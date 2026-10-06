"""The M1 public entry point: parse the query, run it against the index, return ranked candidates.

IR concepts: query parser, Boolean/proximity evaluation, BM25 scoring, heap-based top-K, zone and parametric filtering.
"""

from __future__ import annotations

from common.schema import Hit
from common.skeleton import not_implemented


def search(query: str, k: int = 100, filters: dict | None = None) -> list[Hit]:
    """Top-`k` candidates for `query`, best first, each a Hit(doc_id, rel, zone_scores).

    `filters` is for parametric constraints such as {"year": [1990, 2025], "bench_size": 5}.
    Must return in under a second on the full corpus, and must be able to print the postings and scores it used
    (that intermediate output is what the demo video shows).
    """
    not_implemented("M1", "search()")
