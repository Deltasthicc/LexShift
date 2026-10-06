"""Query statute parser.

Finds section mentions in a free-text query; picks the governing code from an explicit act, else from the offence
date (before 1 July 2024 -> IPC, otherwise BNS); resolves collisions such as BNS 302 (religious sentiments) vs
IPC 302 (murder).

IR concepts: query expansion (a BNS 103 query also reaches IPC 302 precedents), parametric filtering by date.
"""

from __future__ import annotations

from common.schema import QueryStatutes
from common.skeleton import not_implemented


def parse_query(query: str, offence_date: str | None = None) -> QueryStatutes:
    not_implemented("M2", "parse_query()")
