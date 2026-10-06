"""Loaders and validators for the hand-made evaluation files, and the small table helpers the judging tools share.

queries.jsonl, qrels.tsv and gold_overrulings.csv are written and judged by the team, never generated. The loaders refuse
inconsistent input (duplicate query ids, grades outside 0-2, judgements for queries that do not exist) so a typo cannot
silently change a result.

The table helpers live here, not in common/io.py, because the judging files are edited in spreadsheets: they must tolerate a
byte-order mark and short rows, and the accumulated qrels must be written atomically.
"""

from __future__ import annotations

import csv
import os
import re
import tempfile
from collections import defaultdict
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence

from common.config import ROOT, load_config, resolve_path
from common.io import read_jsonl
from common.schema import GRADES, QRELS_COLUMNS, Qrel, Query, SchemaError

Qrels = dict[str, dict[str, int]]  # qid -> doc_id -> grade

_ROUND_NAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*$")


class EvalDataError(ValueError):
    """An evaluation file is missing, malformed or inconsistent."""


# ------------------------------------------------------------------------------------------- table helpers
def read_table(path: str | os.PathLike, delimiter: str = ",") -> list[dict[str, str]]:
    """Read a CSV/TSV with a header row. Every value is a string.

    Spreadsheet programs save "CSV UTF-8" with a byte-order mark (read here as utf-8-sig, so it does not end up glued to the
    first column name), and a short row leaves cells missing (they become empty strings, so validation can say which row is
    wrong instead of the reader crashing). Cells beyond the header are ignored.
    """
    with open(path, "r", encoding="utf-8-sig", newline="") as fh:
        return [
            {key: (value if isinstance(value, str) else "") for key, value in raw.items() if key is not None}
            for raw in csv.DictReader(fh, delimiter=delimiter)
        ]


def write_table(
    path: str | os.PathLike, columns: Iterable[str], rows: Iterable[Mapping[str, Any]], delimiter: str = ","
) -> int:
    """Write a CSV/TSV atomically (temp file, then rename) so a crash never leaves a truncated record. Returns the row count."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    count = 0
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=path.name + ".", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="") as fh:
            writer = csv.DictWriter(fh, fieldnames=list(columns), delimiter=delimiter, lineterminator="\n")
            writer.writeheader()
            for row in rows:
                writer.writerow(row)
                count += 1
        os.replace(tmp, path)
    except BaseException:
        if os.path.exists(tmp):
            os.unlink(tmp)
        raise
    return count


def valid_round_name(name: str) -> bool:
    """A judging round is a single folder name: letters, digits, dot, dash, underscore; never a path."""
    return bool(_ROUND_NAME.match(name))


def judging_root(cfg: dict[str, Any] | None = None) -> Path:
    """The folder holding one subfolder per judging round (evaluation.judging_dir, default eval/judging)."""
    cfg = cfg or load_config()
    p = Path(cfg["evaluation"].get("judging_dir", "eval/judging"))
    return p if p.is_absolute() else ROOT / p


# ------------------------------------------------------------------------------------------------ loaders
def load_queries(path: str | os.PathLike | None = None) -> list[Query]:
    path = Path(path) if path else resolve_path("queries", load_config())
    if not path.exists():
        return []
    queries: list[Query] = []
    seen: set[str] = set()
    try:
        for rec in read_jsonl(path):
            q = Query.from_dict(rec)
            if q.qid in seen:
                raise EvalDataError(f"{path}: duplicate qid {q.qid!r}")
            seen.add(q.qid)
            queries.append(q)
    except SchemaError as exc:
        raise EvalDataError(f"{path}: {exc}") from exc
    return queries


def load_qrels(path: str | os.PathLike | None = None, known_qids: set[str] | None = None) -> Qrels:
    """qid -> {doc_id: grade}. A header row (`qid doc_id grade`) is expected; conflicting duplicate judgements are an error."""
    path = Path(path) if path else resolve_path("qrels", load_config())
    if not path.exists():
        return {}
    rows = read_table(path, delimiter="\t")
    if rows and set(rows[0]) != set(QRELS_COLUMNS):
        raise EvalDataError(f"{path}: header must be {list(QRELS_COLUMNS)}, got {list(rows[0])}")
    qrels: Qrels = defaultdict(dict)
    for lineno, row in enumerate(rows, start=2):
        try:
            qrel = Qrel.from_dict({"qid": row["qid"].strip(), "doc_id": row["doc_id"].strip(), "grade": int(row["grade"])})
        except (SchemaError, ValueError) as exc:
            raise EvalDataError(f"{path}:{lineno}: {exc}") from exc
        if known_qids is not None and qrel.qid not in known_qids:
            raise EvalDataError(f"{path}:{lineno}: judgement for unknown qid {qrel.qid!r}")
        previous = qrels[qrel.qid].get(qrel.doc_id)
        if previous is not None and previous != qrel.grade:
            raise EvalDataError(f"{path}:{lineno}: conflicting grades for ({qrel.qid}, {qrel.doc_id}): {previous} vs {qrel.grade}")
        qrels[qrel.qid][qrel.doc_id] = qrel.grade
    return dict(qrels)


def load_overruled(path: str | os.PathLike | None = None) -> set[str]:
    """doc ids of the hand-verified overruled cases (gold_overrulings.csv), used only for harmful@k."""
    path = Path(path) if path else resolve_path("gold_overrulings", load_config())
    if not path.exists():
        return set()
    ids = set()
    for lineno, row in enumerate(read_table(path), start=2):
        doc_id = row.get("overruled_doc_id", "").strip()
        if not doc_id:
            raise EvalDataError(f"{path}:{lineno}: overruled_doc_id is empty (or the column is missing)")
        ids.add(doc_id)
    return ids


def judged_without(qrels: Mapping[str, Mapping[str, int]], qids: Sequence[str], min_grade: int) -> list[str]:
    """Judged queries (in `qids`) that have no document graded `min_grade` or higher."""
    return [q for q in qids if q in qrels and not any(g >= min_grade for g in qrels[q].values())]


def graded(grades: Mapping[str, int], doc_id: str) -> int:
    """A document with no judgement counts as grade 0 (the pooling assumption)."""
    return grades.get(doc_id, 0)


__all__ = [
    "EvalDataError", "GRADES", "Qrels", "graded", "judged_without", "judging_root", "load_overruled", "load_qrels",
    "load_queries", "read_table", "valid_round_name", "write_table",
]
