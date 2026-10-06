"""Score normalisation: put every signal on a common [0, 1] scale before the weighted sum.

IR concept: score normalisation for a net score. BM25 is unbounded and depends on the query, so it is min-max scaled over the
candidate set. Signals that are already calibrated weights in [0, 1] (continuity, health) are kept as they are, because
min-max would stretch a candidate set whose values only span 0.6 to 1.0 to the full range and make a penalty depend on which
other documents happened to be retrieved (DECISIONS.md D-006). The choice per signal is in `ranking.normalize`.
"""

from __future__ import annotations

import math
from typing import Callable, Sequence

_TOLERANCE = 1e-9


class NormalizationError(ValueError):
    """A signal value is not usable (not finite, or outside [0, 1] for an identity-normalised signal)."""


def minmax(values: Sequence[float]) -> list[float]:
    """(v - min) / (max - min) over the candidates.

    If there is no spread the signal cannot tell these candidates apart: every value becomes 1.0 when the shared value is
    positive and 0.0 when it is zero. Either way the ordering is unaffected.
    """
    if not values:
        return []
    lo, hi = min(values), max(values)
    if hi == lo:
        return [1.0 if hi > 0 else 0.0] * len(values)
    span = hi - lo
    return [(v - lo) / span for v in values]


def identity(values: Sequence[float]) -> list[float]:
    """Keep calibrated values as they are. Rounding noise is clipped; a real violation of [0, 1] is an error."""
    out = []
    for v in values:
        if v < -_TOLERANCE or v > 1.0 + _TOLERANCE:
            raise NormalizationError(f"value {v!r} is outside [0, 1] but its signal is configured as identity")
        out.append(min(1.0, max(0.0, v)))
    return out


NORMALIZERS: dict[str, Callable[[Sequence[float]], list[float]]] = {"minmax": minmax, "identity": identity}


def normalize_column(values: Sequence[float], strategy: str) -> list[float]:
    try:
        fn = NORMALIZERS[strategy]
    except KeyError as exc:
        raise NormalizationError(f"unknown normaliser {strategy!r}; choose one of {sorted(NORMALIZERS)}") from exc
    for v in values:
        if not math.isfinite(v):
            raise NormalizationError(f"non-finite signal value {v!r}")
    return fn(values)
