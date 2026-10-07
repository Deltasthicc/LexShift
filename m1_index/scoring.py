"""Ranking functions and top-K selection.

IR concepts: BM25 (the baseline B0 relies on), lnc.ltc cosine (SMART notation), heap-based top-K selection. The zone-weighted
scoring that `search()` uses lives in `searcher.py`; the functions here score a document as one bag of words (all zones joined).
Stretch: champion lists / tiered index.

All three work on an `InvertedIndex` (m1_index.index) and return plain dicts / lists keyed by document id.
"""

from __future__ import annotations

import heapq
import math
from collections import Counter
from typing import TYPE_CHECKING, Iterable

if TYPE_CHECKING:
    from m1_index.index import InvertedIndex


def _postings_in(index: InvertedIndex, term: str, nums: set[int] | None):
    """[(document number, tf)] of the term's postings, restricted to `nums` when given: probe the candidates by binary search when
    there are few of them, scan the list otherwise (whichever reads less)."""
    tp = index.term_postings(term)
    if tp is None:
        return None, []
    p_doc, p_off = index.p_doc, index.p_off
    if nums is not None and len(nums) * max(1, tp.df.bit_length()) < tp.df:
        out = []
        for n in nums:
            i = tp.find(n)
            if i >= 0:
                out.append((n, p_off[i + 1] - p_off[i]))
        return tp, out
    if nums is None:
        return tp, [(p_doc[i], p_off[i + 1] - p_off[i]) for i in range(tp.lo, tp.hi)]
    return tp, [(p_doc[i], p_off[i + 1] - p_off[i]) for i in range(tp.lo, tp.hi) if p_doc[i] in nums]


def _numbers(index: InvertedIndex, candidates: Iterable[str] | None) -> set[int] | None:
    if candidates is None:
        return None
    return {index.doc_num_of[d] for d in candidates if d in index.doc_num_of}


def bm25_scores(query_terms: list[str], index, k1: float = 1.2, b: float = 0.75, candidates: Iterable[str] | None = None) -> dict[str, float]:
    """doc_id -> BM25 score over the documents that contain at least one query term.

    Flat BM25: a document is the concatenation of its zones, `tf` is the term's total count in it, `dl` the total token count and
    `avgdl` the mean over the collection. A term repeated in `query_terms` counts once per occurrence (as in the usual BM25 sum
    over query tokens; `search()` passes distinct terms). idf = ln(1 + (N - df + 0.5) / (df + 0.5)), which is never negative.
    `candidates` (document ids) restricts the result to those documents.
    """
    n_docs, avgdl, dl = index.num_docs, index.avg_doc_length, index.doc_total_length
    nums = _numbers(index, candidates)
    acc: dict[int, float] = {}
    for term in query_terms:
        tp, rows = _postings_in(index, term, nums)
        if tp is None:
            continue
        df = tp.df
        idf = math.log(1.0 + (n_docs - df + 0.5) / (df + 0.5))
        for num, tf in rows:
            acc[num] = acc.get(num, 0.0) + idf * ((tf * (k1 + 1.0)) / (tf + k1 * (1.0 - b + b * (dl[num] / avgdl))))
    ids = index.doc_ids
    return {ids[n]: s for n, s in acc.items()}


def lnc_ltc_scores(query_terms: list[str], index, candidates: Iterable[str] | None = None) -> dict[str, float]:
    """doc_id -> cosine score: lnc for documents, ltc for the query (SMART notation).

    Document vector (lnc): l = 1 + log10(tf), n = no idf, c = cosine normalisation over all the terms of the document
    (`index.doc_norms`, computed when the index is built).
    Query vector (ltc): l = 1 + log10(tf in the query), t = idf = log10(N / df), c = cosine normalisation over the query's terms.
    Score = dot product of the two vectors, so it lies in [0, 1].

    Terms that are not in the index (df = 0) have no idf and are left out of the query vector. If every query term occurs in every
    document (idf 0) the query vector is zero and the documents that contain a term score 0.0.
    `candidates` (document ids) restricts the result to those documents.
    """
    n_docs = index.num_docs
    q_tf = Counter(query_terms)
    weights: dict[str, float] = {}
    for term, tf in q_tf.items():
        df = index.df(term)
        if df:
            weights[term] = (1.0 + math.log10(tf)) * math.log10(n_docs / df)
    q_norm = math.sqrt(sum(w * w for w in weights.values()))
    nums = _numbers(index, candidates)
    norms = index.doc_norms
    acc: dict[int, float] = {}
    for term in q_tf:
        if term not in weights:
            continue
        _, rows = _postings_in(index, term, nums)
        wq = weights[term] / q_norm if q_norm else 0.0
        for num, tf in rows:
            acc[num] = acc.get(num, 0.0) + wq * ((1.0 + math.log10(tf)) / norms[num])
    ids = index.doc_ids
    return {ids[n]: s for n, s in acc.items()}


def top_k(scores: dict[str, float], k: int) -> list[tuple[str, float]]:
    """The k best (doc_id, score), highest first, via a heap rather than a full sort. Equal scores are ordered by doc id, so the
    answer does not depend on the dict's order."""
    if k <= 0:
        return []
    return heapq.nsmallest(k, scores.items(), key=lambda item: (-item[1], item[0]))
