"""Cohen's kappa against hand-computed values.

a = 0 0 1 1 2 2, b = 0 0 1 2 2 2:  observed agreement 5/6; marginals give chance agreement 1/3, so kappa = (5/6 - 1/3) / (2/3) = 0.75.
Quadratic weights charge the single 1-vs-2 slip 1/4: observed cost 1/24, expected cost 3/8, so kappa_w = 1 - (1/24) / (3/8) = 8/9.
"""

import pytest

from eval.agreement import agreement_report, cohens_kappa, confusion

A = [0, 0, 1, 1, 2, 2]
B = [0, 0, 1, 2, 2, 2]


def test_kappa_matches_hand_computation():
    assert cohens_kappa(A, B) == pytest.approx(0.75)
    assert cohens_kappa(A, B, weights="quadratic") == pytest.approx(8 / 9)


def test_kappa_is_symmetric():
    assert cohens_kappa(B, A) == pytest.approx(cohens_kappa(A, B))
    assert cohens_kappa(B, A, weights="quadratic") == pytest.approx(cohens_kappa(A, B, weights="quadratic"))


def test_perfect_agreement_is_one_and_chance_agreement_is_zero():
    assert cohens_kappa(A, A) == pytest.approx(1.0)
    assert cohens_kappa([0, 0, 1, 1], [0, 1, 0, 1]) == pytest.approx(0.0)


def test_a_far_miss_costs_more_than_a_near_miss_under_quadratic_weights():
    base = [0, 0, 1, 1, 2, 2, 2, 0]
    near = [0, 0, 1, 1, 2, 2, 1, 0]  # one 2-vs-1 slip
    far = [0, 0, 1, 1, 2, 2, 0, 0]  # one 2-vs-0 slip
    assert cohens_kappa(base, far, weights="quadratic") < cohens_kappa(base, near, weights="quadratic")


def test_undefined_cases_are_none():
    assert cohens_kappa([], []) is None
    assert cohens_kappa([1, 1, 1], [1, 1, 1]) is None  # both judges used one grade throughout: nothing to measure


def test_confusion_matrix_and_input_validation():
    assert confusion(A, B) == [[2, 0, 0], [0, 1, 1], [0, 0, 2]]
    with pytest.raises(ValueError, match="different numbers"):
        confusion([0, 1], [0])
    with pytest.raises(ValueError, match="outside"):
        confusion([0, 3], [0, 1])
    with pytest.raises(ValueError):
        cohens_kappa(A, B, weights="linear")


def test_kappa_needs_at_least_two_labels():
    with pytest.raises(ValueError, match="two possible labels"):
        cohens_kappa([1], [1], labels=(1,), weights="quadratic")
    with pytest.raises(ValueError):
        cohens_kappa([1], [1], labels=(1,))


def test_agreement_report_collects_everything():
    r = agreement_report(A, B)
    assert r["n"] == 6 and r["agreement"] == pytest.approx(5 / 6)
    assert r["kappa"] == pytest.approx(0.75) and r["kappa_quadratic"] == pytest.approx(8 / 9)
    assert r["grade_counts"] == {"judge1": {0: 2, 1: 2, 2: 2}, "judge2": {0: 2, 1: 1, 2: 3}}
    assert agreement_report([], [])["agreement"] is None
