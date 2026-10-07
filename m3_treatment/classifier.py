"""Treatment classifier: followed / distinguished / doubted / overruled / neutral, on a citation window.

Main: LLM few-shot on the window, run OFFLINE with every output cached (nothing at demo time).
Baseline: tf-idf + logistic regression. Report precision, recall and F1 per class on the hand-labelled gold set
(data/treatment_gold.csv), never accuracy alone: overruled is rare.

No raw keyword matching for treatment. Cue words may only help FIND candidate windows for labelling (to fix class
imbalance); the label itself comes from reading. "set aside" is not overruling.

Windows given to either classifier mark the cited case with [[ ]] (m3_treatment.windows.mark_target), because one
window often cites several cases and they can be treated differently ("Following X, we overrule Y").

LLM: Google Gemini through the `google-genai` SDK, key in the GEMINI_API_KEY environment variable. Calls happen only
in `python -m m3_treatment.pipeline label-llm`; `classify_llm()` reads the cache and never calls the API.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Iterable, Sequence

from common.schema import NEGATIVE_LABELS, TREATMENT_LABELS

LABELS = TREATMENT_LABELS
PROMPT_VERSION = "v1"
_TARGET = re.compile(r"\[\[(.+?)\]\]", re.DOTALL)

LABEL_GUIDE = """\
Labels, always about how THE CITING COURT ITSELF treats the TARGET case (the one inside [[ ]]):
- followed: the court relies on, applies, follows or approves the TARGET as authority for its own reasoning.
- distinguished: the court holds the TARGET does not apply here because the facts or the question differ.
- doubted: the court disagrees with, criticises or doubts the TARGET, calls it per incuriam, or refers its
  correctness to a larger bench, WITHOUT overruling it.
- overruled: the court itself explicitly overrules the TARGET or declares it is no longer good law.
- neutral: the TARGET is only mentioned, listed, quoted, summarised, cited by counsel, or described without the
  court evaluating it; also when the window reports what some OTHER court did to the TARGET.
Traps: "set aside", "reversed" or "quashed" on appeal is a reversal of the case under appeal, never overruled.
"Objection overruled" or "contention overruled" is about an argument, never a precedent. A case that overrules
another case is itself followed or neutral, not overruled. When unsure between neutral and another label, use neutral."""

SYSTEM_INSTRUCTION = (
    "You label how a judgment of the Supreme Court of India treats an earlier case it cites. "
    "You read short citation windows and return one label per window as JSON.\n\n" + LABEL_GUIDE
)

RESPONSE_SCHEMA = {
    "type": "array",
    "items": {
        "type": "object",
        "properties": {
            "id": {"type": "integer"},
            "label": {"type": "string", "enum": list(LABELS)},
            "confidence": {"type": "number"},
        },
        "required": ["id", "label", "confidence"],
    },
}


def target_of(marked_window: str) -> str:
    m = _TARGET.search(marked_window)
    return m.group(1).strip() if m else ""


def unmark(marked_window: str) -> str:
    return marked_window.replace("[[", "").replace("]]", "")


def valid_negative(label: str, citing_bench: int | None, cited_bench: int | None) -> bool:
    """A negative label counts only if the citing bench is at least as large as the cited bench.

    An unknown bench size on either side cannot be checked, so the negative does not count (it is still shown).
    """
    if label not in NEGATIVE_LABELS or citing_bench is None or cited_bench is None:
        return False
    return citing_bench >= cited_bench


# ----------------------------------------------------------------------------------------------------------------
# LLM (Gemini), offline and cached
# ----------------------------------------------------------------------------------------------------------------
ZERO_SHOT = "zero-shot"


def shots_fingerprint(examples: Sequence["Example"]) -> str:
    """"zero-shot", or "fs-<hash>" of the exact few-shot examples (windows and labels, in prompt order)."""
    if not examples:
        return ZERO_SHOT
    blob = "\x1e".join(f"{ex.label}\x1f{ex.window}" for ex in examples)
    return "fs-" + hashlib.sha256(blob.encode("utf-8")).hexdigest()[:16]


def cache_key(model: str, marked_window: str, shots: str = ZERO_SHOT) -> str:
    """Everything that can change the answer is in the key: prompt version, model, the few-shot examples (their
    fingerprint) and the marked window. A label made zero-shot is therefore never reused once examples exist."""
    return hashlib.sha256(f"{PROMPT_VERSION}\x1f{model}\x1f{shots}\x1f{marked_window}".encode("utf-8")).hexdigest()


class LLMCache:
    """Append-only JSON Lines cache: one {key, model, prompt_version, label, confidence} per labelled window."""

    def __init__(self, path: str | os.PathLike):
        self.path = Path(path)
        self._rows: dict[str, dict] = {}
        if self.path.exists():
            with open(self.path, encoding="utf-8") as fh:
                for line in fh:
                    if line.strip():
                        row = json.loads(line)
                        self._rows[row["key"]] = row

    def __contains__(self, key: str) -> bool:
        return key in self._rows

    def __len__(self) -> int:
        return len(self._rows)

    def get(self, key: str) -> dict | None:
        return self._rows.get(key)

    def put_many(self, rows: list[dict]) -> None:
        if not rows:
            return
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with open(self.path, "a", encoding="utf-8", newline="\n") as fh:
            for row in rows:
                fh.write(json.dumps(row, ensure_ascii=False) + "\n")
                self._rows[row["key"]] = row


@dataclass(frozen=True)
class Example:
    """A hand-labelled few-shot example (from the gold set's few-shot pool, never from the evaluation part)."""

    window: str  # marked
    label: str


def build_prompt(windows: Sequence[str], examples: Sequence[Example] = ()) -> str:
    parts = []
    if examples:
        parts.append("Labelled examples:")
        for i, ex in enumerate(examples, 1):
            parts.append(f"Example {i}:\n{ex.window}\nlabel: {ex.label}")
        parts.append("")
    parts.append(
        "Label each window below. Return a JSON array with one object per window: "
        '{"id": <window id>, "label": <one of ' + ", ".join(LABELS) + '>, "confidence": <0 to 1>}.'
    )
    for i, w in enumerate(windows):
        parts.append(f"Window {i}:\n{w}")
    return "\n\n".join(parts)


def parse_response(text: str, n: int) -> list[tuple[str, float]]:
    """[(label, confidence)] in window order; raises ValueError if anything is missing or invalid."""
    data = json.loads(text)
    if not isinstance(data, list):
        raise ValueError("response is not a JSON array")
    out: dict[int, tuple[str, float]] = {}
    for item in data:
        i, label, conf = int(item["id"]), str(item["label"]).strip().lower(), float(item["confidence"])
        if label not in LABELS:
            raise ValueError(f"unknown label {label!r}")
        if not 0 <= i < n:
            raise ValueError(f"id {i} out of range")
        out[i] = (label, min(1.0, max(0.0, conf)))
    missing = [i for i in range(n) if i not in out]
    if missing:
        raise ValueError(f"no label for windows {missing}")
    return [out[i] for i in range(n)]


def is_moving_alias(model: str) -> bool:
    """A model id that Google re-points to new releases ("gemini-flash-latest") or may change at short notice
    ("-preview", "-exp"). Labels made under it could silently come from different models under one cache key."""
    return bool(re.search(r"latest|preview|exp", model))


def gemini_caller(model: str, temperature: float = 0.0) -> Callable[[str], str]:
    """A function prompt -> JSON text backed by the Gemini API (GEMINI_API_KEY).

    The returned function records the exact version that answered in its `model_version` attribute, so every cache
    row says which model produced it.
    """
    from google import genai
    from google.genai import types

    if is_moving_alias(model):
        raise RuntimeError(f"m3_treatment.llm.model {model!r} is a moving alias or a preview; pin a stable model id")
    if not (os.environ.get("GEMINI_API_KEY") or os.environ.get("GOOGLE_API_KEY")):
        raise RuntimeError("set GEMINI_API_KEY to run the offline LLM labelling")
    client = genai.Client()
    config = types.GenerateContentConfig(
        system_instruction=SYSTEM_INSTRUCTION,
        temperature=temperature,
        response_mime_type="application/json",
        response_json_schema=RESPONSE_SCHEMA,
    )

    def call(prompt: str) -> str:
        response = client.models.generate_content(model=model, contents=prompt, config=config)
        call.model_version = getattr(response, "model_version", None) or model
        return response.text

    call.model_version = None
    return call


class LLMLabeller:
    """Labels marked windows through `call` (prompt -> JSON text), in batches, with cache, pacing and retries."""

    def __init__(
        self,
        cache: LLMCache,
        model: str,
        call: Callable[[str], str],
        examples: Sequence[Example] = (),
        batch_size: int = 10,
        min_interval_s: float = 0.0,
        max_retries: int = 4,
        sleep: Callable[[float], None] = time.sleep,
    ):
        self.cache, self.model, self.call, self.examples = cache, model, call, list(examples)
        self.batch_size, self.min_interval_s, self.max_retries, self.sleep = batch_size, min_interval_s, max_retries, sleep
        self.shots = shots_fingerprint(self.examples)
        self.calls = 0
        self._last = 0.0

    def label(self, marked_windows: Iterable[str], progress: Callable[[int, int], None] | None = None) -> int:
        """Label every uncached window; returns how many were newly labelled. Failures raise after retries."""
        todo, seen = [], set()
        for w in marked_windows:
            k = cache_key(self.model, w, self.shots)
            if k not in self.cache and k not in seen:
                seen.add(k)
                todo.append(w)
        done = 0
        for start in range(0, len(todo), self.batch_size):
            batch = todo[start : start + self.batch_size]
            results = self._call_with_retries(batch)
            self.cache.put_many(
                [
                    {
                        "key": cache_key(self.model, w, self.shots),
                        "model": self.model,
                        "model_version": getattr(self.call, "model_version", None),
                        "prompt_version": PROMPT_VERSION,
                        "shots": self.shots,
                        "n_examples": len(self.examples),
                        "label": lab,
                        "confidence": conf,
                    }
                    for w, (lab, conf) in zip(batch, results)
                ]
            )
            done += len(batch)
            if progress:
                progress(done, len(todo))
        return done

    def _call_with_retries(self, batch: list[str]) -> list[tuple[str, float]]:
        prompt = build_prompt(batch, self.examples)
        delay = 2.0
        for attempt in range(self.max_retries + 1):
            wait = self.min_interval_s - (time.monotonic() - self._last)
            if wait > 0:
                self.sleep(wait)
            self._last = time.monotonic()
            try:
                self.calls += 1
                return parse_response(self.call(prompt), len(batch))
            except Exception:  # noqa: BLE001 - API, quota and malformed-output errors are all retried
                if attempt == self.max_retries:
                    raise
                self.sleep(delay)
                delay *= 2
        raise AssertionError("unreachable")


# ----------------------------------------------------------------------------------------------------------------
# Baseline: tf-idf + logistic regression
# ----------------------------------------------------------------------------------------------------------------
_LOCAL = 150  # characters either side of the target that form the "near the target" view


def local_context(marked_window: str) -> str:
    m = _TARGET.search(marked_window)
    if not m:
        return marked_window
    return marked_window[max(0, m.start() - _LOCAL) : m.end() + _LOCAL]


class BaselineClassifier:
    """tf-idf (word 1-2 grams) over the whole window plus a second tf-idf over the text near the target, then a
    class-balanced logistic regression (rare classes such as overruled get more weight)."""

    def __init__(self, C: float = 4.0, seed: int = 0):
        self.C, self.seed = C, seed
        self.model = None

    def _features(self, windows: Sequence[str], fit: bool):
        from scipy.sparse import hstack

        whole = [unmark(w) for w in windows]
        near = [unmark(local_context(w)) for w in windows]
        if fit:
            return hstack([self.vec_whole.fit_transform(whole), self.vec_near.fit_transform(near)]).tocsr()
        return hstack([self.vec_whole.transform(whole), self.vec_near.transform(near)]).tocsr()

    def fit(self, windows: Sequence[str], labels: Sequence[str]) -> "BaselineClassifier":
        from sklearn.feature_extraction.text import TfidfVectorizer
        from sklearn.linear_model import LogisticRegression

        self.vec_whole = TfidfVectorizer(ngram_range=(1, 2), min_df=1, sublinear_tf=True, lowercase=True)
        self.vec_near = TfidfVectorizer(ngram_range=(1, 2), min_df=1, sublinear_tf=True, lowercase=True)
        X = self._features(windows, fit=True)
        self.model = LogisticRegression(C=self.C, class_weight="balanced", max_iter=5000, random_state=self.seed)
        self.model.fit(X, list(labels))
        return self

    def predict(self, windows: Sequence[str]) -> list[tuple[str, float]]:
        if self.model is None:
            raise RuntimeError("baseline classifier is not trained (it needs the hand-labelled gold set)")
        proba = self.model.predict_proba(self._features(windows, fit=False))
        classes = list(self.model.classes_)
        return [(classes[row.argmax()], float(row.max())) for row in proba]


# ----------------------------------------------------------------------------------------------------------------
# Evaluation helpers
# ----------------------------------------------------------------------------------------------------------------
def per_class_report(gold: Sequence[str], pred: Sequence[str]) -> dict:
    """Precision, recall, F1 and support per class, plus macro-F1, accuracy and the confusion matrix."""
    rows = {}
    for c in LABELS:
        tp = sum(1 for g, p in zip(gold, pred) if g == c and p == c)
        fp = sum(1 for g, p in zip(gold, pred) if g != c and p == c)
        fn = sum(1 for g, p in zip(gold, pred) if g == c and p != c)
        prec = tp / (tp + fp) if tp + fp else 0.0
        rec = tp / (tp + fn) if tp + fn else 0.0
        f1 = 2 * prec * rec / (prec + rec) if prec + rec else 0.0
        rows[c] = {"precision": prec, "recall": rec, "f1": f1, "support": tp + fn}
    present = [c for c in LABELS if rows[c]["support"] > 0]
    macro = sum(rows[c]["f1"] for c in present) / len(present) if present else 0.0
    acc = sum(1 for g, p in zip(gold, pred) if g == p) / len(gold) if gold else 0.0
    confusion = {g: {p: sum(1 for a, b in zip(gold, pred) if a == g and b == p) for p in LABELS} for g in LABELS}
    return {"per_class": rows, "macro_f1": macro, "accuracy": acc, "n": len(gold), "confusion": confusion}


# ----------------------------------------------------------------------------------------------------------------
# Contract-level helpers (read frozen outputs only)
# ----------------------------------------------------------------------------------------------------------------
def _m3_cfg() -> dict:
    from common.config import load_config

    return load_config().get("m3_treatment", {})


def default_cache() -> LLMCache:
    from common.config import ROOT

    return LLMCache(ROOT / _m3_cfg().get("llm", {}).get("cache", "data/llm_labels/m3_llm_labels.jsonl"))


def classify_llm(window: str) -> tuple[str, float]:
    """(label, confidence) from the cached LLM run with the current few-shot pool. Never calls the API; a window not
    labelled under the current pool (or zero-shot when there is none) is an error."""
    from m3_treatment.pipeline import few_shot_examples

    model = _m3_cfg()["llm"]["model"]
    row = default_cache().get(cache_key(model, window, shots_fingerprint(few_shot_examples())))
    if row is None:
        raise KeyError("window not in the LLM cache; run `python -m m3_treatment.pipeline label-llm` offline first")
    return row["label"], float(row["confidence"])


_BASELINE: BaselineClassifier | None = None


def classify_baseline(window: str) -> tuple[str, float]:
    """(label, confidence) from the tf-idf + logistic-regression baseline, trained on the whole gold set."""
    global _BASELINE
    if _BASELINE is None:
        from m3_treatment.gold import final_labels, load_gold

        items = final_labels(load_gold())
        if not items:
            raise RuntimeError("data/treatment_gold.csv has no labels yet; the baseline needs the hand-labelled gold set")
        _BASELINE = BaselineClassifier(seed=0).fit([w for w, _ in items], [lab for _, lab in items])
    return _BASELINE.predict([window])[0]
