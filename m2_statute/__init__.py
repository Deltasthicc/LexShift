"""M2: statute layer (IPC <-> BNS continuity). Public API: parse_query(), continuity()."""

from m2_statute.matcher import continuity
from m2_statute.query_parser import parse_query

__all__ = ["parse_query", "continuity"]