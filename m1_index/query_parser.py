"""Query parser: AND / OR / NOT, "phrases", proximity /s (sentence), /p (paragraph), /k (within k words).

IR concepts: Boolean retrieval, postings intersection with terms processed in increasing document frequency,
phrase queries via the positional index, Westlaw-style proximity operators. Example: "common intention" /s murder.
"""

from __future__ import annotations

from common.skeleton import not_implemented


def parse_boolean_query(query: str):
    """Query string -> an expression tree the index can evaluate."""
    not_implemented("M1", "query_parser.parse_boolean_query()")
