"""continuity(): matches query statutes against extracted document statutes."""

from __future__ import annotations
NOT_FOUND_EXPLANATION = "Document not found or no statutes extracted"
import json
import logging
import os
from pathlib import Path

from common.schema import DocStatutes, QueryStatutes, StatuteMapRow, StatuteRef
from m2_statute.mapping import REPO_ROOT, base_section, load_config, load_map, relation_between

log = logging.getLogger(__name__)

MISSING_DOC_IDS: set[str] = set()

# Dynamically reloaded cache based on file modification time
_DOC_REFS_CACHE: dict[str, tuple[StatuteRef, ...]] = {}
_DOC_REFS_MTIME: float = 0.0

def _doc_statutes_path() -> Path:
    return REPO_ROOT / load_config()["paths"]["doc_statutes"]


def load_doc_refs(path: str) -> dict[str, tuple[StatuteRef, ...]]:
    global _DOC_REFS_MTIME, _DOC_REFS_CACHE
    p = Path(path)
    if not p.exists():
        raise FileNotFoundError(f"{p} missing: extractor has not produced doc_statutes.jsonl yet")
    
    mtime = os.path.getmtime(p)
    if mtime > _DOC_REFS_MTIME or not _DOC_REFS_CACHE:
        _DOC_REFS_CACHE.clear()
        with p.open(encoding="utf-8") as fh:
            for line in fh:
                if line.strip():
                    rec = DocStatutes.from_dict(json.loads(line))
                    _DOC_REFS_CACHE[rec.doc_id] = tuple(rec.refs)
        _DOC_REFS_MTIME = mtime
    return _DOC_REFS_CACHE


def _label(ref: StatuteRef) -> str:
    if ref.offence_id:
        return f"{ref.act} {ref.section} ({ref.offence_id})"
    return f"{ref.act} {ref.section}"


def best_match(
    query_refs: list[StatuteRef], doc_refs: tuple[StatuteRef, ...], rows: tuple[StatuteMapRow, ...]
) -> tuple[float, str] | None:
    """Highest-weight link between any query section and any judgment section."""
    best: tuple[float, str] | None = None
    
    for q in query_refs:
        for d in doc_refs:
            if q.act != "UNKNOWN" and d.act != "UNKNOWN":
                # Both name their code: the same provision (sub-clauses ignored) or the statute map's relation, scored by its weight
                if (q.act, base_section(q.section)) == (d.act, base_section(d.section)):
                    cand = (1.0, f"{_label(q)} = {_label(d)} (same provision)")
                else:
                    row = relation_between(q.act, q.section, d.act, d.section, rows)
                    if row is None:
                        continue
                    cand = (row.weight, f"{_label(q)} -> {_label(d)} ({row.relation})")
            elif q.offence_id and d.offence_id and q.offence_id == d.offence_id:
                # A prose query ("murder") carries an offence id and no code: it matches a judgment section of the same offence
                cand = (1.0, f"Lexicon Match: {q.offence_id} = {d.offence_id}")
            else:
                continue

            if best is None or cand[0] > best[0]:
                best = cand

    return best


def continuity(qs: QueryStatutes, doc_id: str) -> tuple[float, str]:
    doc_refs = load_doc_refs(str(_doc_statutes_path()))
    
    # Strict contract: raise KeyError if document is utterly absent
    if doc_id not in doc_refs:
        MISSING_DOC_IDS.add(doc_id)
        return 0.0, NOT_FOUND_EXPLANATION

    # Strict contract: 0.0 if document exists but lacks references
    if not doc_refs[doc_id]:
        return 0.0, "judgment cites no statute"

    # Must have either a valid Act or a valid Lexicon offence_id to attempt a match
    if not any(r.act != "UNKNOWN" or r.offence_id for r in qs.refs):
        return 0.0, "query names no resolvable statute section or lexicon term"

    match = best_match(qs.refs, doc_refs[doc_id], load_map())
    if match is None:
        return 0.0, "no mapped overlap between query sections and this judgment's sections"
        
    return match