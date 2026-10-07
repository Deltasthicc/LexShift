from __future__ import annotations
"""Load and query data/statute_map.csv: the typed IPC -> BNS (and key CrPC -> BNSS) mapping.

IR concept: normalisation to a controlled vocabulary. Different surface forms of one offence ("Section 302 IPC",
"S. 103 BNS", "murder") map to one offence_id (OFF_<NAME>). Split and merge relations are many-to-many with direction.

Every row must be verified in two independent sources and carry its source. Unmapped sections stay unmapped:
never guess.
"""

"""Load and query data/statute_map.csv (owner: M2). The map is the only source of relations and weights."""


import csv
import re
from functools import lru_cache
from pathlib import Path

import yaml

from common.schema import STATUTE_MAP_COLUMNS, SchemaError, StatuteMapRow

REPO_ROOT = Path(__file__).resolve().parents[1]


@lru_cache(maxsize=None)
def base_section(section: str) -> str:
    """'3(5)' -> '3', '438(1)' -> '438', '120-B' -> '120B': a section without its sub-clauses (the map lists whole sections)."""
    return re.sub(r"\(.*$", "", re.sub(r"[^A-Z0-9()]", "", section.upper()))


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


_INDEX: tuple[tuple[StatuteMapRow, ...], dict[tuple[tuple[str, str], tuple[str, str]], StatuteMapRow]] | None = None


def _pair_index(rows: tuple[StatuteMapRow, ...]) -> dict[tuple[tuple[str, str], tuple[str, str]], StatuteMapRow]:
    """(provision, provision) -> the highest-weight row linking them, in both directions; built once per rows tuple (a lookup is O(1), a scan of the map was not)."""
    global _INDEX
    if _INDEX is None or _INDEX[0] is not rows:
        index: dict[tuple[tuple[str, str], tuple[str, str]], StatuteMapRow] = {}
        for r in rows:
            old = (r.old_act, base_section(r.old_section))
            new = (r.new_act, base_section(r.new_section))
            for key in ((old, new), (new, old)):
                if key not in index or r.weight > index[key].weight:
                    index[key] = r
        _INDEX = (rows, index)
    return _INDEX[1]


def relation_between(
    act_a: str, sec_a: str, act_b: str, sec_b: str, rows: tuple[StatuteMapRow, ...] | None = None
) -> StatuteMapRow | None:
    """Best (highest-weight) map row linking provision A and provision B, in either direction (sub-clauses ignored)."""
    rows = load_map() if rows is None else rows
    return _pair_index(rows).get(((act_a, base_section(sec_a)), (act_b, base_section(sec_b))))
