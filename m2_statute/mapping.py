from __future__ import annotations
"""Load and query data/statute_map.csv: the typed IPC -> BNS (and key CrPC -> BNSS) mapping.

IR concept: normalisation to a controlled vocabulary. Different surface forms of one offence ("Section 302 IPC",
"S. 103 BNS", "murder") map to one offence_id (OFF_<NAME>). Split and merge relations are many-to-many with direction.

Every row must be verified in two independent sources and carry its source. Unmapped sections stay unmapped:
never guess.
"""

"""Load and query data/statute_map.csv (owner: M2). The map is the only source of relations and weights."""


import csv
from functools import lru_cache
from pathlib import Path

import yaml

from common.schema import STATUTE_MAP_COLUMNS, SchemaError, StatuteMapRow

REPO_ROOT = Path(__file__).resolve().parents[1]


@lru_cache(maxsize=None)
def load_config() -> dict:
    with (REPO_ROOT / "common" / "config.yaml").open(encoding="utf-8") as fh:
        return yaml.safe_load(fh)


@lru_cache(maxsize=None)
def load_map(path: str | None = None) -> tuple[StatuteMapRow, ...]:
    """Read and validate every row. A bad header or row is an error, never skipped."""
    p = Path(path) if path else REPO_ROOT / load_config()["paths"]["statute_map"]
    rows: list[StatuteMapRow] = []
    with p.open(newline="", encoding="utf-8") as fh:
        reader = csv.DictReader(fh)
        if tuple(reader.fieldnames or ()) != STATUTE_MAP_COLUMNS:
            raise SchemaError(f"{p}: header must be {STATUTE_MAP_COLUMNS}, got {reader.fieldnames}")
        for line_no, rec in enumerate(reader, start=2):
            try:
                rec["weight"] = float(rec["weight"])
                rows.append(StatuteMapRow.from_dict(rec))
            except (ValueError, SchemaError) as exc:
                raise SchemaError(f"{p}, line {line_no}: {exc}") from exc
    return tuple(rows)


def relation_between(
    act_a: str, sec_a: str, act_b: str, sec_b: str, rows: tuple[StatuteMapRow, ...] | None = None
) -> StatuteMapRow | None:
    """Best (highest-weight) map row linking provision A and provision B, in either direction."""
    rows = load_map() if rows is None else rows
    a = (act_a, sec_a.upper())
    b = (act_b, sec_b.upper())
    best: StatuteMapRow | None = None
    for r in rows:
        old = (r.old_act, r.old_section.upper())
        new = (r.new_act, r.new_section.upper())
        if (old, new) in ((a, b), (b, a)) and (best is None or r.weight > best.weight):
            best = r
    return best