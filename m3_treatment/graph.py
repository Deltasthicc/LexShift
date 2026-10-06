"""Citation graph and PageRank over positive and neutral edges, weighted by bench strength.

IR concepts: citation graph, PageRank, static quality score g(d). Newer is not stronger: recency alone never
raises or lowers a score.

PageRank by power iteration, written out rather than taken from a library so the video can show it:
    PR(d) = (1 - a) / N  +  a * [ sum over citers c of PR(c) * w(c, d) / W(c)  +  D / N ]
where a is the damping factor, w(c, d) the edge weight, W(c) the total out-weight of c, and D the PageRank mass of
dangling judgments (those that cite nothing in the graph), spread uniformly so the scores keep summing to 1.
"""

from __future__ import annotations

import math
from typing import Iterable


def pagerank_raw(
    edges: Iterable[tuple[str, str, float]],
    nodes: Iterable[str] = (),
    damping: float = 0.85,
    tol: float = 1e-10,
    max_iter: int = 200,
) -> dict[str, float]:
    """Weighted PageRank; returns doc_id -> score, summing to 1 over all nodes (edge endpoints plus `nodes`).

    Parallel edges between the same pair are merged by taking the largest weight, so a judgment that mentions a
    precedent twenty times does not vote twenty times. Self-loops and non-positive weights are ignored.
    """
    out: dict[str, dict[str, float]] = {}
    universe: set[str] = set(nodes)
    for src, dst, w in edges:
        universe.update((src, dst))
        if src == dst or not w or w <= 0:
            continue
        row = out.setdefault(src, {})
        row[dst] = max(row.get(dst, 0.0), float(w))
    ids = sorted(universe)
    n = len(ids)
    if n == 0:
        return {}
    pr = {d: 1.0 / n for d in ids}
    totals = {s: sum(row.values()) for s, row in out.items()}
    for _ in range(max_iter):
        dangling = sum(pr[d] for d in ids if d not in out)
        base = (1.0 - damping) / n + damping * dangling / n
        nxt = {d: base for d in ids}
        for src, row in out.items():
            share = damping * pr[src] / totals[src]
            for dst, w in row.items():
                nxt[dst] += share * w
        delta = sum(abs(nxt[d] - pr[d]) for d in ids)
        pr = nxt
        if delta < tol:
            break
    return pr


def pagerank(edges: list[tuple[str, str, float]], damping: float = 0.85) -> dict[str, float]:
    """(citing, cited, weight) edges -> doc_id -> score normalised to [0, 1]."""
    pr = pagerank_raw(edges, damping=damping)
    top = max(pr.values(), default=0.0)
    return {d: (v / top if top else 0.0) for d, v in pr.items()}


def bench_weight(bench: int | None, max_bench: int = 7, unknown_bench: int = 2) -> float:
    """log(1 + bench) / log(1 + max_bench), capped at 1: a Constitution Bench outweighs a two-judge bench."""
    b = bench if bench else unknown_bench
    return min(1.0, math.log1p(b) / math.log1p(max_bench))


def authority_scores(
    pr: dict[str, float], benches: dict[str, int | None], max_bench: int = 7, unknown_bench: int = 2
) -> dict[str, float]:
    """authority(d) = normalised log(1 + N * PR(d) * bench_weight(d)), in [0, 1].

    N * PR(d) is 1 for a judgment with exactly the average PageRank; the log keeps a handful of landmark cases from
    flattening everything else to 0, and dividing by the maximum maps the corpus onto [0, 1].
    """
    n = len(pr)
    if n == 0:
        return {}
    raw = {d: math.log1p(n * v * bench_weight(benches.get(d), max_bench, unknown_bench)) for d, v in pr.items()}
    top = max(raw.values())
    return {d: (v / top if top > 0 else 0.0) for d, v in raw.items()}
