"""Split a judgment into zones: headnote, facts, arguments, holding.

IR concept: zone index. A hit in the holding is stronger evidence than a hit in the facts, so the index keeps
per-zone postings and the scorer weights them. A rough heuristic (headings plus position) is enough: do not
over-engineer it, and inspect real text before committing to rules.
"""

from __future__ import annotations

from common.skeleton import not_implemented


def split_zones(text: str) -> dict[str, str]:
    """Map zone name (keys from common.schema.ZONES) -> text. A zone that cannot be found is simply absent."""
    not_implemented("M1", "zones.split_zones()")
