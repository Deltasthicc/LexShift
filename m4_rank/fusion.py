"""Weighted-sum fusion of normalised signals, with heap-based top-K selection.

    final(q, d) = sum over signals s of  w_s * normalise_s(raw_s(q, d))

IR concepts: net score (relevance combined with static quality scores g(d)), top-K selection with a heap rather than a full
sort. Ties are broken deterministically (higher raw BM25, then doc_id) so the same inputs always give the same ranking.
"""

from __future__ import annotations

import heapq
from dataclasses import dataclass, field
from typing import Mapping, Sequence

from common.schema import Result
from m4_rank.explain import build_explanation
from m4_rank.normalize import normalize_column
from m4_rank.weights import SIGNALS, active_signals


@dataclass
class SignalRow:
    """One candidate with its raw (un-normalised) signal values and the reasons behind them."""

    doc_id: str
    raw: dict[str, float]  # always "rel"; "cont", "health", "auth" only if collected
    cont_why: str = ""  # M2's explanation of the continuity value
    evidence: list[dict] = field(default_factory=list)  # M3's evidence, strongest first


def fuse(
    rows: Sequence[SignalRow],
    weights: Mapping[str, float],
    normalize_cfg: Mapping[str, str],
    k: int,
    max_evidence: int = 3,
    stubbed: Sequence[str] = (),
) -> list[Result]:
    """Normalise each signal over `rows`, take the weighted sum, return the top `k` as Results (best first).

    Signals that carry no weight and were not collected appear as 0.0 on the Result and are absent from `raw`.
    """
    if k < 1:
        raise ValueError(f"k must be >= 1, got {k}")
    if not rows:
        return []
    active = active_signals(weights)
    present = [s for s in SIGNALS if all(s in r.raw for r in rows)]
    missing = [s for s in active if s not in present]
    if missing:
        raise ValueError(f"signal(s) {missing} have a weight but were not collected for every candidate")

    columns = {s: normalize_column([r.raw[s] for r in rows], normalize_cfg[s]) for s in present}
    finals: list[float] = []
    contribs: list[dict[str, float]] = []
    for i in range(len(rows)):
        c = {s: weights[s] * columns[s][i] for s in active}
        contribs.append(c)
        finals.append(min(1.0, max(0.0, sum(c.values()))))

    # heap-based top-k: O(n log k); key sorts best first
    best = heapq.nsmallest(k, range(len(rows)), key=lambda i: (-finals[i], -rows[i].raw["rel"], rows[i].doc_id))

    results: list[Result] = []
    for i in best:
        row = rows[i]
        norm = {s: (columns[s][i] if s in columns else 0.0) for s in SIGNALS}
        shown = list(row.evidence[:max_evidence])  # the explanation still counts the full list, so it never understates
        result = Result(
            doc_id=row.doc_id,
            final=finals[i],
            rel=norm["rel"],
            cont=norm["cont"],
            health=norm["health"],
            auth=norm["auth"],
            explanation=build_explanation(row.raw, norm, weights, contribs[i], row.cont_why, row.evidence, stubbed),
            evidence=shown,
            raw=dict(row.raw),
            contributions=dict(contribs[i]),
            stubbed=list(stubbed),
        )
        result.validate()
        results.append(result)
    return results
