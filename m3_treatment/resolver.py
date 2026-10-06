"""Resolve a raw citation to a corpus doc_id.

First choice: metadata (reporter_citations). Fallback: Jaccard similarity on party-name tokens plus the year.
IR concept: Jaccard coefficient.
"""

from __future__ import annotations

from common.skeleton import not_implemented


def resolve(cited_raw: str, year: int | None = None) -> str | None:
    """doc_id, or None if unresolved."""
    not_implemented("M3", "resolver.resolve()")
