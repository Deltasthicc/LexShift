"""Citation graph and PageRank over positive and neutral edges, weighted by bench strength.

IR concepts: citation graph, PageRank, static quality score g(d). Newer is not stronger: recency alone never
raises or lowers a score.
"""

from __future__ import annotations

from common.skeleton import not_implemented


def pagerank(edges: list[tuple[str, str, float]], damping: float = 0.85) -> dict[str, float]:
    """(citing, cited, weight) edges -> doc_id -> score normalised to [0, 1]."""
    not_implemented("M3", "graph.pagerank()")
