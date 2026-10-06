"""Gold set for treatment labels: data/treatment_gold.csv (about 150-300 windows, two labellers on a subset).

Cue words may only be used to FIND candidate windows (so rare classes such as overruled are represented); the
label is assigned by reading. Report Cohen's kappa on the doubly-labelled subset.
"""

from __future__ import annotations

from common.skeleton import not_implemented


def sample_candidate_windows(n: int, seed: int = 0) -> list[dict]:
    """Class-balanced candidate windows for hand labelling (a labelling helper, not a labeller)."""
    not_implemented("M3", "gold.sample_candidate_windows()")


def cohens_kappa(labels_a: list[str], labels_b: list[str]) -> float:
    not_implemented("M3", "gold.cohens_kappa()")
