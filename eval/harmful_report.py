"""Does the ranking push known-overruled judgments down? A check that needs no relevance grades, only the hand-verified gold overruling list.

    python -m eval.harmful_report                 # all 30 queries, B0 / B1 / Full, writes eval/results/harmful_at_10.md and .csv

For every query and every system it takes the top 10 and counts the judgments on the gold list (`eval/gold_overrulings.csv`, written and verified by people, never taken
from our own `doc_health.jsonl`). It reports harmful@10 per system, and, for each gold judgment that reaches the top 10 of any system for any query, its rank under B0, B1
and Full, so "Sowmithri Vishnu is 1st with BM25 alone and 9th with all four signals" can be read straight off the table. Lower is better. Refuses when the gold list is
empty or any provider is a stand-in; the output is named for what it is and is never a relevance result.
"""

from __future__ import annotations

import argparse
import csv
import sys
from pathlib import Path
from typing import Mapping, Sequence

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from common.config import load_config, resolve_path  # noqa: E402
from common.providers import load_providers  # noqa: E402
from eval.loaders import load_overruled, load_queries  # noqa: E402
from m4_rank.rank import collect, fuse_collected, load_checked, stubbed_groups  # noqa: E402
from m4_rank.weights import load_weights, signals_used  # noqa: E402

CONFIGS = ("b0", "b1", "full")
TOP = 10


def harmful_share(ranked: Sequence[str], overruled: set[str], k: int = TOP) -> float:
    return sum(1 for d in ranked[:k] if d in overruled) / k


def rank_rows(runs: Mapping[str, Mapping[str, Sequence[str]]], overruled: set[str], k: int = TOP) -> list[dict[str, object]]:
    """runs[qid][config] = ranked doc ids. One row per (query, gold judgment) that is in the top k of at least one system: its 1-based rank under each system, or '' if not in the top k."""
    rows: list[dict[str, object]] = []
    for qid, by_config in runs.items():
        seen = {d for ranked in by_config.values() for d in ranked[:k] if d in overruled}
        for doc in sorted(seen):
            row: dict[str, object] = {"qid": qid, "doc_id": doc}
            for config in CONFIGS:
                ranked = list(by_config.get(config, ()))
                row[config] = ranked.index(doc) + 1 if doc in ranked[:k] else ""
            rows.append(row)
    return rows


def render(runs: Mapping[str, Mapping[str, Sequence[str]]], overruled: set[str], titles: Mapping[str, str], splits: Mapping[str, str]) -> str:
    lines = ["# harmful@10 without grades: known-overruled judgments in the top 10", "",
             f"Gold list: {len(overruled)} overruled judgments (`eval/gold_overrulings.csv`, written and verified by people). {len(runs)} queries. Lower is better.", "",
             "| system | harmful@10 (all queries) | dev | test |", "|---|---|---|---|"]
    for config in CONFIGS:
        def mean(sel):
            vals = [harmful_share(by[config], overruled) for q, by in runs.items() if config in by and sel(q)]
            return f"{sum(vals) / len(vals):.3f}" if vals else "n/a"
        lines.append(f"| {config.upper()} | {mean(lambda q: True)} | {mean(lambda q: splits.get(q) == 'dev')} | {mean(lambda q: splits.get(q) == 'test')} |")
    rows = rank_rows(runs, overruled)
    lines += ["", "Rank of each gold judgment that reaches the top 10 of at least one system (blank: not in that system's top 10)", "",
              "| query | judgment | B0 | B1 | Full |", "|---|---|---|---|---|"]
    for r in rows:
        lines.append(f"| {r['qid']} | {titles.get(str(r['doc_id']), r['doc_id'])} ({r['doc_id']}) | {r['b0']} | {r['b1']} | {r['full']} |")
    if not rows:
        lines.append("| none | no gold judgment reaches any top 10 | | | |")
    lines += ["", "harmful@10 counts a gold judgment in the top 10 of any query, as in `eval.metrics`; it does not check that the query is about the point on which the judgment was overruled."]
    return "\n".join(lines) + "\n"


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="python -m eval.harmful_report", description=__doc__.split("\n\n")[0])
    ap.add_argument("--gold", help="gold overruling list to use (default: paths.gold_overrulings); pass the draft to preview it before adopting it")
    ap.add_argument("--out", help="output directory (default: paths.results_dir)")
    args = ap.parse_args(argv)
    cfg = load_config()
    overruled = load_overruled(args.gold)
    if not overruled:
        print("eval/gold_overrulings.csv is empty: adopt the verified rows of eval/gold_overrulings.draft.csv first (each row read in the judgments, `verified_by` filled).")
        return 2
    queries = load_queries()
    weights = {n: load_weights(n, cfg) for n in CONFIGS}
    signals = signals_used(weights, CONFIGS)
    providers = load_checked(load_providers, cfg)
    stubbed = stubbed_groups(providers, signals)
    if stubbed:
        print("Refusing: these providers are stand-ins: " + ", ".join(stubbed))
        return 2
    runs: dict[str, dict[str, list[str]]] = {}
    for q in queries:
        collected = collect(q.text, q.offence_date, signals, providers=providers, cfg=cfg)
        runs[q.qid] = {c: [r.doc_id for r in fuse_collected(collected, weights[c], TOP, cfg)] for c in CONFIGS}
    titles = {}
    meta = resolve_path("doc_meta", cfg)
    if meta.exists():
        from common.io import read_jsonl

        titles = {r["doc_id"]: r.get("title", "") for r in read_jsonl(meta) if r["doc_id"] in overruled}
    text = render(runs, overruled, titles, {q.qid: q.split for q in queries})
    out = Path(args.out) if args.out else resolve_path("results_dir", cfg)
    out.mkdir(parents=True, exist_ok=True)
    (out / "harmful_at_10.md").write_text(text, encoding="utf-8", newline="\n")
    with (out / "harmful_at_10.csv").open("w", encoding="utf-8", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=["qid", "doc_id", *CONFIGS], lineterminator="\n")
        w.writeheader()
        w.writerows(rank_rows(runs, overruled))
    print(text)
    print(f"Wrote {out / 'harmful_at_10.md'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
