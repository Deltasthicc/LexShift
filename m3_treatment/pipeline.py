"""The offline M3 pipeline, step by step (each step reads the previous step's file, so any step can be re-run):

  python -m m3_treatment.pipeline extract       judgments.jsonl -> m3_mentions.jsonl   (+ resolution report)
  python -m m3_treatment.gold sample            m3_mentions.jsonl -> blank labelling sheets (humans label them)
  python -m m3_treatment.pipeline label-llm     m3_mentions.jsonl -> Gemini labels in the cache (needs GEMINI_API_KEY)
  python -m m3_treatment.pipeline evaluate      gold set -> per-class P/R/F1 for the LLM and the baseline
  python -m m3_treatment.pipeline citations     m3_mentions.jsonl + labels -> citations.jsonl
  python -m m3_treatment.pipeline health        citations.jsonl -> doc_health.jsonl (health, authority, evidence)

`python -m m3_treatment.citations build` runs extract + citations, `python -m m3_treatment.scores build` runs health.
Only `label-llm` touches the network. Everything the live demo reads (doc_health.jsonl) is a frozen file.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from collections import Counter, defaultdict
from pathlib import Path

from common.config import ROOT, load_config, resolve_path
from common.io import read_jsonl, write_jsonl
from common.schema import NEGATIVE_LABELS, TREATMENT_LABELS, Citation, DocHealth

from m3_treatment.citations import extract_mentions
from m3_treatment.classifier import (
    BaselineClassifier,
    Example,
    LLMCache,
    LLMLabeller,
    cache_key,
    gemini_caller,
    per_class_report,
    unmark,
    valid_negative,
)
from m3_treatment.graph import authority_scores, pagerank_raw
from m3_treatment.resolver import CorpusIndex, bench_of, metadata_view
from m3_treatment.text import clean_text, sentence_spans
from m3_treatment.windows import is_appeal_history, marked_window, same_parties


def cfg() -> dict:
    return load_config()["m3_treatment"]


def _path(key: str) -> Path:
    return ROOT / cfg()[key]


def load_mentions(path: Path | None = None) -> list[dict]:
    path = path or _path("mentions")
    if not path.exists():
        raise FileNotFoundError(f"{path} not found; run `python -m m3_treatment.pipeline extract` first")
    return list(read_jsonl(path))


def _report_dir() -> Path:
    d = _path("reports_dir")
    d.mkdir(parents=True, exist_ok=True)
    return d


# ----------------------------------------------------------------------------------------------------------------
# extract
# ----------------------------------------------------------------------------------------------------------------
def mention_records(rec: dict, index: CorpusIndex, wcfg: dict) -> list[dict]:
    """Every mention in one judgment, resolved, windowed and appeal-checked (no label yet)."""
    citing = rec["doc_id"]
    text = clean_text(rec.get("text") or "")
    if not text:
        return []
    spans = sentence_spans(text)
    mentions = extract_mentions(text)
    citing_title = rec.get("title", "")
    citing_bench = bench_of(rec)
    out = []
    for i, m in enumerate(mentions):
        src = mentions[m.antecedent] if m.antecedent is not None else m
        res = index.resolve(src.cites, src.name, src.year)
        cited_doc = res.doc_id
        cited_title = index.meta[cited_doc].title if cited_doc else src.name
        is_self = cited_doc == citing or (cited_doc is None and not src.cites and same_parties(citing_title, src.name))
        is_sc = bool(cited_doc) or any(c.is_sc for c in src.cites) or not src.cites
        window = marked_window(text, m.start, m.end, wcfg["before"], wcfg["after"], wcfg["max_chars"], spans)
        out.append(
            {
                "citing_doc": citing,
                "start": m.start,
                "end": m.end,
                "kind": m.kind,
                "cited_raw": m.raw(text) if m.kind in ("full", "cite", "name") else f"{m.raw(text)} -> {src.raw(text)}",
                "cites": [c.key for c in src.cites],
                "cited_doc": cited_doc,
                "resolution": res.method,
                "resolution_score": res.score,
                "marked_window": window,
                "is_self": is_self,
                "is_appeal_history": (not is_self) and is_appeal_history(unmark(window), citing_title, cited_title, cited_is_sc=is_sc),
                "citing_bench": citing_bench,
                "cited_bench": index.meta[cited_doc].bench if cited_doc else None,
                "antecedent_kind": src.kind if m.antecedent is not None else None,
            }
        )
    return out


def run_extract(limit: int | None = None) -> dict:
    jpath = resolve_path("judgments")
    if not jpath.exists():
        raise FileNotFoundError(f"{jpath} not found; M1 ships judgments.jsonl")
    c = cfg()
    index = CorpusIndex((metadata_view(r) for r in read_jsonl(jpath)), **c.get("resolver", {}))
    t0 = time.time()
    n_docs = 0

    def records():
        nonlocal n_docs
        for rec in read_jsonl(jpath):
            if limit is not None and n_docs >= limit:
                break
            n_docs += 1
            yield from mention_records(rec, index, c["window"])

    rows = list(records())
    write_jsonl(_path("mentions"), rows)
    rep = resolution_report(rows, n_docs, len(index.meta), time.time() - t0)
    (_report_dir() / "resolution.md").write_text(rep["markdown"], encoding="utf-8")
    return rep


def resolution_report(rows: list[dict], n_docs: int, corpus_size: int, seconds: float) -> dict:
    """Resolution rate overall, by mention kind, and for citations that name a Supreme Court reporter."""
    edges = [r for r in rows if not r["is_self"]]
    total = len(edges)
    resolved = sum(1 for r in edges if r["cited_doc"])
    by_kind: dict[str, Counter] = defaultdict(Counter)
    for r in edges:
        by_kind[r["kind"]]["resolved" if r["cited_doc"] else "unresolved"] += 1
    sc_cited = [r for r in edges if r["cites"] and any(k.split("|")[0] in ("SCC", "SCR", "INSC", "SCALE", "JT") or "|SC|" in k for k in r["cites"])]
    sc_res = sum(1 for r in sc_cited if r["cited_doc"])
    methods = Counter(r["resolution"] for r in edges if r["cited_doc"])
    appeal = sum(1 for r in edges if r["is_appeal_history"])
    pairs = {(r["citing_doc"], r["cited_doc"]) for r in edges if r["cited_doc"] and not r["is_appeal_history"]}
    pct = lambda a, b: f"{100 * a / b:.1f}%" if b else "n/a"  # noqa: E731
    lines = [
        "# M3 citation resolution report",
        "",
        f"Generated by `python -m m3_treatment.pipeline extract` over {n_docs} judgments (index of {corpus_size}) in {seconds:.1f}s.",
        "Self-references (running headers, the judgment's own citation) are excluded from every count below.",
        "",
        "| Measure | Count | Rate |",
        "|---|---|---|",
        f"| Mentions (all kinds) | {total} | |",
        f"| Resolved to a corpus judgment | {resolved} | {pct(resolved, total)} |",
        f"| Mentions carrying a Supreme Court reporter citation | {len(sc_cited)} | |",
        f"| ... of which resolved | {sc_res} | {pct(sc_res, len(sc_cited))} |",
        f"| Tagged appeal history (excluded from treatment) | {appeal} | {pct(appeal, total)} |",
        f"| Distinct citing -> cited edges (resolved, not appeal history) | {len(pairs)} | |",
        "",
        "By mention kind:",
        "",
        "| Kind | Resolved | Unresolved | Rate |",
        "|---|---|---|---|",
    ]
    for k in ("full", "cite", "name", "supra", "alias"):
        c = by_kind.get(k, Counter())
        lines.append(f"| {k} | {c['resolved']} | {c['unresolved']} | {pct(c['resolved'], c['resolved'] + c['unresolved'])} |")
    lines += ["", "Resolution method: " + ", ".join(f"{m} {n}" for m, n in methods.most_common()), ""]
    lines.append(
        "Unresolved mentions are kept in citations.jsonl with cited_doc = null. Most are High Court or foreign "
        "decisions, or Supreme Court judgments outside the corpus subset, which can never resolve."
    )
    return {
        "mentions": total,
        "resolved": resolved,
        "sc_cited": len(sc_cited),
        "sc_resolved": sc_res,
        "appeal_history": appeal,
        "edges": len(pairs),
        "markdown": "\n".join(lines) + "\n",
    }


# ----------------------------------------------------------------------------------------------------------------
# label-llm
# ----------------------------------------------------------------------------------------------------------------
def in_llm_scope(m: dict, scope: str) -> bool:
    if m["is_self"] or m["is_appeal_history"]:
        return False
    return scope == "all" or bool(m["cited_doc"])


def few_shot_examples(per_class: int) -> list[Example]:
    from m3_treatment.gold import final_labels, load_gold

    pool, _ = split_gold(final_labels(load_gold()), per_class)
    return [Example(w, lab) for w, lab in pool]


def split_gold(items: list[tuple[str, str]], per_class: int) -> tuple[list[tuple[str, str]], list[tuple[str, str]]]:
    """(few-shot pool, evaluation set): the first `per_class` windows of each label in hash order go to the pool."""
    import hashlib

    ordered = sorted(items, key=lambda it: hashlib.sha1(it[0].encode("utf-8")).hexdigest())
    taken: Counter = Counter()
    pool, rest = [], []
    for w, lab in ordered:
        if taken[lab] < per_class:
            pool.append((w, lab))
            taken[lab] += 1
        else:
            rest.append((w, lab))
    return pool, rest


def run_label_llm(limit: int | None = None, dry_run: bool = False, call=None) -> dict:
    c = cfg()["llm"]
    mentions = load_mentions()
    windows = list(dict.fromkeys(m["marked_window"] for m in mentions if in_llm_scope(m, c["scope"])))
    gold_windows = [w for w, _ in _gold_items()]
    windows = list(dict.fromkeys(gold_windows + windows))  # the gold set is always labelled, for the F1 table
    cache = LLMCache(ROOT / c["cache"])
    todo = [w for w in windows if cache_key(c["model"], w) not in cache]
    if limit is not None:
        todo = todo[:limit]
    chars = sum(len(w) for w in todo)
    requests = -(-len(todo) // max(1, c["batch_size"]))
    info = {
        "model": c["model"],
        "in_scope": len(windows),
        "already_cached": len(windows) - len(todo) if limit is None else None,
        "to_label": len(todo),
        "requests": requests,
        "approx_input_tokens": chars // 4 + 900 * requests,  # windows plus the instructions repeated per request
    }
    if dry_run or not todo:
        return info
    examples = few_shot_examples(c["few_shot_per_class"])
    labeller = LLMLabeller(
        cache,
        c["model"],
        call or gemini_caller(c["model"]),
        examples=examples,
        batch_size=c["batch_size"],
        min_interval_s=c["min_interval_s"],
        max_retries=c["max_retries"],
    )
    progress = lambda d, t: print(f"\r  labelled {d}/{t}", end="", flush=True)  # noqa: E731
    info["labelled"] = labeller.label(todo, progress)
    info["api_calls"] = labeller.calls
    print()
    return info


def _gold_items() -> list[tuple[str, str]]:
    from m3_treatment.gold import final_labels, load_gold

    return final_labels(load_gold())


# ----------------------------------------------------------------------------------------------------------------
# evaluate
# ----------------------------------------------------------------------------------------------------------------
def run_evaluate(folds: int = 5, seed: int = 0) -> dict:
    """Per-class P/R/F1 of the LLM (cached) and the baseline (stratified k-fold) on the same evaluation windows."""
    c = cfg()
    items = _gold_items()
    if not items:
        raise RuntimeError("data/treatment_gold.csv has no settled labels yet")
    pool, evalset = split_gold(items, c["llm"]["few_shot_per_class"])
    windows = [w for w, _ in evalset]
    gold = [lab for _, lab in evalset]
    out: dict = {"n_eval": len(evalset), "n_fewshot_pool": len(pool), "label_counts": dict(Counter(gold))}

    cache = LLMCache(ROOT / c["llm"]["cache"])
    rows = [cache.get(cache_key(c["llm"]["model"], w)) for w in windows]
    missing = sum(r is None for r in rows)
    if missing:
        out["llm"] = {"skipped": f"{missing} gold windows are not in the LLM cache; run label-llm"}
    else:
        out["llm"] = per_class_report(gold, [r["label"] for r in rows])

    k = min(folds, min(Counter(gold).values()))
    if k < 2:
        out["baseline"] = {"skipped": "every class needs at least 2 gold windows for cross-validation"}
    else:
        from sklearn.model_selection import StratifiedKFold

        pred = [""] * len(windows)
        for tr, te in StratifiedKFold(n_splits=k, shuffle=True, random_state=seed).split(windows, gold):
            clf = BaselineClassifier(seed=seed).fit([windows[i] for i in tr], [gold[i] for i in tr])
            for i, (lab, _) in zip(te, clf.predict([windows[i] for i in te])):
                pred[i] = lab
        out["baseline"] = per_class_report(gold, pred)
        out["baseline"]["folds"] = k
    md = f1_markdown(out, c["llm"]["model"])
    (_report_dir() / "classifier_f1.md").write_text(md, encoding="utf-8")
    (_report_dir() / "classifier_f1.json").write_text(json.dumps(out, indent=2), encoding="utf-8")
    out["markdown"] = md
    return out


def f1_markdown(out: dict, model: str) -> str:
    lines = [
        "# M3 treatment classifier: per-class precision, recall and F1",
        "",
        f"Evaluation windows: {out['n_eval']} hand-labelled (few-shot pool of {out['n_fewshot_pool']} held out). "
        f"Gold label counts: {out['label_counts']}.",
        "",
    ]
    for name, title in (("llm", f"LLM few-shot ({model}, cached)"), ("baseline", "tf-idf + logistic regression (stratified CV)")):
        r = out.get(name, {})
        lines.append(f"## {title}")
        lines.append("")
        if "skipped" in r:
            lines += [f"Not run: {r['skipped']}.", ""]
            continue
        lines += ["| Class | Precision | Recall | F1 | Support |", "|---|---|---|---|---|"]
        for lab in TREATMENT_LABELS:
            p = r["per_class"][lab]
            lines.append(f"| {lab} | {p['precision']:.3f} | {p['recall']:.3f} | {p['f1']:.3f} | {p['support']} |")
        lines += ["", f"Macro-F1 {r['macro_f1']:.3f} (over classes present), accuracy {r['accuracy']:.3f}, n = {r['n']}.", ""]
        lines += ["Confusion (rows gold, columns predicted):", "", "| | " + " | ".join(TREATMENT_LABELS) + " |", "|---" * (len(TREATMENT_LABELS) + 1) + "|"]
        for g in TREATMENT_LABELS:
            lines.append(f"| {g} | " + " | ".join(str(r["confusion"][g][p]) for p in TREATMENT_LABELS) + " |")
        lines.append("")
    return "\n".join(lines)


# ----------------------------------------------------------------------------------------------------------------
# citations
# ----------------------------------------------------------------------------------------------------------------
def run_citations(labels: str | None = None) -> dict:
    """citations.jsonl: one record per mention (self-references dropped), with label, confidence and bench check.

    Mentions outside the LLM scope (unresolved, appeal history) are labelled `neutral` with confidence 0.0, which
    means "not classified": they cannot move any score (no corpus target, or a reversal on appeal).
    """
    c = cfg()
    labels = labels or c["labels"]
    mentions = load_mentions()
    cache = LLMCache(ROOT / c["llm"]["cache"])
    baseline = None
    if labels == "baseline":
        items = _gold_items()
        if not items:
            raise RuntimeError("--labels baseline needs the hand-labelled gold set")
        baseline = BaselineClassifier(seed=0).fit([w for w, _ in items], [lab for _, lab in items])
    scope = c["llm"]["scope"]
    targets = [m for m in mentions if not m["is_self"] and in_llm_scope(m, scope)]
    if labels == "llm":
        missing = [m for m in targets if cache_key(c["llm"]["model"], m["marked_window"]) not in cache]
        if missing:
            raise RuntimeError(f"{len(missing)} in-scope windows have no cached LLM label; run `python -m m3_treatment.pipeline label-llm`")
    predicted: dict[str, tuple[str, float]] = {}
    if baseline is not None:
        uniq = list(dict.fromkeys(m["marked_window"] for m in targets))
        predicted = dict(zip(uniq, baseline.predict(uniq)))
    out, counts = [], Counter()
    for m in mentions:
        if m["is_self"]:
            continue
        if in_llm_scope(m, scope):
            if labels == "llm":
                row = cache.get(cache_key(c["llm"]["model"], m["marked_window"]))
                label, conf = row["label"], float(row["confidence"])
            else:
                label, conf = predicted[m["marked_window"]]
        else:
            label, conf = "neutral", 0.0
        rec = Citation(
            citing_doc=m["citing_doc"],
            cited_doc=m["cited_doc"],
            cited_raw=m["cited_raw"],
            window=unmark(m["marked_window"]),
            is_appeal_history=m["is_appeal_history"],
            label=label,
            confidence=round(conf, 4),
            citing_bench=m["citing_bench"],
            cited_bench=m["cited_bench"],
            valid_negative=bool(m["cited_doc"]) and not m["is_appeal_history"] and valid_negative(label, m["citing_bench"], m["cited_bench"]),
        )
        rec.validate()
        out.append(rec.to_dict())
        counts[label] += 1
    n = write_jsonl(resolve_path("citations"), out)
    return {"records": n, "label_source": labels, "labels": dict(counts), "valid_negatives": sum(r["valid_negative"] for r in out)}


# ----------------------------------------------------------------------------------------------------------------
# health
# ----------------------------------------------------------------------------------------------------------------
def _strength(label: str, values: dict) -> float:
    return values.get(label, values["default"])


def run_health() -> dict:
    """doc_health.jsonl for EVERY judgment in the corpus: health, authority and the evidence behind them."""
    c = cfg()
    values = c["health_values"]
    min_conf = c["min_confidence"]
    acfg = c["authority"]
    benches: dict[str, int | None] = {}
    for rec in read_jsonl(resolve_path("judgments")):
        benches[rec["doc_id"]] = bench_of(rec)
    cits = [Citation.from_dict(r) for r in read_jsonl(resolve_path("citations"))]

    edges = [
        (r.citing_doc, r.cited_doc, r.confidence)
        for r in cits
        if r.cited_doc and not r.is_appeal_history and r.label in acfg["edge_labels"] and r.confidence > 0
    ]
    pr = pagerank_raw(edges, nodes=benches, damping=c["pagerank"]["damping"], tol=c["pagerank"]["tol"], max_iter=c["pagerank"]["max_iter"])
    auth = authority_scores(pr, benches, acfg["max_bench"], acfg["unknown_bench"])

    offences: dict[str, list[str]] = {}
    statutes = resolve_path("doc_statutes")
    if statutes.exists():
        for rec in read_jsonl(statutes):
            offences[rec["doc_id"]] = sorted({r["offence_id"] for r in rec.get("refs", []) if r.get("offence_id")})

    negatives: dict[str, list] = defaultdict(list)
    positives: dict[str, list] = defaultdict(list)
    for r in cits:
        if not r.cited_doc or r.is_appeal_history:
            continue
        if r.valid_negative and r.confidence >= min_conf:
            negatives[r.cited_doc].append(r)
        elif r.label == "followed" and r.confidence >= min_conf:
            positives[r.cited_doc].append(r)

    out = []
    flagged = Counter()
    for doc_id in benches:
        negs = sorted(negatives.get(doc_id, []), key=lambda r: (_strength(r.label, values), -r.confidence, r.citing_doc))
        health = min([_strength(r.label, values) for r in negs], default=values["default"])
        # one evidence item per citing judgment, strongest first, then a few positive treatments for context
        evidence, seen = [], set()
        for r in negs + sorted(positives.get(doc_id, []), key=lambda r: (-(r.citing_bench or 0), -r.confidence, r.citing_doc)):
            if (r.citing_doc, r.label) in seen:
                continue
            seen.add((r.citing_doc, r.label))
            item = {"citing_doc": r.citing_doc, "label": r.label, "sentence": r.window, "confidence": r.confidence, "citing_bench": r.citing_bench}
            if r.label in NEGATIVE_LABELS:
                item["offence_ids"] = offences.get(r.citing_doc, [])  # [] = unknown: the penalty always applies
            evidence.append(item)
            if len(evidence) >= c["max_evidence"]:
                break
        if negs:
            flagged[negs[0].label] += 1
        rec = DocHealth(doc_id=doc_id, health=round(health, 4), authority=round(auth.get(doc_id, 0.0), 6), evidence=evidence)
        rec.validate()
        out.append(rec.to_dict())
    n = write_jsonl(resolve_path("doc_health"), out)
    return {"judgments": n, "edges_in_pagerank": len(edges), "lowered_health": dict(flagged)}


# ----------------------------------------------------------------------------------------------------------------
def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="python -m m3_treatment.pipeline", description=__doc__.split("\n\n")[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    e = sub.add_parser("extract")
    e.add_argument("--limit", type=int, help="only the first N judgments (for a quick look)")
    l = sub.add_parser("label-llm")  # noqa: E741
    l.add_argument("--limit", type=int, help="label at most N new windows this run")
    l.add_argument("--dry-run", action="store_true", help="count windows and estimate tokens, call nothing")
    sub.add_parser("evaluate")
    ci = sub.add_parser("citations")
    ci.add_argument("--labels", choices=("llm", "baseline"), help="override m3_treatment.labels")
    sub.add_parser("health")
    b = sub.add_parser("build", help="extract + citations + health (needs the LLM cache, or --labels baseline)")
    b.add_argument("--labels", choices=("llm", "baseline"))
    args = ap.parse_args(argv)

    if args.cmd in ("extract", "build"):
        rep = run_extract(getattr(args, "limit", None))
        print(rep.pop("markdown"))
    if args.cmd == "label-llm":
        print(json.dumps(run_label_llm(args.limit, args.dry_run), indent=2))
    if args.cmd == "evaluate":
        print(run_evaluate().pop("markdown"))
    if args.cmd in ("citations", "build"):
        print(json.dumps(run_citations(args.labels), indent=2))
    if args.cmd in ("health", "build"):
        print(json.dumps(run_health(), indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
