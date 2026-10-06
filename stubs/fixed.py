"""Fixed-value stand-ins for every cross-module function (Guide 4.4, "Stubs first").

These exist ONLY so that integration (rank(), eval, the demo) can be built and tested from hour 0 while the real
modules are still being written. They ignore the query and return the same hard-coded table every time.

They are never evidence. Anything produced while a stub is active is flagged:
  * `Result.stubbed` lists the signals served by stubs,
  * the CLI prints a banner,
  * eval/run_ablation.py refuses to write results unless told `--allow-stubs`, and then names the output stub_*.

The doc ids are all `STUB-nnn`: none of them is a real judgment.
"""

from __future__ import annotations

from common.schema import Hit, QueryStatutes, ZONES

# doc_id: (rel, cont, health, authority). Chosen so every signal can change the ordering:
#   001 strong on everything          002 very relevant but overruled      003 doubted
#   005 offence omitted in the BNS    009 offence new in the BNS           010 relevant, overruled, high authority
_TABLE: dict[str, tuple[float, float, float, float]] = {
    "STUB-001": (14.2, 1.0, 1.0, 0.80),
    "STUB-002": (12.8, 0.5, 0.1, 0.70),
    "STUB-003": (11.0, 1.0, 0.6, 0.30),
    "STUB-004": (9.5, 0.9, 1.0, 0.55),
    "STUB-005": (8.1, 0.1, 1.0, 0.40),
    "STUB-006": (7.7, 1.0, 1.0, 0.90),
    "STUB-007": (6.0, 0.7, 1.0, 0.10),
    "STUB-008": (4.4, 1.0, 1.0, 0.20),
    "STUB-009": (3.2, 0.0, 1.0, 0.05),
    "STUB-010": (1.5, 1.0, 0.1, 0.65),
}
STUB_DOC_IDS = tuple(_TABLE)
_NOTE = "STUB: fixed value, not computed from any judgment"


def search(query: str, k: int = 100, filters: dict | None = None) -> list[Hit]:
    """M1 stand-in: the same ranked list for every query."""
    ordered = sorted(_TABLE.items(), key=lambda kv: (-kv[1][0], kv[0]))
    share = 1.0 / len(ZONES)
    return [
        Hit(doc_id=doc_id, rel=rel, zone_scores={z: round(rel * share, 6) for z in ZONES})
        for doc_id, (rel, _c, _h, _a) in ordered[: max(k, 0)]
    ]


def parse_query(query: str, offence_date: str | None = None) -> QueryStatutes:
    """M2 stand-in: finds no statutes and picks no code."""
    return QueryStatutes(query=query, offence_date=offence_date, governing_act=None, refs=[], notes=[_NOTE])


def continuity(qs: QueryStatutes, doc_id: str) -> tuple[float, str]:
    """M2 stand-in."""
    row = _TABLE.get(doc_id)
    return (row[1], _NOTE) if row else (0.0, f"{_NOTE} (unknown doc)")


def health(doc_id: str, offence_ids: list[str] | None = None) -> tuple[float, list[dict]]:
    """M3 stand-in. A below-1 value carries one clearly fake evidence item so the demo path is exercised."""
    row = _TABLE.get(doc_id)
    if row is None:
        return 1.0, []
    value = row[2]
    if value >= 1.0:
        return value, []
    label = "overruled" if value <= 0.1 else "doubted"
    return value, [{"citing_doc": "STUB-000", "label": label, "sentence": f"{_NOTE} (placeholder sentence)"}]


def authority(doc_id: str) -> float:
    """M3 stand-in."""
    row = _TABLE.get(doc_id)
    return row[3] if row else 0.0
