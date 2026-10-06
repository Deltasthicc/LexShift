"""continuity(): how much of a judgment's statutory basis carries over to the code that applies to the query.

Best match between the query's offence ids and the judgment's offence ids (data/processed/doc_statutes.jsonl),
scored with the relation weight from statute_map.csv, plus a human-readable explanation such as
"BNS 103 -> IPC 302 (equivalent)". Design rule: old IPC judgments are not dead; penalise only in proportion to how
much the law changed.
"""

from __future__ import annotations

from common.schema import QueryStatutes
from common.skeleton import not_implemented


def continuity(qs: QueryStatutes, doc_id: str) -> tuple[float, str]:
    """(score in [0, 1], explanation)."""
    not_implemented("M2", "continuity()")
