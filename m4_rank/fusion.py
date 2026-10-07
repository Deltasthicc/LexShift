"""Weighted-sum fusion of normalised signals, with heap-based top-K selection.

    final(q, d) = sum over signals s of  w_s * normalise_s(raw_s(q, d))

IR concepts: net score (relevance combined with static quality scores g(d)), top-K selection with a heap rather than a full
sort. Ties are broken deterministically (higher raw BM25, then doc_id) so the same inputs always give the same ranking.

`fuse` builds full Results (explanations, evidence). Weight tuning only needs the order, so `rank_ids` shares the same scoring
and tie-breaking and skips the rest, and `normalized_columns` lets a caller normalise once and reuse the columns for every
weight vector (normalisation does not depend on the weights).
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


Columns = dict[str, list[float]]


def normalized_columns(rows: Sequence[SignalRow], normalize_cfg: Mapping[str, str]) -> Columns:
    """Each signal collected for every row, normalised over the rows (independent of any weights)."""
    present = [s for s in SIGNALS if all(s in r.raw for r in rows)]
    return {s: normalize_column([r.raw[s] for r in rows], normalize_cfg[s]) for s in present}


def _scores(
    rows: Sequence[SignalRow], weights: Mapping[str, float], columns: Columns
) -> tuple[list[dict[str, float]], list[float]]:
    """Per-row contributions and the final score (clipped to [0, 1])."""
    active = active_signals(weights)
    missing = [s for s in active if s not in columns]
    if missing:
        raise ValueError(f"signal(s) {missing} have a weight but were not collected for every candidate")
    contribs: list[dict[str, float]] = []
    finals: list[float] = []
    for i in range(len(rows)):
        c = {s: weights[s] * columns[s][i] for s in active}
        contribs.append(c)
        finals.append(min(1.0, max(0.0, sum(c.values()))))
    return contribs, finals


def _top(rows: Sequence[SignalRow], finals: Sequence[float], k: int) -> list[int]:
    """Indices of the k best rows, best first: heap-based, O(n log k)."""
    return heapq.nsmallest(k, range(len(rows)), key=lambda i: (-finals[i], -rows[i].raw["rel"], rows[i].doc_id))


def rank_ids(rows: Sequence[SignalRow], weights: Mapping[str, float], columns: Columns, k: int) -> list[str]:
    """The doc ids `fuse` would return, without building Results. `columns` come from `normalized_columns`."""
    if k < 1:
        raise ValueError(f"k must be >= 1, got {k}")
    if not rows:
        return []
    _, finals = _scores(rows, weights, columns)
    return [rows[i].doc_id for i in _top(rows, finals, k)]


def fuse(
    rows: Sequence[SignalRow],
    weights: Mapping[str, float],
    normalize_cfg: Mapping[str, str],
    k: int,
    max_evidence: int = 3,
    stubbed: Sequence[str] = (),
    *,
    columns: Columns | None = None,
) -> list[Result]:
    """Normalise each signal over `rows`, take the weighted sum, return the top `k` as Results (best first).

    Signals that carry no weight and were not collected appear as 0.0 on the Result and are absent from `raw`.
    """
    if k < 1:
        raise ValueError(f"k must be >= 1, got {k}")
    if not rows:
        return []
    columns = columns if columns is not None else normalized_columns(rows, normalize_cfg)
    contribs, finals = _scores(rows, weights, columns)

    results: list[Result] = []
    for i in _top(rows, finals, k):
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
