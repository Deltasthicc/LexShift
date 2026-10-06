"""Metrics against hand-computed values.

ranked = a b c d e (e is unjudged), grades a=2 b=0 c=1 d=0 x=2 (x is relevant but never retrieved), threshold 1.
    P@5  = |{a, c}| / 5 = 0.4          P@10 = 2 / 10 = 0.2         R@10 = 2 / |{a, c, x}| = 2/3
    AP   = (1/1 + 2/3) / 3             (hits at ranks 1 and 3, three judged relevant documents)
    nDCG (exp gain 2**g - 1): DCG = 3/log2(2) + 1/log2(4) = 3.5; ideal gains 3, 3, 1 -> 3 + 3/log2(3) + 1/log2(4)
"""

import math

import pytest

from eval.metrics import (
    METRIC_NAMES,
    aggregate,
    average_precision,
    dcg,
    evaluate_query,
    harmful_at_k,
    judged_at_k,
    ndcg_at_k,
    paired_bootstrap,
    precision_at_k,
    recall_at_k,
)

RANKED = ["a", "b", "c", "d", "e"]
GRADES = {"a": 2, "b": 0, "c": 1, "d": 0, "x": 2}


def test_precision_divides_by_k_even_when_fewer_results_are_returned():
    assert precision_at_k(RANKED, GRADES, 5) == pytest.approx(0.4)
    assert precision_at_k(RANKED, GRADES, 10) == pytest.approx(0.2)
    assert precision_at_k(RANKED, GRADES, 1) == 1.0


def test_precision_threshold_selects_what_counts_as_relevant():
    assert precision_at_k(RANKED, GRADES, 5, threshold=2) == pytest.approx(0.2)  # only a


def test_recall_is_relative_to_the_judged_relevant_pool():
    assert recall_at_k(RANKED, GRADES, 10) == pytest.approx(2 / 3)
    assert recall_at_k(RANKED, GRADES, 1) == pytest.approx(1 / 3)
    assert recall_at_k(RANKED, {"a": 0, "b": 0}, 10) is None


def test_average_precision():
    assert average_precision(RANKED, GRADES, 20) == pytest.approx((1 + 2 / 3) / 3)
    assert average_precision(RANKED, GRADES, 2) == pytest.approx(1 / 3)  # only the hit at rank 1 is inside the depth
    assert average_precision(RANKED, {"a": 0}, 20) is None
    assert average_precision(["x", "a"], {"a": 1, "x": 1}, 20) == pytest.approx(1.0)


def test_ndcg_exponential_gain():
    ideal = 3 + 3 / math.log2(3) + 1 / math.log2(4)
    assert ndcg_at_k(RANKED, GRADES, 10) == pytest.approx(3.5 / ideal)


def test_ndcg_linear_gain():
    expected = (2 + 1 / math.log2(4)) / (2 + 2 / math.log2(3) + 1 / math.log2(4))
    assert ndcg_at_k(RANKED, GRADES, 10, gain="linear") == pytest.approx(expected)
    with pytest.raises(ValueError):
        ndcg_at_k(RANKED, GRADES, 10, gain="log")


def test_ndcg_is_one_for_the_ideal_ranking_and_undefined_without_gradable_documents():
    assert ndcg_at_k(["a", "x", "c"], GRADES, 10) == pytest.approx(1.0)
    assert ndcg_at_k(RANKED, {"a": 0, "b": 0}, 10) is None
    assert ndcg_at_k([], GRADES, 10) == 0.0


def test_dcg_discounts_by_log2_of_rank_plus_one():
    assert dcg([1.0, 1.0]) == pytest.approx(1 + 1 / math.log2(3))


def test_judged_and_harmful_at_k():
    assert judged_at_k(RANKED, GRADES, 10) == pytest.approx(0.4)  # a b c d are judged, e is not
    assert harmful_at_k(RANKED, {"b"}, 10) == pytest.approx(0.1)
    assert harmful_at_k(RANKED, {"zzz"}, 10) == 0.0
    assert harmful_at_k(RANKED, {"a", "b"}, 5) == pytest.approx(0.4)


def test_evaluate_query_reports_every_metric_and_truncates_to_depth():
    m = evaluate_query(RANKED, GRADES, {"b"}, depth=20)
    assert set(m) == set(METRIC_NAMES)
    assert m["P@5"] == pytest.approx(0.4) and m["harmful@10"] == pytest.approx(0.1)
    shallow = evaluate_query(RANKED, GRADES, {"b"}, depth=1)
    assert shallow["P@5"] == pytest.approx(0.2)  # only the top-1 list is considered, denominator stays k


def test_harmful_is_unavailable_without_a_gold_overruling_list():
    assert evaluate_query(RANKED, GRADES, None)["harmful@10"] is None
    assert evaluate_query(RANKED, GRADES, set())["harmful@10"] is None


def test_aggregate_averages_only_where_defined():
    per_query = {
        "q1": {**{m: None for m in METRIC_NAMES}, "P@5": 0.4, "R@10": 0.5},
        "q2": {**{m: None for m in METRIC_NAMES}, "P@5": 0.8, "R@10": None},
    }
    agg = aggregate(per_query)
    assert agg["P@5"] == (pytest.approx(0.6), 2)
    assert agg["R@10"] == (pytest.approx(0.5), 1)
    assert agg["MAP"] == (None, 0)


def test_paired_bootstrap_constant_difference_has_a_degenerate_interval():
    a = {"q1": 0.5, "q2": 0.7, "q3": None}
    b = {"q1": 0.4, "q2": 0.6, "q3": 0.9}
    mean, lo, hi, n = paired_bootstrap(a, b, n_boot=500, seed=1)
    assert (mean, n) == (pytest.approx(0.1), 2)
    assert lo == pytest.approx(0.1) and hi == pytest.approx(0.1)


def test_paired_bootstrap_is_seeded_and_brackets_the_mean():
    a = {f"q{i}": v for i, v in enumerate([0.9, 0.2, 0.7, 0.4, 0.8, 0.1])}
    b = {f"q{i}": v for i, v in enumerate([0.5, 0.3, 0.6, 0.4, 0.2, 0.2])}
    first = paired_bootstrap(a, b, n_boot=2000, seed=7)
    assert first == paired_bootstrap(a, b, n_boot=2000, seed=7)
    mean, lo, hi, n = first
    assert lo <= mean <= hi and n == 6


@pytest.mark.parametrize("n_boot", [0, -3])
def test_paired_bootstrap_needs_at_least_one_resample(n_boot):
    with pytest.raises(ValueError, match="n_boot"):
        paired_bootstrap({"q1": 0.5}, {"q1": 0.4}, n_boot=n_boot)


def test_paired_bootstrap_without_shared_queries_is_none():
    assert paired_bootstrap({"q1": 0.5}, {"q2": 0.5}) is None
    assert paired_bootstrap({"q1": None}, {"q1": 0.5}) is None
