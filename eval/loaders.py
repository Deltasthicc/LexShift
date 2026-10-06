"""Loaders and validators for the hand-made evaluation files: queries.jsonl, qrels.tsv, gold_overrulings.csv.

These files are written and judged by the team, never generated. The loaders refuse inconsistent input (duplicate query
ids, grades outside 0-2, judgements for queries that do not exist) so a typo cannot silently change a result.
"""

from __future__ import annotations

import os
from collections import defaultdict
from pathlib import Path

from common.config import load_config, resolve_path
from common.io import read_delimited, read_jsonl
from common.schema import GRADES, QRELS_COLUMNS, Qrel, Query, SchemaError

Qrels = dict[str, dict[str, int]]  # qid -> doc_id -> grade


class EvalDataError(ValueError):
    """An evaluation file is missing, malformed or inconsistent."""


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
    rows = read_delimited(path, delimiter="\t")
    if rows and set(rows[0]) != set(QRELS_COLUMNS):
        raise EvalDataError(f"{path}: header must be {list(QRELS_COLUMNS)}, got {list(rows[0])}")
    qrels: Qrels = defaultdict(dict)
    for lineno, row in enumerate(rows, start=2):
        try:
            qrel = Qrel.from_dict({"qid": row["qid"], "doc_id": row["doc_id"], "grade": int(row["grade"])})
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
    rows = read_delimited(path)
    ids = set()
    for lineno, row in enumerate(rows, start=2):
        doc_id = (row.get("overruled_doc_id") or "").strip()
        if not doc_id:
            raise EvalDataError(f"{path}:{lineno}: overruled_doc_id is empty")
        ids.add(doc_id)
    return ids


def graded(grades: dict[str, int], doc_id: str) -> int:
    """A document with no judgement counts as grade 0 (the pooling assumption)."""
    return grades.get(doc_id, 0)


__all__ = ["EvalDataError", "GRADES", "Qrels", "graded", "load_overruled", "load_qrels", "load_queries"]
