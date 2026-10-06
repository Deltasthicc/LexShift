"""Build eval/qrels.tsv from the two judges' graded sheets, with agreement statistics.

    python -m eval.make_qrels --round round1

Inputs, in eval/judging/<round>/ :
  sheet_template.csv   written by `python -m eval.pool` (the rows that had to be graded)
  judge1.csv, judge2.csv   copies of the template with the `grade` column filled in (0, 1 or 2) by two judges, independently
  disagreements.csv    written by this tool: the rows where the judges differ, with an `adjudicated` column for the team to
                       fill in after discussing them (the discussion is the point: disagreements are resolved by reading again)

Rules the tool enforces: each judge file contains exactly the template's rows (none missing, added or duplicated), every grade
is 0, 1 or 2, and every disagreement has an adjudicated grade. Otherwise qrels.tsv is NOT written (--allow-incomplete writes
only the settled rows). Grades already in qrels.tsv are never changed.

Outputs: eval/qrels.tsv (merged with earlier rounds), <round>/disagreements.csv, <round>/agreement.md (percent agreement and
Cohen's kappa for the report).
"""

from __future__ import annotations

import argparse
import datetime as dt
import sys
from collections import defaultdict
from pathlib import Path
from typing import Mapping

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from common.config import load_config, resolve_path  # noqa: E402
from common.io import read_delimited, write_delimited  # noqa: E402
from common.schema import GRADES, QRELS_COLUMNS  # noqa: E402
from eval.agreement import LABELS, agreement_report  # noqa: E402
from eval.loaders import EvalDataError, load_qrels, load_queries  # noqa: E402

Pair = tuple[str, str]  # (qid, doc_id)
DISAGREEMENT_COLUMNS = ("qid", "query", "doc_id", "title", "grade_judge1", "grade_judge2", "adjudicated", "note")


class QrelsBuildError(ValueError):
    """The judging files are inconsistent with the template or with the existing qrels."""


def read_template(path: Path) -> list[dict[str, str]]:
    if not path.exists():
        raise QrelsBuildError(f"{path} not found: run `python -m eval.pool --round <name>` first")
    rows = read_delimited(path)
    seen: set[Pair] = set()
    for row in rows:
        pair = (row["qid"], row["doc_id"])
        if pair in seen:
            raise QrelsBuildError(f"{path}: duplicate row {pair}")
        seen.add(pair)
    return rows


def _parse_grade(raw: str | None) -> int | None:
    text = (raw or "").strip()
    if not text:
        return None
    try:
        value = int(float(text))  # a spreadsheet may turn 2 into 2.0
    except ValueError:
        raise ValueError(f"grade {text!r} is not a number") from None
    if float(text) != value or value not in GRADES:
        raise ValueError(f"grade {text!r} is not one of {GRADES}")
    return value


def read_judge_file(path: Path, expected: set[Pair]) -> tuple[dict[Pair, int], list[str]]:
    """The grades in one judge's file and a list of problems (wrong rows, bad or missing grades)."""
    rows = read_delimited(path)
    problems: list[str] = []
    if rows and not {"qid", "doc_id", "grade"} <= set(rows[0]):
        return {}, [f"{path.name}: needs the columns qid, doc_id and grade"]
    grades: dict[Pair, int] = {}
    seen: set[Pair] = set()
    invalid: set[Pair] = set()  # rows that already have their own error message
    blank: list[Pair] = []
    for lineno, row in enumerate(rows, start=2):
        pair = (row["qid"].strip(), row["doc_id"].strip())
        if pair in seen:
            problems.append(f"{path.name}:{lineno}: duplicate row {pair}")
            continue
        seen.add(pair)
        if pair not in expected:
            problems.append(f"{path.name}:{lineno}: row {pair} is not in the template (rows may not be added or renamed)")
            continue
        try:
            grade = _parse_grade(row.get("grade"))
        except ValueError as exc:
            problems.append(f"{path.name}:{lineno}: {pair}: {exc}")
            invalid.add(pair)
            continue
        if grade is None:
            blank.append(pair)
        else:
            grades[pair] = grade
    for pair in sorted(expected - seen):
        problems.append(f"{path.name}: template row {pair} is missing")
    if blank:
        problems.append(f"{path.name}: {len(blank)} row(s) have no grade yet, for example {blank[0]}")
    return grades, problems


def load_adjudications(path: Path) -> dict[Pair, tuple[int, str]]:
    """Adjudicated grades (and notes) already typed into disagreements.csv; blank cells mean 'not decided yet'."""
    if not path.exists():
        return {}
    out: dict[Pair, tuple[int, str]] = {}
    for lineno, row in enumerate(read_delimited(path), start=2):
        try:
            grade = _parse_grade(row.get("adjudicated"))
        except ValueError as exc:
            raise QrelsBuildError(f"{path.name}:{lineno}: {exc}") from exc
        if grade is not None:
            out[(row["qid"], row["doc_id"])] = (grade, row.get("note", ""))
    return out


def reconcile(
    g1: Mapping[Pair, int], g2: Mapping[Pair, int], adjudicated: Mapping[Pair, tuple[int, str]]
) -> tuple[dict[Pair, int], list[Pair], list[Pair]]:
    """(final grades, all disagreements, disagreements still lacking an adjudicated grade)."""
    final: dict[Pair, int] = {}
    disagreements: list[Pair] = []
    unresolved: list[Pair] = []
    for pair in sorted(set(g1) & set(g2)):
        if g1[pair] == g2[pair]:
            final[pair] = g1[pair]
            continue
        disagreements.append(pair)
        if pair in adjudicated:
            final[pair] = adjudicated[pair][0]
        else:
            unresolved.append(pair)
    return final, disagreements, unresolved


def merge_qrels(existing: Mapping[str, Mapping[str, int]], new: Mapping[Pair, int]) -> dict[str, dict[str, int]]:
    """Existing qrels plus the new grades. Changing a grade that is already recorded is refused."""
    merged: dict[str, dict[str, int]] = {qid: dict(docs) for qid, docs in existing.items()}
    for (qid, doc_id), grade in new.items():
        previous = merged.get(qid, {}).get(doc_id)
        if previous is not None and previous != grade:
            raise QrelsBuildError(
                f"({qid}, {doc_id}) is already graded {previous} in qrels.tsv and this round says {grade}. Grades are not "
                "overwritten by the tool: edit qrels.tsv by hand and record the reason in DECISIONS.md.")
        merged.setdefault(qid, {})[doc_id] = grade
    return merged


def qrels_rows(qrels: Mapping[str, Mapping[str, int]]) -> list[dict[str, object]]:
    return [{"qid": qid, "doc_id": doc, "grade": qrels[qid][doc]} for qid in sorted(qrels) for doc in sorted(qrels[qid])]


def per_query_summary(qrels: Mapping[str, Mapping[str, int]], qids: list[str]) -> tuple[list[str], list[str]]:
    """Judged queries with no relevant document (recall and AP undefined) and with no grade-2 document."""
    no_relevant = [q for q in qids if q in qrels and not any(g >= 1 for g in qrels[q].values())]
    no_good = [q for q in qids if q in qrels and not any(g == 2 for g in qrels[q].values())]
    return no_relevant, no_good


def _pct(x: float | None) -> str:
    return "n/a" if x is None else f"{100 * x:.1f}%"


def _num(x: float | None) -> str:
    return "n/a" if x is None else f"{x:.3f}"


def render_agreement(round_name: str, report: Mapping, n_disagree: int, n_adjudicated: int) -> str:
    c = report["confusion"]
    lines = [
        f"# Judge agreement: {round_name}", "",
        f"Generated {dt.datetime.now(dt.timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}.", "",
        f"* Documents graded by both judges: **{report['n']}**",
        f"* Exact agreement: **{_pct(report['agreement'])}**",
        f"* Cohen's kappa: **{_num(report['kappa'])}**; quadratic-weighted kappa: **{_num(report['kappa_quadratic'])}** "
        "(grades are ordinal, so the weighted value is the more informative one)",
        f"* Disagreements: {n_disagree}, of which adjudicated: {n_adjudicated}", "",
        "Confusion matrix (rows: judge 1, columns: judge 2)", "",
        "| judge 1 \\ judge 2 | " + " | ".join(str(g) for g in LABELS) + " |", "|---|" + "---|" * len(LABELS),
    ]
    lines += [f"| {g} | " + " | ".join(str(v) for v in c[i]) + " |" for i, g in enumerate(LABELS)]
    gc = report["grade_counts"]
    lines += ["", f"Grade counts, judge 1: {gc['judge1']}; judge 2: {gc['judge2']}.", "",
              "Kappa depends on how the grades are distributed; report it together with the counts above and with how the "
              "disagreements were resolved, not as a verdict on quality."]
    return "\n".join(lines) + "\n"


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--round", default="round1")
    ap.add_argument("--allow-incomplete", action="store_true", help="write only the settled rows even if some are missing or unresolved")
    ap.add_argument("--out", help="judging directory (default: paths.judging_dir)")
    return ap.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    cfg = load_config()
    if args.round.startswith("stub_"):
        print("A stub round is not a judging round and cannot produce qrels.")
        return 2
    round_dir = (Path(args.out) if args.out else resolve_path("judging_dir", cfg)) / args.round
    try:
        queries = load_queries()
        known = {q.qid for q in queries}
        template = read_template(round_dir / "sheet_template.csv")
        expected = {(r["qid"], r["doc_id"]) for r in template}
        unknown = sorted({qid for qid, _ in expected} - known)
        if unknown:
            raise QrelsBuildError(f"the template mentions queries that are not in queries.jsonl: {unknown[:5]}")
        files = {name: round_dir / f"{name}.csv" for name in ("judge1", "judge2")}
        missing = [str(p.name) for p in files.values() if not p.exists()]
        if missing:
            raise QrelsBuildError(f"missing {', '.join(missing)} in {round_dir}: each judge copies sheet_template.csv and fills `grade`")
        g1, p1 = read_judge_file(files["judge1"], expected)
        g2, p2 = read_judge_file(files["judge2"], expected)
        existing = load_qrels(known_qids=known)
    except (QrelsBuildError, EvalDataError) as exc:
        print(f"Cannot build qrels: {exc}")
        return 2

    problems = p1 + p2
    both = sorted(set(g1) & set(g2))
    report = agreement_report([g1[p] for p in both], [g2[p] for p in both])
    dis_path = round_dir / "disagreements.csv"
    try:
        adjudicated = load_adjudications(dis_path)
    except QrelsBuildError as exc:
        print(f"Cannot build qrels: {exc}")
        return 2
    final, disagreements, unresolved = reconcile(g1, g2, adjudicated)

    ctx = {(r["qid"], r["doc_id"]): r for r in template}
    qtext = {q.qid: q.text for q in queries}
    write_delimited(dis_path, DISAGREEMENT_COLUMNS, [
        {"qid": qid, "query": qtext.get(qid, ""), "doc_id": doc, "title": ctx[(qid, doc)].get("title", ""),
         "grade_judge1": g1[(qid, doc)], "grade_judge2": g2[(qid, doc)],
         "adjudicated": adjudicated[(qid, doc)][0] if (qid, doc) in adjudicated else "",
         "note": adjudicated[(qid, doc)][1] if (qid, doc) in adjudicated else ""}
        for qid, doc in disagreements
    ])
    (round_dir / "agreement.md").write_text(
        render_agreement(args.round, report, len(disagreements), len(disagreements) - len(unresolved)),
        encoding="utf-8", newline="\n")

    print(f"{report['n']} documents graded by both judges; agreement {_pct(report['agreement'])}; "
          f"kappa {_num(report['kappa'])} (quadratic-weighted {_num(report['kappa_quadratic'])}).")
    if disagreements:
        print(f"{len(disagreements)} disagreement(s) written to {dis_path}; {len(unresolved)} still need an `adjudicated` grade.")
    incomplete = bool(problems or unresolved)
    if incomplete:
        for line in problems[:12]:
            print(f"  problem: {line}")
        if len(problems) > 12:
            print(f"  ... and {len(problems) - 12} more problem(s)")
        if not args.allow_incomplete:
            print("qrels.tsv was NOT written. Fix the points above and re-run (or --allow-incomplete to write only settled rows).")
            return 2
        print("--allow-incomplete: writing only the settled rows.")

    try:
        merged = merge_qrels(existing, final)
    except QrelsBuildError as exc:
        print(f"Cannot build qrels: {exc}")
        return 2
    qrels_path = resolve_path("qrels", cfg)
    write_delimited(qrels_path, QRELS_COLUMNS, qrels_rows(merged), delimiter="\t")
    print(f"Wrote {sum(len(d) for d in merged.values())} judgements for {len(merged)} queries to {qrels_path}.")
    no_rel, no_good = per_query_summary(merged, sorted(merged))
    if no_rel:
        print(f"warning: no relevant document (grade >= 1) for {', '.join(no_rel)}: recall and AP are undefined for them.")
    if no_good:
        print(f"note: no grade-2 (relevant and good law) document for {', '.join(no_good)}.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
