import pytest

from m3_treatment.graph import authority_scores, bench_weight, pagerank, pagerank_raw


def test_pagerank_sums_to_one_and_handles_dangling_nodes():
    pr = pagerank_raw([("a", "b", 1), ("b", "c", 1), ("c", "a", 1), ("d", "a", 1)], nodes=["e"])
    assert sum(pr.values()) == pytest.approx(1.0)
    assert set(pr) == {"a", "b", "c", "d", "e"}
    assert pr["a"] > pr["d"] and pr["e"] == pytest.approx(pr["d"])  # nobody cites d or e


def test_pagerank_matches_a_hand_computed_two_node_graph():
    # a -> b only; b is dangling, so its mass is spread over both nodes:
    #   PR(a) = 0.15/2 + 0.85 * PR(b)/2,  PR(a) + PR(b) = 1  =>  PR(a) = 0.5 / 1.425
    pr = pagerank_raw([("a", "b", 1)], damping=0.85)
    assert pr["a"] == pytest.approx(0.5 / 1.425, abs=1e-9)
    assert pr["b"] == pytest.approx(1 - 0.5 / 1.425, abs=1e-9)


def test_pagerank_matches_networkx_style_reference_on_a_weighted_graph():
    edges = [("a", "b", 2.0), ("a", "c", 1.0), ("b", "c", 1.0), ("c", "a", 1.0), ("d", "c", 1.0)]
    pr = pagerank_raw(edges, damping=0.85)
    # reference by dense power iteration
    ids = sorted(pr)
    n = len(ids)
    out = {"a": {"b": 2, "c": 1}, "b": {"c": 1}, "c": {"a": 1}, "d": {"c": 1}}
    ref = {d: 1 / n for d in ids}
    for _ in range(500):
        ref = {
            d: 0.15 / n + 0.85 * sum(ref[s] * row.get(d, 0) / sum(row.values()) for s, row in out.items())
            for d in ids
        }
    for d in ids:
        assert pr[d] == pytest.approx(ref[d], abs=1e-8)


def test_parallel_edges_do_not_vote_twice_and_self_loops_are_ignored():
    once = pagerank_raw([("a", "b", 1.0), ("c", "b", 1.0)])
    many = pagerank_raw([("a", "b", 1.0)] * 20 + [("c", "b", 1.0), ("b", "b", 1.0)])
    assert once == pytest.approx(many)


def test_normalised_pagerank_is_in_unit_interval():
    pr = pagerank([("a", "b", 1), ("c", "b", 1)])
    assert max(pr.values()) == 1.0 and min(pr.values()) >= 0


def test_bench_weight_and_authority():
    assert bench_weight(7) == 1.0 and bench_weight(13) == 1.0
    assert bench_weight(2) < bench_weight(3) < bench_weight(5)
    assert bench_weight(None) == bench_weight(2)
    pr = {"x": 0.5, "y": 0.25, "z": 0.25}
    a = authority_scores(pr, {"x": 2, "y": 5, "z": 2})
    assert max(a.values()) == 1.0 and all(0 <= v <= 1 for v in a.values())
    assert a["y"] > a["z"]  # same PageRank, larger bench
