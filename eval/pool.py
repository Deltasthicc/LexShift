"""Pooling: turn the systems' rankings into the sheets the two judges grade, so the qrels are built the standard IR way.

    python -m eval.pool --split all --round round1         # pool the top-20 of b0, b1 and full for every query
    python -m eval.pool --split dev --round round2         # later: only documents not judged yet are added

Pooling in IR terms: nobody can judge a whole corpus, so each system contributes its top-`depth` documents and the union (the
pool) is judged. Documents outside the pool count as non-relevant, which is why this tool pools every system, why evaluation
runs at the pool depth, and why `judged@10` is reported.

What it writes to eval/judging/<round>/ (never overwriting an existing round):
  sheet_template.csv  the BLIND sheet the judges fill in: shuffled per query, no scores, no ranks, no system names, no
                      continuity/health values (those would make the labels circular);
  provenance.csv      which system returned each document at which rank, kept apart from the judges;
  summary.md          pool sizes and the overlap between systems, plus the judging effort.

Pooling is incremental: documents already graded in eval/qrels.tsv are left out of a new template, so after the real modules
improve or the weights change, a new round adds only what is new and the earlier grades stay. Pooled lists come from real
providers only: with a stub provider the tool refuses (a stub round is named stub_* and git-ignored).
"""

from __future__ import annotations

import argparse
import datetime as dt
import random
import re
import sys
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from common.config import load_config, resolve_path  # noqa: E402
from common.io import read_jsonl  # noqa: E402
from common.providers import Providers, load_providers  # noqa: E402
from common.schema import Query  # noqa: E402
from eval.loaders import (  # noqa: E402
    EvalDataError, judging_root, load_qrels, load_queries, valid_round_name, write_table,
)
from m4_rank.explain import strip_controls  # noqa: E402
from m4_rank.rank import (  # noqa: E402
    ArtefactError, Collected, ContractViolation, collect, fuse_collected, load_checked, stubbed_groups,
)
from m4_rank.weights import canonical_config, format_weights, load_weights, signals_used  # noqa: E402

SHEET_COLUMNS = ("qid", "query", "type", "offence_date", "doc_id", "title", "date", "bench_size", "excerpt", "grade", "note")
DEFAULT_CONFIGS = "b0,b1,full"
EXCERPT_CHARS = 500

Pool = dict[str, dict[str, dict[str, int]]]  # qid -> doc_id -> {config: 1-based rank}


# ----------------------------------------------------------------------------------------------- pure logic
def build_pool(
    queries: Sequence[Query],
    collected: Mapping[str, Collected],
    weights_by_config: Mapping[str, Mapping[str, float]],
    depth: int,
    cfg: dict[str, Any],
) -> Pool:
    """The union of every config's top-`depth` for each query, remembering each document's rank per config."""
    pool: Pool = {}
    for q in queries:
        per_doc: dict[str, dict[str, int]] = {}
        for name, weights in weights_by_config.items():
            for rank, result in enumerate(fuse_collected(collected[q.qid], weights, depth, cfg), start=1):
                per_doc.setdefault(result.doc_id, {})[name] = rank
        pool[q.qid] = per_doc
    return pool


def drop_judged(pool: Pool, qrels: Mapping[str, Mapping[str, int]]) -> Pool:
    """The part of the pool that still needs grades (documents already in qrels are not asked about again)."""
    return {qid: {d: r for d, r in docs.items() if d not in qrels.get(qid, {})} for qid, docs in pool.items()}


def blind_order(qid: str, doc_ids: Iterable[str], seed: int) -> list[str]:
    """A deterministic shuffle per query, so a document's position tells the judge nothing about any system's rank."""
    ordered = sorted(doc_ids)
    random.Random(f"{seed}:{qid}").shuffle(ordered)
    return ordered


def overlap_stats(docs: Mapping[str, Mapping[str, int]], configs: Sequence[str]) -> dict[str, int]:
    """Pool size and how many documents every system agreed on."""
    return {
        "union": len(docs),
        "in_all": sum(1 for ranks in docs.values() if all(c in ranks for c in configs)),
        "in_one": sum(1 for ranks in docs.values() if len(ranks) == 1),
    }


def _tidy(text: str, limit: int) -> str:
    text = re.sub(r"\s+", " ", strip_controls(text or "")).strip()
    return text if len(text) <= limit else text[: limit - 3].rstrip() + "..."


def safe_cell(text: Any) -> str:
    """Neutralise spreadsheet formulas: a cell starting with = + - @ (or a tab/CR) is prefixed with a single quote.

    The judges open these sheets in a spreadsheet program. Court text (OCR separators such as '---' or '= = =') routinely starts
    with those characters and would otherwise be evaluated or mangled, and re-saved that way.
    """
    s = "" if text is None else str(text)
    s = strip_controls(s)
    return "'" + s if s[:1] in ("=", "+", "-", "@", "\t", "\r") else s


def load_doc_context(doc_ids: set[str], path: Path | None = None) -> dict[str, dict[str, Any]]:
    """Title, date, bench and a short excerpt for the pooled documents only (one streaming pass over judgments.jsonl)."""
    path = path or resolve_path("judgments", load_config())
    if not path.exists() or not doc_ids:
        return {}
    found: dict[str, dict[str, Any]] = {}
    for rec in read_jsonl(path):
        doc_id = rec.get("doc_id")
        if doc_id not in doc_ids:
            continue
        zones = rec.get("zones") or {}
        body = zones.get("holding") or rec.get("text") or ""
        found[doc_id] = {
            "title": rec.get("title") or "",
            "date": rec.get("date") or "",
            "bench_size": rec.get("bench_size") if rec.get("bench_size") is not None else "",
            "excerpt": _tidy(body, EXCERPT_CHARS),
        }
        if len(found) == len(doc_ids):
            break
    return found


def sheet_rows(queries: Sequence[Query], pool_new: Pool, context: Mapping[str, Mapping[str, Any]], seed: int) -> list[dict[str, Any]]:
    rows = []
    for q in queries:
        for doc_id in blind_order(q.qid, pool_new.get(q.qid, {}), seed):
            ctx = context.get(doc_id, {})
            rows.append({
                "qid": q.qid, "query": safe_cell(q.text), "type": q.type, "offence_date": q.offence_date or "",
                "doc_id": doc_id, "title": safe_cell(ctx.get("title", "")), "date": ctx.get("date", ""),
                "bench_size": ctx.get("bench_size", ""), "excerpt": safe_cell(ctx.get("excerpt", "")), "grade": "", "note": "",
            })
    return rows


def provenance_rows(pool: Pool, qrels: Mapping[str, Mapping[str, int]], configs: Sequence[str]) -> list[dict[str, Any]]:
    rows = []
    for qid in sorted(pool):
        for doc_id in sorted(pool[qid]):
            ranks = pool[qid][doc_id]
            rows.append({
                "qid": qid, "doc_id": doc_id,
                **{f"rank_{c}": ranks.get(c, "") for c in configs},
                "n_systems": len(ranks), "already_judged": doc_id in qrels.get(qid, {}),
            })
    return rows


def render_summary(
    round_name: str, queries: Sequence[Query], pool: Pool, pool_new: Pool, configs: Sequence[str],
    weights: Mapping[str, Mapping[str, float]], depth: int, seed: int, providers: Providers, has_context: bool,
) -> str:
    lines = [
        f"# Pool summary: {round_name}", "",
        f"Generated {dt.datetime.now(dt.timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}. Providers: {providers.describe()}.",
        f"Systems pooled: {', '.join(configs)}; depth {depth}; shuffle seed {seed}.",
        "Weights: " + "; ".join(f"{n} = {format_weights(w)} (rel/cont/health/auth)" for n, w in weights.items()) + ".",
        "",
    ]
    if providers.stubbed:
        lines += ["> **STUB ROUND: these documents come from fixed-value stand-ins and must not be judged or used.**", ""]
    if not has_context:
        lines += ["> No judgments.jsonl was found, so the sheet has no titles or excerpts: judges must open the documents "
                  "themselves. Run the pipeline (`make build-index`) first if you can.", ""]
    lines += ["| qid | split | type | pooled | in every system | in one system only | already judged | to judge now |",
              "|---|---|---|---|---|---|---|---|"]
    tot_pool = tot_new = 0
    for q in queries:
        st = overlap_stats(pool.get(q.qid, {}), configs)
        new = len(pool_new.get(q.qid, {}))
        tot_pool += st["union"]
        tot_new += new
        lines.append(f"| {q.qid} | {q.split} | {q.type} | {st['union']} | {st['in_all']} | {st['in_one']} | {st['union'] - new} | {new} |")
    lines += ["", f"**{tot_new} documents to judge now** ({tot_pool} pooled over {len(queries)} queries), so about "
                  f"{2 * tot_new} individual judgements for two judges.", "",
              "How to read the overlap: if almost every document is in every system, the systems retrieve the same documents and "
              "differ only in ORDER (nDCG will show it, P@k will not). A large 'in one system only' column means the systems "
              "disagree about WHAT to retrieve, and the pool is doing real work.", "",
              "Judging rules: [eval/JUDGING_GUIDE.md](../../JUDGING_GUIDE.md). Judges grade independently, from the sheet only."]
    return "\n".join(lines) + "\n"


# ------------------------------------------------------------------------------------------------- command
def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--split", choices=("dev", "test", "all"), default="all")
    ap.add_argument("--round", default="round1", help="name of this judging round (a directory under eval/judging/)")
    ap.add_argument("--depth", type=int, help="documents taken from each system (default: evaluation.depth, 20)")
    ap.add_argument("--configs", default=DEFAULT_CONFIGS, help=f"systems to pool (default {DEFAULT_CONFIGS})")
    ap.add_argument("--seed", type=int, default=0, help="seed of the per-query shuffle (default 0)")
    ap.add_argument("--include-judged", action="store_true", help="also list documents that already have a grade")
    ap.add_argument("--force", action="store_true", help="regenerate an existing round's template, provenance and summary; refused once judging has started")
    ap.add_argument("--allow-stubs", action="store_true", help="pool from stub providers; the round is named stub_* and is not usable")
    ap.add_argument("--out", help="judging directory (default: paths.judging_dir)")
    return ap.parse_args(argv)


JUDGING_FILES = ("judge1.csv", "judge2.csv", "disagreements.csv")  # a round with any of these has judging under way


def main(argv: list[str] | None = None) -> int:
    try:
        return _main(argv)
    except ArtefactError as exc:
        print(f"A module could not find its data: {exc}")
        return 2
    except ContractViolation as exc:
        print(f"A module returned data that breaks its contract: {exc}")
        return 3


def _main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    cfg = load_config()
    if not valid_round_name(args.round):
        print(f"--round must be a plain folder name (letters, digits, '.', '-', '_'), got {args.round!r}.")
        return 2
    try:
        configs = [canonical_config(n, cfg) for n in args.configs.split(",") if n.strip()]
        all_queries = load_queries()
        if not all_queries:
            print("No queries in eval/queries.jsonl: write them first (eval/JUDGING_GUIDE.md), then pool.")
            return 2
        qrels = load_qrels(known_qids={q.qid for q in all_queries})
    except EvalDataError as exc:
        print(f"Evaluation data problem: {exc}")
        return 2

    queries = [q for q in all_queries if args.split == "all" or q.split == args.split]
    if not queries:
        print(f"No {args.split} queries.")
        return 2
    depth = args.depth or int(cfg["evaluation"]["depth"])
    if not 1 <= depth <= int(cfg["ranking"]["candidates"]):
        print(f"--depth must be between 1 and ranking.candidates ({cfg['ranking']['candidates']}).")
        return 2

    weights = {n: load_weights(n, cfg) for n in configs}
    signals = signals_used(weights, configs)
    providers = load_checked(load_providers, cfg)
    stubbed = stubbed_groups(providers, signals)
    if stubbed and not args.allow_stubs:
        print("Refusing to pool: these providers are fixed-value stubs, so the documents would be placeholders: "
              + ", ".join(stubbed) + ".\nSwitch the real functions on in common/config.yaml first (or LEXSHIFT_STUBS=none).")
        return 2

    base = Path(args.out) if args.out else judging_root(cfg)
    round_dir = base / (f"stub_{args.round}" if stubbed else args.round)
    if round_dir.exists() and any(round_dir.iterdir()):
        started = [name for name in JUDGING_FILES if (round_dir / name).exists()]
        if started:
            print(f"{round_dir} already has {', '.join(started)}: judging has started, and regenerating the template would "
                  f"orphan those grades. Use a new --round name; documents already graded are skipped automatically.")
            return 2
        if not args.force:
            print(f"{round_dir} already exists. Pick a new --round name, or --force to regenerate its template, provenance "
                  "and summary.")
            return 2

    collected = {q.qid: collect(q.text, q.offence_date, signals, providers=providers, cfg=cfg) for q in queries}
    pool = build_pool(queries, collected, weights, depth, cfg)
    pool_new = pool if args.include_judged else drop_judged(pool, qrels)
    for q in queries:
        if not pool[q.qid]:
            print(f"warning: {q.qid} returned no documents")

    needed = {d for docs in pool_new.values() for d in docs}
    context = load_doc_context(needed)
    rows = sheet_rows(queries, pool_new, context, args.seed)
    if not rows:
        print("Nothing to judge: every pooled document already has a grade in eval/qrels.tsv.")
        return 0

    round_dir.mkdir(parents=True, exist_ok=True)
    write_table(round_dir / "sheet_template.csv", SHEET_COLUMNS, rows)
    prov = provenance_rows(pool, qrels, configs)
    write_table(round_dir / "provenance.csv", list(prov[0]) if prov else ["qid", "doc_id"], prov)
    summary = render_summary(args.round, queries, pool, pool_new, configs, weights, depth, args.seed, providers, bool(context))
    (round_dir / "summary.md").write_text(summary, encoding="utf-8", newline="\n")

    print(summary)
    print(f"Wrote {round_dir}. Next: each judge copies sheet_template.csv to judge1.csv / judge2.csv and fills the `grade` "
          f"column (0, 1 or 2) independently; then run  python -m eval.make_qrels --round {args.round}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
