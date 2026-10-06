"""fuse() and rank(), checked against hand-computed numbers from tests/conftest.py's SCENARIO.

Normalised signals (rel and auth min-max over the four candidates, cont and health identity):
    rel   A 1.000  B 0.875  C 0.250  D 0.000        auth  A 0.500  B 0.375  C 1.000  D 0.000
full (0.5, 0.2, 0.2, 0.1):  A 0.770  B 0.875  C 0.425  D 0.400   -> B, A, C, D
b1   (0.7, 0.3):            A 1.000  B 0.9125 C 0.175  D 0.300   -> A, B, D, C
b0   (1.0):                 A 1.000  B 0.875  C 0.250  D 0.000   -> A, B, C, D
"""

import pytest

from common import contracts
from m4_rank.fusion import SignalRow, fuse
from m4_rank.rank import ContractViolation, collect, fuse_collected, rank
from m4_rank.weights import load_weights

NORMALIZE = {"rel": "minmax", "cont": "identity", "health": "identity", "auth": "minmax"}


def ids(results):
    return [r.doc_id for r in results]


# ------------------------------------------------------------------------ fuse
def rows(spec):
    return [SignalRow(doc_id=d, raw=dict(raw)) for d, raw in spec.items()]


def test_fuse_matches_hand_computed_weighted_sum():
    spec = {"A": {"rel": 10.0, "cont": 0.5}, "B": {"rel": 5.0, "cont": 1.0}, "C": {"rel": 0.0, "cont": 1.0}}
    out = fuse(rows(spec), {"rel": 0.6, "cont": 0.4, "health": 0.0, "auth": 0.0}, NORMALIZE, k=3)
    assert ids(out) == ["A", "B", "C"]
    assert [round(r.final, 6) for r in out] == [0.8, 0.7, 0.4]
    assert out[0].contributions == pytest.approx({"rel": 0.6, "cont": 0.2})
    for r in out:
        assert sum(r.contributions.values()) == pytest.approx(r.final)


def test_fuse_top_k_agrees_with_a_full_sort():
    spec = {f"d{i:02d}": {"rel": float((i * 7) % 13)} for i in range(30)}
    w = {"rel": 1.0, "cont": 0.0, "health": 0.0, "auth": 0.0}
    everything = fuse(rows(spec), w, NORMALIZE, k=30)
    assert ids(fuse(rows(spec), w, NORMALIZE, k=5)) == ids(everything)[:5]
    assert len(fuse(rows(spec), w, NORMALIZE, k=100)) == 30


def test_fuse_ties_break_on_raw_relevance_then_doc_id():
    # Identical final scores: same weighted sum from different raw rel, then fully identical signals.
    spec = {"zz": {"rel": 4.0, "cont": 0.0}, "aa": {"rel": 4.0, "cont": 0.0}, "mm": {"rel": 4.0, "cont": 0.0}}
    out = fuse(rows(spec), {"rel": 0.5, "cont": 0.5, "health": 0.0, "auth": 0.0}, NORMALIZE, k=3)
    assert ids(out) == ["aa", "mm", "zz"]


def test_fuse_is_deterministic_regardless_of_input_order():
    spec = {"A": {"rel": 3.0}, "B": {"rel": 3.0}, "C": {"rel": 1.0}}
    w = {"rel": 1.0, "cont": 0.0, "health": 0.0, "auth": 0.0}
    forward = ids(fuse(rows(spec), w, NORMALIZE, 3))
    backward = ids(fuse(list(reversed(rows(spec))), w, NORMALIZE, 3))
    assert forward == backward


def test_fuse_rejects_weight_on_an_uncollected_signal_and_bad_k():
    with pytest.raises(ValueError, match="were not collected"):
        fuse(rows({"A": {"rel": 1.0}}), {"rel": 0.5, "cont": 0.5, "health": 0.0, "auth": 0.0}, NORMALIZE, 1)
    with pytest.raises(ValueError, match="k must be"):
        fuse(rows({"A": {"rel": 1.0}}), {"rel": 1.0, "cont": 0.0, "health": 0.0, "auth": 0.0}, NORMALIZE, 0)
    assert fuse([], {"rel": 1.0, "cont": 0.0, "health": 0.0, "auth": 0.0}, NORMALIZE, 5) == []


def test_fuse_unused_signals_are_zero_and_absent_from_raw():
    out = fuse(rows({"A": {"rel": 2.0}, "B": {"rel": 1.0}}), {"rel": 1.0, "cont": 0.0, "health": 0.0, "auth": 0.0}, NORMALIZE, 2)
    assert out[0].cont == out[0].health == out[0].auth == 0.0
    assert set(out[0].raw) == {"rel"}


def test_fuse_truncates_evidence_and_flags_stubs():
    ev = [{"citing_doc": f"C{i}", "label": "overruled", "sentence": "s"} for i in range(5)]
    r = [SignalRow("A", {"rel": 1.0, "health": 0.1}, evidence=ev)]
    out = fuse(r, {"rel": 0.5, "cont": 0.0, "health": 0.5, "auth": 0.0}, NORMALIZE, 1, max_evidence=2, stubbed=["health"])
    assert len(out[0].evidence) == 2
    assert out[0].stubbed == ["health"]
    assert "STUB" in out[0].explanation
    assert "per C0 +4 more" in out[0].explanation  # strongest evidence named, the rest counted


# ------------------------------------------------------------------------ rank
def test_b0_is_plain_relevance_order(make_providers):
    p = make_providers()
    out = rank("murder", None, k=4, config="b0", providers=p)
    assert ids(out) == ["A", "B", "C", "D"]
    assert [round(r.final, 4) for r in out] == [1.0, 0.875, 0.25, 0.0]


def test_b1_continuity_reorders_without_touching_treatment(make_providers):
    p = make_providers()
    out = rank("murder", None, k=4, config="b1", providers=p)
    assert ids(out) == ["A", "B", "D", "C"]
    assert [round(r.final, 4) for r in out] == [1.0, 0.9125, 0.3, 0.175]
    assert p.calls["health"] == 0 and p.calls["authority"] == 0


def test_full_drops_the_low_health_document_below_a_healthy_one(make_providers):
    p = make_providers()
    out = rank("murder", None, k=4, config="full", providers=p)
    assert ids(out) == ["B", "A", "C", "D"]
    assert [round(r.final, 4) for r in out] == [0.875, 0.77, 0.425, 0.4]
    by_id = {r.doc_id: r for r in out}
    assert by_id["A"].health == pytest.approx(0.1)
    assert by_id["A"].evidence and by_id["A"].evidence[0]["label"] == "overruled"
    assert "overruled per Z" in by_id["A"].explanation
    assert "IPC 124A omitted in BNS" in by_id["C"].explanation
    assert by_id["A"].raw == {"rel": 10.0, "cont": 1.0, "health": 0.1, "auth": 0.5}


def test_b0_never_calls_the_statute_or_treatment_providers(make_providers):
    p = make_providers()
    rank("murder", None, k=3, config="b0", providers=p)
    assert p.calls == {"search": 1, "parse_query": 0, "continuity": 0, "health": 0, "authority": 0}


def test_b2_is_an_alias_of_full(make_providers):
    a = rank("q", None, k=4, config="b2", providers=make_providers())
    b = rank("q", None, k=4, config="full", providers=make_providers())
    assert [(r.doc_id, r.final) for r in a] == [(r.doc_id, r.final) for r in b]


def test_rank_asks_search_for_the_configured_candidate_depth(make_providers):
    p = make_providers()
    rank("q", None, k=2, config="full", providers=p)
    assert p.seen["search_k"] == [100]
    assert len(rank("q", None, k=2, config="full", providers=p)) == 2


def test_rank_passes_the_query_offence_ids_to_health(make_providers):
    p = make_providers(offence_ids=["OFF_MURDER"])
    rank("BNS 103", "2025-01-10", k=2, config="full", providers=p)
    assert set(map(tuple, p.seen["health_offence_ids"])) == {("OFF_MURDER",)}
    q = make_providers()
    rank("plain doctrine query", None, k=2, config="full", providers=q)
    assert set(q.seen["health_offence_ids"]) == {None}


def test_results_satisfy_the_rank_contract_and_are_deterministic(make_providers):
    p = make_providers()
    for config in ("b0", "b1", "full"):
        first = rank("q", "2024-08-01", k=3, config=config, providers=p)
        again = rank("q", "2024-08-01", k=3, config=config, providers=p)
        assert contracts.check_results(first, 3, {"A", "B", "C", "D"}) == []
        assert [(r.doc_id, r.final) for r in first] == [(r.doc_id, r.final) for r in again]


def test_stub_flags_cover_only_signals_the_config_uses(make_providers):
    p = make_providers(stubbed={"health"})
    assert rank("q", None, k=2, config="b0", providers=p)[0].stubbed == []
    assert rank("q", None, k=2, config="b1", providers=p)[0].stubbed == []
    assert rank("q", None, k=2, config="full", providers=p)[0].stubbed == ["health"]


def test_explanations_never_use_the_forbidden_wording(make_providers):
    for r in rank("q", None, k=4, config="full", providers=make_providers()):
        assert "bad law" not in r.explanation.lower() and "dead law" not in r.explanation.lower()


@pytest.mark.parametrize(
    "args,kwargs",
    [
        (("", None), {}),
        (("   ", None), {}),
        (("q", "01/02/2025"), {}),
        (("q", None), {"k": 0}),
        (("q", None), {"config": "b9"}),
    ],
)
def test_rank_rejects_bad_inputs(make_providers, args, kwargs):
    with pytest.raises(ValueError):
        rank(*args, providers=make_providers(), **kwargs)


def test_rank_raises_when_a_provider_breaks_its_contract(make_providers, scenario):
    scenario["A"]["health"] = 1.5
    with pytest.raises(ContractViolation, match="health"):
        rank("q", None, k=2, config="full", providers=make_providers(scenario))


def test_rank_raises_on_unsorted_or_duplicate_search_hits(make_providers):
    from common.providers import Providers
    from common.schema import Hit

    good = make_providers()
    unsorted_p = Providers(lambda q, k=100, filters=None: [Hit("A", 1.0), Hit("B", 2.0)], good.parse_query,
                           good.continuity, good.health, good.authority, frozenset())
    with pytest.raises(ContractViolation, match="search"):
        rank("q", None, k=2, config="b0", providers=unsorted_p)
    dup_p = Providers(lambda q, k=100, filters=None: [Hit("A", 2.0), Hit("A", 1.0)], good.parse_query,
                      good.continuity, good.health, good.authority, frozenset())
    with pytest.raises(ContractViolation, match="duplicate"):
        rank("q", None, k=2, config="b0", providers=dup_p)


def test_stubbed_groups_always_counts_search_because_it_supplies_the_candidates(make_providers):
    from m4_rank.rank import stubbed_groups

    p = make_providers(stubbed={"search", "health"})
    assert stubbed_groups(p, ("rel",)) == ["search"]
    assert stubbed_groups(p, ("cont",)) == ["search"]  # rel is implied
    assert stubbed_groups(p, ("cont", "health", "auth")) == ["health", "search"]
    assert stubbed_groups(make_providers(), ("rel", "cont", "health", "auth")) == []
    assert stubbed_groups(make_providers(stubbed={"authority", "statute"}), ("rel",)) == []


def test_text_with_the_piece_separator_is_cleaned_in_explanations():
    r = [SignalRow("A", {"rel": 1.0, "cont": 1.0}, cont_why="x | y\nz")]
    out = fuse(r, {"rel": 0.5, "cont": 0.5, "health": 0.0, "auth": 0.0}, NORMALIZE, 1)[0]
    assert "x / y z" in out.explanation and out.explanation.count(" | ") == 1 and "\n" not in out.explanation


def test_collect_once_then_fuse_under_many_weight_vectors(make_providers):
    p = make_providers()
    collected = collect("q", None, ("rel", "cont", "health", "auth"), providers=p)
    calls_after_collect = dict(p.calls)
    for w in (load_weights("b0"), load_weights("b1"), load_weights("full")):
        fuse_collected(collected, w, 4)
    assert p.calls == calls_after_collect  # fusing again never calls a provider
