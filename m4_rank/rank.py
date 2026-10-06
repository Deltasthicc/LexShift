"""rank(): take the top candidates from search(), add the other signals, normalise, fuse, explain.

    final(q, d) = w_r*rel + w_s*cont + w_h*health + w_a*auth     (weights tuned on DEV queries only)

IR concepts: static quality score g(d) and net score, score normalisation, ablation configs (B0 / B1 / full).
"""

from __future__ import annotations

from common.schema import Result
from common.skeleton import not_implemented


def rank(query: str, offence_date: str | None = None, k: int = 10, config: str = "full") -> list[Result]:
    """Top-`k` results with per-signal breakdown and explanation. `config` is one of b0, b1, full."""
    not_implemented("M4", "rank()")
