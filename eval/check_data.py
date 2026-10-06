"""Check the hand-made evaluation data against the plan, so mistakes surface before they reach the results table.

    python -m eval.check_data            # report; exit 1 only on errors
    python -m eval.check_data --strict   # warnings fail too (use before recording the video or submitting)

Errors are things that make a result wrong (a graded or gold document id that is not in the corpus, a malformed file).
Warnings are departures from the plan (the 10 dev / 20 test split, all four query types, an offence date on the queries where
it decides the code, a judged query with no relevant document, ...). Nothing here changes any file.
"""

from __future__ import annotations

import argparse
import sys
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path
from typing import Mapping, Sequence

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from common.config import load_config, resolve_path  # noqa: E402
from common.io import read_jsonl  # noqa: E402
from common.schema import QUERY_TYPES, SPLITS, Query  # noqa: E402
from eval.loaders import EvalDataError, load_overruled, load_qrels, load_queries  # noqa: E402

PLAN = {"dev": 10, "test": 20}  # Guide section 5, M4 block
DATE_MATTERS = ("A", "D")  # BNS-needing-IPC and bare-number queries: the offence date decides which code applies


@dataclass
class Findings:
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    info: list[str] = field(default_factory=list)


def corpus_ids(needed: set[str], path: Path | None = None) -> set[str] | None:
    """Which of `needed` exist in judgments.jsonl (None if the corpus has not been built yet)."""
    path = path or resolve_path("judgments", load_config())
    if not path.exists():
        return None
    found: set[str] = set()
    for rec in read_jsonl(path):
        if rec.get("doc_id") in needed:
            found.add(rec["doc_id"])
            if len(found) == len(needed):
                break
    return found


def check(
    queries: Sequence[Query],
    qrels: Mapping[str, Mapping[str, int]],
    overruled: set[str],
    known_docs: set[str] | None,
    plan: Mapping[str, int] = PLAN,
) -> Findings:
    """Pure function over the loaded data. `known_docs` is the subset of referenced doc ids found in the corpus."""
    f = Findings()
    by_split = Counter(q.split for q in queries)
    by_type = Counter((q.split, q.type) for q in queries)
    f.info.append("queries per split and type: " + "; ".join(
        f"{s}: " + ", ".join(f"{t}={by_type[(s, t)]}" for t in QUERY_TYPES) + f" (total {by_split[s]})" for s in SPLITS))

    for split, wanted in plan.items():
        if by_split[split] != wanted:
            f.warnings.append(f"{by_split[split]} {split} queries; the plan is {wanted}")
    for t in QUERY_TYPES:
        if not any(by_type[(s, t)] for s in SPLITS):
            f.warnings.append(f"no query of type {t} at all")
    for q in queries:
        if q.type in DATE_MATTERS and not q.offence_date:
            f.warnings.append(f"{q.qid} (type {q.type}) has no offence_date, but the date decides IPC versus BNS for it")
    seen: dict[tuple[str, str | None], str] = {}
    for q in queries:
        key = (" ".join(q.text.lower().split()), q.offence_date)
        if key in seen:
            f.warnings.append(f"{q.qid} repeats the text and date of {seen[key]}")
        seen.setdefault(key, q.qid)

    unjudged = [q.qid for q in queries if not qrels.get(q.qid)]
    if unjudged:
        f.warnings.append(f"{len(unjudged)} queries have no judgements yet: {', '.join(unjudged[:8])}" + (" ..." if len(unjudged) > 8 else ""))
    judged = [q for q in queries if qrels.get(q.qid)]
    no_rel = [q.qid for q in judged if not any(g >= 1 for g in qrels[q.qid].values())]
    no_good = [q.qid for q in judged if not any(g == 2 for g in qrels[q.qid].values())]
    if no_rel:
        f.warnings.append(f"no relevant document (grade >= 1) for {', '.join(no_rel)}: recall and AP are undefined for them")
    if no_good:
        f.info.append(f"no grade-2 document for {', '.join(no_good)}")
    grades = Counter(g for docs in qrels.values() for g in docs.values())
    f.info.append(f"{sum(grades.values())} judgements over {len(qrels)} queries; grade counts {dict(sorted(grades.items()))}")

    if not overruled:
        f.warnings.append("gold_overrulings.csv is empty, so harmful@10 is n/a")
    else:
        for q in queries:
            if q.type == "C" and qrels.get(q.qid) and not (set(qrels[q.qid]) & overruled):
                f.warnings.append(f"{q.qid} (type C, doctrines with overruled cases) has no gold-overruled document in its "
                                  "judgements, so harmful@10 cannot show anything for it")

    referenced = {d for docs in qrels.values() for d in docs} | overruled
    if known_docs is None:
        f.warnings.append("the corpus (judgments.jsonl) is not built, so document ids were not verified against it")
    else:
        for missing in sorted(referenced - known_docs):
            f.errors.append(f"document id {missing!r} (qrels or the gold overruling list) is not in the corpus: "
                            "a typo, or a document outside the corpus subset")
    return f


def render(f: Findings) -> str:
    out = []
    for label, items in (("ERROR", f.errors), ("WARNING", f.warnings), ("info", f.info)):
        out += [f"[{label}] {item}" for item in items]
    out.append(f"\n{len(f.errors)} error(s), {len(f.warnings)} warning(s)")
    return "\n".join(out)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--strict", action="store_true", help="exit 1 on warnings as well as errors")
    args = ap.parse_args(argv)
    try:
        queries = load_queries()
        qrels = load_qrels(known_qids={q.qid for q in queries})
        overruled = load_overruled()
    except EvalDataError as exc:
        print(f"[ERROR] {exc}")
        return 1
    if not queries:
        print("[WARNING] eval/queries.jsonl is empty: the judged query set has not been written yet (eval/JUDGING_GUIDE.md).")
        return 1 if args.strict else 0
    referenced = {d for docs in qrels.values() for d in docs} | overruled
    findings = check(queries, qrels, overruled, corpus_ids(referenced) if referenced else set())
    print(render(findings))
    if findings.errors or (args.strict and findings.warnings):
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
