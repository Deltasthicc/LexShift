"""Treatment classifier: followed / distinguished / doubted / overruled / neutral, on a citation window.

Main: LLM few-shot on the window, run OFFLINE with every output cached (nothing at demo time).
Baseline: tf-idf + logistic regression. Report precision, recall and F1 per class on the hand-labelled gold set
(data/treatment_gold.csv), never accuracy alone: overruled is rare.

No raw keyword matching for treatment. Cue words may only help FIND candidate windows for labelling (to fix class
imbalance); the label itself comes from reading. "set aside" is not overruling.
"""

from __future__ import annotations

from common.skeleton import not_implemented


def classify_llm(window: str) -> tuple[str, float]:
    """(label, confidence) from the cached few-shot LLM run."""
    not_implemented("M3", "classifier.classify_llm()")


def classify_baseline(window: str) -> tuple[str, float]:
    """(label, confidence) from the tf-idf + logistic-regression baseline."""
    not_implemented("M3", "classifier.classify_baseline()")


def valid_negative(label: str, citing_bench: int | None, cited_bench: int | None) -> bool:
    """A negative label counts only if the citing bench is at least as large as the cited bench."""
    not_implemented("M3", "classifier.valid_negative()")
