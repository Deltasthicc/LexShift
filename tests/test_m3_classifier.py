import json

import pytest

from m3_treatment.classifier import (
    BaselineClassifier,
    Example,
    LLMCache,
    LLMLabeller,
    build_prompt,
    cache_key,
    local_context,
    parse_response,
    per_class_report,
    target_of,
    unmark,
    valid_negative,
)


def test_bench_check_for_negative_labels():
    assert valid_negative("overruled", 5, 2)
    assert valid_negative("doubted", 3, 3)
    assert not valid_negative("overruled", 2, 3)  # a smaller bench cannot overrule a larger one
    assert not valid_negative("overruled", None, 2)  # cannot be checked, so it does not count
    assert not valid_negative("followed", 5, 2)


def test_target_marking_helpers():
    w = "We hold that [[Koushal (supra)]] is overruled."
    assert target_of(w) == "Koushal (supra)"
    assert unmark(w) == "We hold that Koushal (supra) is overruled."
    assert "[[Koushal (supra)]]" in local_context(w)


def test_parse_response_validates_ids_and_labels():
    assert parse_response(json.dumps([{"id": 1, "label": "neutral", "confidence": 0.7}, {"id": 0, "label": "Overruled", "confidence": 1.4}]), 2) == [
        ("overruled", 1.0),
        ("neutral", 0.7),
    ]
    with pytest.raises(ValueError):
        parse_response(json.dumps([{"id": 0, "label": "bad law", "confidence": 1}]), 1)
    with pytest.raises(ValueError):
        parse_response(json.dumps([{"id": 0, "label": "neutral", "confidence": 1}]), 2)


def test_prompt_contains_examples_and_numbered_windows():
    p = build_prompt(["w0 [[A]]", "w1 [[B]]"], [Example("ex [[C]]", "followed")])
    assert "Example 1:\nex [[C]]\nlabel: followed" in p
    assert "Window 0:\nw0 [[A]]" in p and "Window 1:\nw1 [[B]]" in p


class FakeLLM:
    """Stands in for Gemini: labels a window overruled if it says so near the target, else neutral."""

    def __init__(self, fail_first=0):
        self.prompts, self.fail_first = [], fail_first

    def __call__(self, prompt):
        self.prompts.append(prompt)
        if self.fail_first:
            self.fail_first -= 1
            raise RuntimeError("429 quota")
        windows = prompt.split("Window ")[1:]
        out = []
        for chunk in windows:
            i, body = chunk.split(":\n", 1)
            out.append({"id": int(i), "label": "overruled" if "overruled" in body else "neutral", "confidence": 0.9})
        return json.dumps(out)


def test_llm_labeller_batches_caches_and_retries(tmp_path):
    cache = LLMCache(tmp_path / "c.jsonl")
    fake = FakeLLM(fail_first=1)
    sleeps = []
    lab = LLMLabeller(cache, "gemini-test", fake, batch_size=2, sleep=sleeps.append)
    windows = ["[[A]] is overruled.", "[[B]] was cited.", "[[C]] was cited.", "[[B]] was cited."]
    assert lab.label(windows) == 3  # the duplicate is labelled once
    assert lab.calls == 3  # two batches plus one retry after the simulated quota error
    assert sleeps  # backed off before retrying
    row = cache.get(cache_key("gemini-test", "[[A]] is overruled."))
    assert row["label"] == "overruled" and row["confidence"] == 0.9
    # a second run makes no calls, and the cache survives a reload from disk
    assert LLMLabeller(LLMCache(tmp_path / "c.jsonl"), "gemini-test", fake).label(windows) == 0
    # a different model is a different cache entry
    assert cache_key("gemini-other", windows[0]) != cache_key("gemini-test", windows[0])


def test_baseline_learns_a_separable_toy_problem():
    train = [
        ("This Court in [[X (supra)]] is hereby overruled for these reasons.", "overruled"),
        ("We overrule [[Y (supra)]] and declare it is not good law.", "overruled"),
        ("We respectfully follow [[Z (supra)]] and apply it here.", "followed"),
        ("Relying on [[W (supra)]] we follow the ratio.", "followed"),
        ("Counsel cited [[Q v. R (1999) 1 SCC 1]] in the list.", "neutral"),
        ("Reference was made to [[S v. T]] by counsel.", "neutral"),
    ]
    clf = BaselineClassifier(seed=0).fit([w for w, _ in train], [lab for _, lab in train])
    preds = clf.predict(["We overrule [[K (supra)]] for the reasons given.", "We follow [[M (supra)]] and apply it."])
    assert [p for p, _ in preds] == ["overruled", "followed"]
    assert all(0 <= c <= 1 for _, c in preds)


def test_per_class_report_matches_sklearn():
    from sklearn.metrics import precision_recall_fscore_support

    gold = ["neutral", "neutral", "followed", "overruled", "doubted", "neutral", "followed"]
    pred = ["neutral", "followed", "followed", "neutral", "doubted", "neutral", "followed"]
    rep = per_class_report(gold, pred)
    labels = ["followed", "distinguished", "doubted", "overruled", "neutral"]
    p, r, f, s = precision_recall_fscore_support(gold, pred, labels=labels, zero_division=0)
    for i, c in enumerate(labels):
        assert rep["per_class"][c]["precision"] == pytest.approx(p[i])
        assert rep["per_class"][c]["recall"] == pytest.approx(r[i])
        assert rep["per_class"][c]["f1"] == pytest.approx(f[i])
        assert rep["per_class"][c]["support"] == s[i]
    assert rep["accuracy"] == pytest.approx(5 / 7)
    assert rep["confusion"]["overruled"]["neutral"] == 1


def test_cache_key_depends_on_the_few_shot_examples(tmp_path):
    from m3_treatment.classifier import ZERO_SHOT, shots_fingerprint

    ex = [Example("[[A]] is overruled.", "overruled")]
    assert shots_fingerprint([]) == ZERO_SHOT and shots_fingerprint(ex).startswith("fs-")
    assert shots_fingerprint(ex) != shots_fingerprint([Example("[[A]] is overruled.", "neutral")])
    w = "[[B]] was cited."
    assert cache_key("m", w) != cache_key("m", w, shots_fingerprint(ex))
    cache = LLMCache(tmp_path / "c.jsonl")
    assert LLMLabeller(cache, "m", FakeLLM()).label([w]) == 1
    few = LLMLabeller(cache, "m", FakeLLM(), examples=ex)
    assert few.label([w]) == 1  # the zero-shot label is not reused
    row = cache.get(cache_key("m", w, few.shots))
    assert row["shots"] == few.shots and row["n_examples"] == 1


def test_moving_model_aliases_are_refused_and_the_answering_version_is_recorded(tmp_path, monkeypatch):
    from m3_treatment.classifier import gemini_caller, is_moving_alias

    assert is_moving_alias("gemini-flash-latest") and is_moving_alias("gemini-3-flash-preview")
    assert not is_moving_alias("gemini-2.5-flash") and not is_moving_alias("gemini-3.8-flash")
    monkeypatch.setenv("GEMINI_API_KEY", "unused")
    with pytest.raises(RuntimeError, match="pin a stable model id"):
        gemini_caller("gemini-flash-latest")

    def call(prompt):
        return json.dumps([{"id": 0, "label": "neutral", "confidence": 0.5}])

    call.model_version = "gemini-2.5-flash-001"
    LLMLabeller(LLMCache(tmp_path / "c.jsonl"), "gemini-2.5-flash", call, batch_size=1).label(["[[X v. Y]] was cited."])
    row = json.loads((tmp_path / "c.jsonl").read_text(encoding="utf-8"))
    assert row["model"] == "gemini-2.5-flash" and row["model_version"] == "gemini-2.5-flash-001"
