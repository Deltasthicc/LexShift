"""Ranking metrics. Pure functions over a ranked list of doc ids and a {doc_id: grade} judgement map.

Choices, all recorded in DECISIONS.md D-007:
  * relevant = grade >= `threshold` (default 1) for P@k, Recall@k and AP; nDCG uses graded gains;
  * a document without a judgement counts as grade 0 (pooling assumption), `judged_at_k` reports how many were judged;
  * recall and AP are relative to the judged relevant documents (the pool), not the whole corpus;
  * metrics that are undefined for a query (no relevant document) return None and are excluded from the mean.
"""

from __future__ import annotations

import math
import random
from typing import Mapping, Sequence

Grades = Mapping[str, int]


def _relevant(grades: Grades, threshold: int) -> set[str]:
    return {d for d, g in grades.items() if g >= threshold}


def precision_at_k(ranked: Sequence[str], grades: Grades, k: int, threshold: int = 1) -> float:
    """Relevant documents in the top k, divided by k (also when fewer than k were returned)."""
    rel = _relevant(grades, threshold)
    return sum(1 for d in ranked[:k] if d in rel) / k


def recall_at_k(ranked: Sequence[str], grades: Grades, k: int, threshold: int = 1) -> float | None:
    rel = _relevant(grades, threshold)
    if not rel:
        return None
    return sum(1 for d in ranked[:k] if d in rel) / len(rel)


def average_precision(ranked: Sequence[str], grades: Grades, depth: int, threshold: int = 1) -> float | None:
    """AP over the top `depth`: mean of precision at each relevant hit, divided by all judged relevant documents."""
    rel = _relevant(grades, threshold)
    if not rel:
        return None
    hits, total = 0, 0.0
    for i, d in enumerate(ranked[:depth], start=1):
        if d in rel:
            hits += 1
            total += hits / i
    return total / len(rel)


def _gain(grade: int, kind: str) -> float:
    if kind == "exp":
        return float(2**grade - 1)
    if kind == "linear":
        return float(grade)
    raise ValueError(f"unknown gain {kind!r}; use exp or linear")


def dcg(gains: Sequence[float]) -> float:
    return sum(g / math.log2(i + 1) for i, g in enumerate(gains, start=1))


def ndcg_at_k(ranked: Sequence[str], grades: Grades, k: int, gain: str = "exp") -> float | None:
    """DCG of the ranking over the DCG of the ideal ranking of the judged documents. None if nothing is gradable."""
    ideal = sorted((_gain(g, gain) for g in grades.values()), reverse=True)[:k]
    ideal_dcg = dcg(ideal)
    if ideal_dcg == 0:
        return None
    actual = dcg([_gain(grades.get(d, 0), gain) for d in ranked[:k]])
    return actual / ideal_dcg


def judged_at_k(ranked: Sequence[str], grades: Grades, k: int) -> float:
    """Share of the top k that has a judgement: a low value means the pool missed documents this system returns."""
    return sum(1 for d in ranked[:k] if d in grades) / k


def harmful_at_k(ranked: Sequence[str], overruled: set[str], k: int) -> float:
    """Share of the top k that is a known-overruled case (hand-verified gold list, not our own health signal)."""
    return sum(1 for d in ranked[:k] if d in overruled) / k


def evaluate_query(
    ranked: Sequence[str],
    grades: Grades,
    overruled: set[str] | None,
    *,
    depth: int = 20,
    threshold: int = 1,
    gain: str = "exp",
) -> dict[str, float | None]:
    """All reported metrics for one query. `harmful@10` is None when no gold overruling list is available."""
    ranked = list(ranked[:depth])
    return {
        "P@5": precision_at_k(ranked, grades, 5, threshold),
        "P@10": precision_at_k(ranked, grades, 10, threshold),
        "R@10": recall_at_k(ranked, grades, 10, threshold),
        "MAP": average_precision(ranked, grades, depth, threshold),
        "nDCG@10": ndcg_at_k(ranked, grades, 10, gain),
        "harmful@10": harmful_at_k(ranked, overruled, 10) if overruled else None,
        "judged@10": judged_at_k(ranked, grades, 10),
    }


METRIC_NAMES = ("P@5", "P@10", "R@10", "MAP", "nDCG@10", "harmful@10", "judged@10")
# Metrics where higher is better and that measure ranking quality: the only valid tuning objectives. harmful@10 is
# lower-is-better and judged@10 measures the pool, not the ranking, so neither may be optimised.
OBJECTIVES = ("nDCG@10", "MAP", "P@5", "P@10", "R@10")


def aggregate(per_query: Mapping[str, Mapping[str, float | None]]) -> dict[str, tuple[float | None, int]]:
    """Mean of each metric over the queries where it is defined: {metric: (mean or None, n queries used)}."""
    out: dict[str, tuple[float | None, int]] = {}
    for name in METRIC_NAMES:
        values = [m[name] for m in per_query.values() if m.get(name) is not None]
        out[name] = (sum(values) / len(values), len(values)) if values else (None, 0)
    return out


def paired_bootstrap(
    a: Mapping[str, float | None], b: Mapping[str, float | None], n_boot: int = 10000, seed: int = 0
) -> tuple[float, float, float, int] | None:
    """Mean difference (a - b) over shared queries with a 95% percentile-bootstrap interval: (mean, low, high, n).

    Resamples queries with replacement under a fixed seed. With a few dozen queries the interval is wide: read it as a
    reminder of that, not as a significance test. Returns None if there are no shared queries.
    """
    shared = [q for q in a if a[q] is not None and b.get(q) is not None]
    if not shared:
        return None
    diffs = [a[q] - b[q] for q in shared]  # type: ignore[operator]
    n = len(diffs)
    mean = sum(diffs) / n
    rng = random.Random(seed)
    means = sorted(sum(diffs[rng.randrange(n)] for _ in range(n)) / n for _ in range(n_boot))
    lo, hi = means[int(0.025 * n_boot)], means[min(n_boot - 1, int(0.975 * n_boot))]
    return mean, lo, hi, n
