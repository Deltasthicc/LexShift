"""Ranking functions and top-K selection.

IR concepts: BM25 (the baseline B0 relies on it), lnc.ltc cosine (SMART notation), zone-weighted scoring,
heap-based top-K selection. Stretch: champion lists / tiered index.
"""

from __future__ import annotations

from common.skeleton import not_implemented


def bm25_scores(query_terms: list[str], index, k1: float = 1.2, b: float = 0.75) -> dict[str, float]:
    """doc_id -> BM25 score over the documents that contain at least one query term."""
    not_implemented("M1", "scoring.bm25_scores()")


def lnc_ltc_scores(query_terms: list[str], index) -> dict[str, float]:
    """doc_id -> cosine score: lnc for documents, ltc for the query."""
    not_implemented("M1", "scoring.lnc_ltc_scores()")


def top_k(scores: dict[str, float], k: int) -> list[tuple[str, float]]:
    """The k best (doc_id, score), highest first, via a heap rather than a full sort."""
    not_implemented("M1", "scoring.top_k()")
