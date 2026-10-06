"""Inter-judge agreement for the two-judge qrels: percent agreement and Cohen's kappa (plain and quadratic-weighted).

Grades are ordinal (0 < 1 < 2), so the quadratic-weighted kappa, which charges a 0-vs-2 split more than a 0-vs-1 split, is the
more informative number; the plain kappa is reported next to it because it is the one people usually quote.
"""

from __future__ import annotations

from collections import Counter
from typing import Any, Sequence

LABELS = (0, 1, 2)


def confusion(a: Sequence[int], b: Sequence[int], labels: Sequence[int] = LABELS) -> list[list[int]]:
    """Rows are judge 1's grade, columns are judge 2's."""
    if len(a) != len(b):
        raise ValueError(f"the two judges graded different numbers of items ({len(a)} vs {len(b)})")
    index = {lab: i for i, lab in enumerate(labels)}
    matrix = [[0] * len(labels) for _ in labels]
    for x, y in zip(a, b):
        if x not in index or y not in index:
            raise ValueError(f"grade outside {tuple(labels)}: {x!r}, {y!r}")
        matrix[index[x]][index[y]] += 1
    return matrix


def cohens_kappa(
    a: Sequence[int], b: Sequence[int], labels: Sequence[int] = LABELS, weights: str | None = None
) -> float | None:
    """kappa = (observed - expected) / (1 - expected). `weights="quadratic"` penalises distant grades more.

    Returns None when kappa is undefined: no items, or the chance-expected disagreement is zero (both judges used one and the
    same single grade throughout, so there is nothing to measure agreement on).
    """
    if weights not in (None, "quadratic"):
        raise ValueError("weights must be None or 'quadratic'")
    n = len(a)
    if n == 0:
        return None
    matrix = confusion(a, b, labels)
    k = len(labels)
    row = [sum(matrix[i]) / n for i in range(k)]
    col = [sum(matrix[i][j] for i in range(k)) / n for j in range(k)]

    def cost(i: int, j: int) -> float:
        if weights is None:
            return 0.0 if i == j else 1.0
        return ((i - j) / (k - 1)) ** 2

    observed = sum(cost(i, j) * matrix[i][j] / n for i in range(k) for j in range(k))
    expected = sum(cost(i, j) * row[i] * col[j] for i in range(k) for j in range(k))
    if expected == 0:
        return None
    return 1.0 - observed / expected


def agreement_report(a: Sequence[int], b: Sequence[int], labels: Sequence[int] = LABELS) -> dict[str, Any]:
    n = len(a)
    same = sum(1 for x, y in zip(a, b) if x == y)
    return {
        "n": n,
        "agreement": (same / n) if n else None,
        "kappa": cohens_kappa(a, b, labels),
        "kappa_quadratic": cohens_kappa(a, b, labels, weights="quadratic"),
        "confusion": confusion(a, b, labels),
        "grade_counts": {
            "judge1": dict(sorted(Counter(a).items())),
            "judge2": dict(sorted(Counter(b).items())),
        },
    }
