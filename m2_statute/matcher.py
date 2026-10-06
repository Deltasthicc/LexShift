"""continuity(): how much of a judgment's statutory basis carries over to the code that applies to the query.

Best match between the query's offence ids and the judgment's offence ids (data/processed/doc_statutes.jsonl),
scored with the relation weight from statute_map.csv, plus a human-readable explanation such as
"BNS 103 -> IPC 302 (equivalent)". Design rule: old IPC judgments are not dead; penalise only in proportion to how
much the law changed.
"""

from __future__ import annotations

import json
import logging
from functools import lru_cache
from pathlib import Path

from common.schema import DocStatutes, QueryStatutes, StatuteMapRow, StatuteRef
from m2_statute.mapping import REPO_ROOT, load_config, load_map, relation_between

log = logging.getLogger(__name__)

STUB_PREFIX = "STUB-"
NOT_FOUND_EXPLANATION = "Document not found or no statutes extracted"

# Real doc_ids (not STUB-*) that continuity() was asked about but doc_statutes.jsonl lacks.
# Inspect after a run: a non-empty set means the extractor did not cover the corpus M1 searched.
MISSING_DOC_IDS: set[str] = set()


def _doc_statutes_path() -> Path:
    return REPO_ROOT / load_config()["paths"]["doc_statutes"]


@lru_cache(maxsize=None)
def load_doc_refs(path: str) -> dict[str, tuple[StatuteRef, ...]]:
    p = Path(path)
    if not p.exists():
        raise FileNotFoundError(
            f"{p} does not exist: the M2 extractor has not produced doc_statutes.jsonl yet, "
            "so continuity() has no judgment data to read"
        )
    out: dict[str, tuple[StatuteRef, ...]] = {}
    with p.open(encoding="utf-8") as fh:
        for line in fh:
            if line.strip():
                rec = DocStatutes.from_dict(json.loads(line))
                out[rec.doc_id] = tuple(rec.refs)
    return out


def _label(ref: StatuteRef) -> str:
    return f"{ref.act} {ref.section}"


def best_match(
    query_refs: list[StatuteRef], doc_refs: tuple[StatuteRef, ...], rows: tuple[StatuteMapRow, ...]
) -> tuple[float, str] | None:
    """Highest-weight link between any query section and any judgment section; None if there is none."""
    best: tuple[float, str] | None = None
    for q in query_refs:
        if q.act == "UNKNOWN":
            continue
        for d in doc_refs:
            if d.act == "UNKNOWN":
                continue
            if (q.act, q.section.upper()) == (d.act, d.section.upper()):
                cand = (1.0, f"{_label(q)} = {_label(d)} (same provision)")
            else:
                row = relation_between(q.act, q.section, d.act, d.section, rows)
                if row is None:
                    continue
                cand = (row.weight, f"{_label(q)} -> {_label(d)} ({row.relation})")
            if best is None or cand[0] > best[0]:
                best = cand
    return best


def continuity(qs: QueryStatutes, doc_id: str) -> tuple[float, str]:
    if not any(r.act != "UNKNOWN" for r in qs.refs):
        return 0.0, "query names no resolvable statute section"

    # Ids minted by the flagged M1 search stub never exist in the real corpus.
    if doc_id.startswith(STUB_PREFIX):
        return 0.0, NOT_FOUND_EXPLANATION

    doc_refs = load_doc_refs(str(_doc_statutes_path()))
    if doc_id not in doc_refs:
        if doc_id not in MISSING_DOC_IDS:
            log.warning("continuity(): %s is not in doc_statutes.jsonl; scoring 0.0", doc_id)
        MISSING_DOC_IDS.add(doc_id)
        return 0.0, NOT_FOUND_EXPLANATION

    match = best_match(qs.refs, doc_refs[doc_id], load_map())
    if match is None:
        return 0.0, "no mapped overlap between query sections and this judgment's sections"
    return match