"""Load and query data/statute_map.csv: the typed IPC -> BNS (and key CrPC -> BNSS) mapping.

IR concept: normalisation to a controlled vocabulary. Different surface forms of one offence ("Section 302 IPC",
"S. 103 BNS", "murder") map to one offence_id (OFF_<NAME>). Split and merge relations are many-to-many with direction.

Every row must be verified in two independent sources and carry its source. Unmapped sections stay unmapped:
never guess.
"""

from __future__ import annotations

from common.schema import StatuteMapRow
from common.skeleton import not_implemented


def load_statute_map(path=None) -> list[StatuteMapRow]:
    not_implemented("M2", "mapping.load_statute_map()")


def offence_id(act: str, section: str) -> str | None:
    """OFF_<NAME> for a mapped (act, section), else None."""
    not_implemented("M2", "mapping.offence_id()")
