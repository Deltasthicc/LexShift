"""M1's ranking functions: lnc.ltc and flat BM25 against numbers worked out by hand on a three-document corpus, and top_k against a sort.

The corpus (one zone, tokens given directly):
    A  alpha alpha beta                    tf(alpha) = 2, tf(beta) = 1,  length 3
    B  alpha gamma                         tf(alpha) = 1, tf(gamma) = 1, length 2
    C  gamma gamma gamma delta             tf(gamma) = 3, tf(delta) = 1, length 4
    N = 3;  df: alpha 2, beta 1, gamma 2, delta 1.
"""

from __future__ import annotations

import math
import random

import pytest

pytest.importorskip("nltk")
try:
    from m1_index import scoring
    from m1_index.index import IndexBuilder
    from m1_index.searcher import RankedSearchEngine
except (LookupError, RuntimeError, ImportError) as exc:  # NLTK stop words missing, for example
    pytest.skip(f"M1 cannot be imported here: {exc}", allow_module_level=True)

from common.schema import Hit

log10 = math.log10


@pytest.fixture(scope="module")
def index():
    builder = IndexBuilder()
    for doc_id, tokens in (("A", ["alpha", "alpha", "beta"]), ("B", ["alpha", "gamma"]), ("C", ["gamma", "gamma", "gamma", "delta"])):
        builder.add_tokens(doc_id, {"year": 2020, "bench_size": 2, "title": doc_id, "date": "2020-01-01"}, {"holding": tokens})
    return builder.finish()


# ---------------------------------------------------------------------------------------------------------------- lnc.ltc
def test_lnc_ltc_matches_the_hand_computation(index):
    """Query "alpha alpha beta" (tf alpha 2, beta 1).

    Query vector (ltc): weight = (1 + log10 tf) * log10(N / df)
        alpha: (1 + log10 2) * log10(3 / 2) = 1.30103 * 0.176091 = 0.229100
        beta:  (1 + log10 1) * log10(3 / 1) = 1.0     * 0.477121 = 0.477121
        length sqrt(0.229100^2 + 0.477121^2) = sqrt(0.052487 + 0.227645) = 0.529275
        normalised: alpha 0.432857, beta 0.901463
    Document vectors (lnc): weight = 1 + log10 tf, no idf, divided by the length of the document's whole vector
        A: alpha 1.30103, beta 1.0;  length sqrt(1.692679 + 1) = 1.640938  ->  alpha 0.792855, beta 0.609406
        B: alpha 1.0, gamma 1.0;     length sqrt(2)        = 1.414214  ->  alpha 0.707107
        C: has neither query term, so it is not scored
    Scores: A = 0.432857 * 0.792855 + 0.901463 * 0.609406 = 0.343193 + 0.549359 = 0.892552
            B = 0.432857 * 0.707107                       = 0.306076
    """
    scores = scoring.lnc_ltc_scores(["alpha", "alpha", "beta"], index)
    assert set(scores) == {"A", "B"}
    assert scores["A"] == pytest.approx(0.8925516, abs=1e-6)
    assert scores["B"] == pytest.approx(0.3060759, abs=1e-6)

    # the same arithmetic, spelled out
    q_alpha, q_beta = (1 + log10(2)) * log10(3 / 2), (1 + log10(1)) * log10(3 / 1)
    q_len = math.sqrt(q_alpha ** 2 + q_beta ** 2)
    a_len = math.sqrt((1 + log10(2)) ** 2 + (1 + log10(1)) ** 2)
    b_len = math.sqrt((1 + log10(1)) ** 2 + (1 + log10(1)) ** 2)
    assert scores["A"] == pytest.approx((q_alpha / q_len) * (1 + log10(2)) / a_len + (q_beta / q_len) * 1.0 / a_len, abs=1e-12)
    assert scores["B"] == pytest.approx((q_alpha / q_len) * 1.0 / b_len, abs=1e-12)


def test_lnc_ltc_ranks_the_better_match_first_and_stays_in_the_unit_interval(index):
    scores = scoring.lnc_ltc_scores(["alpha", "beta"], index)
    assert scores["A"] > scores["B"] > 0
    assert all(0.0 <= s <= 1.0 + 1e-12 for s in scores.values())
    # a document that is exactly the query direction scores 1
    builder = IndexBuilder()
    builder.add_tokens("X", {}, {"holding": ["alpha", "beta"]})
    builder.add_tokens("Y", {}, {"holding": ["gamma", "delta"]})
    one = scoring.lnc_ltc_scores(["alpha", "beta"], builder.finish())
    assert one == {"X": pytest.approx(1.0)}


def test_lnc_ltc_edge_cases(index):
    assert scoring.lnc_ltc_scores([], index) == {}
    assert scoring.lnc_ltc_scores(["nosuchterm"], index) == {}
    assert scoring.lnc_ltc_scores(["nosuchterm", "beta"], index) == scoring.lnc_ltc_scores(["beta"], index)  # df = 0: no idf, left out of the query
    # a term in every document has idf 0: the query vector is zero, the matching documents score 0
    builder = IndexBuilder()
    for doc_id in ("X", "Y"):
        builder.add_tokens(doc_id, {}, {"holding": ["alpha", "beta"]})
    assert scoring.lnc_ltc_scores(["alpha"], builder.finish()) == {"X": 0.0, "Y": 0.0}


def test_lnc_ltc_can_be_restricted_to_candidates(index):
    both = scoring.lnc_ltc_scores(["alpha", "beta"], index)
    only_b = scoring.lnc_ltc_scores(["alpha", "beta"], index, candidates=["B", "C"])
    assert only_b == {"B": both["B"]}


def test_the_document_vector_lengths_are_stored_at_build_time(index):
    # A: sqrt((1 + log10 2)^2 + 1), B: sqrt(2), C: sqrt((1 + log10 3)^2 + 1)
    expected = [math.sqrt((1 + log10(2)) ** 2 + 1), math.sqrt(2), math.sqrt((1 + log10(3)) ** 2 + 1)]
    assert list(index.doc_norms) == pytest.approx(expected, abs=1e-12)


# ---------------------------------------------------------------------------------------------------------------- BM25
def test_flat_bm25_matches_the_hand_computation(index):
    """Query "alpha": N = 3, df = 2, idf = ln(1 + (3 - 2 + 0.5) / (2 + 0.5)) = ln(1.6) = 0.470004; avgdl = (3 + 2 + 4) / 3 = 3.
    k1 = 1.2, b = 0.75:
        A (tf 2, dl 3): 2 * 2.2 / (2 + 1.2 * (0.25 + 0.75 * 3 / 3)) = 4.4 / 3.2 = 1.375      -> 0.470004 * 1.375    = 0.646255
        B (tf 1, dl 2): 1 * 2.2 / (1 + 1.2 * (0.25 + 0.75 * 2 / 3)) = 2.2 / 1.9 = 1.157895   -> 0.470004 * 1.157895 = 0.544215
    """
    scores = scoring.bm25_scores(["alpha"], index)
    assert set(scores) == {"A", "B"}
    assert scores["A"] == pytest.approx(0.470004 * 1.375, abs=1e-6) and scores["A"] == pytest.approx(0.6462550, abs=1e-6)
    assert scores["B"] == pytest.approx(0.470004 * (2.2 / 1.9), abs=1e-6) and scores["B"] == pytest.approx(0.5442147, abs=1e-6)


def test_flat_bm25_arguments_and_repeated_terms(index):
    default = scoring.bm25_scores(["alpha"], index)
    assert scoring.bm25_scores(["alpha"], index, k1=1.2, b=0.75) == default
    # b = 0: no length normalisation, so A (tf 2) = idf * 2 * 2.2 / (2 + 1.2)
    assert scoring.bm25_scores(["alpha"], index, b=0.0)["A"] == pytest.approx(math.log(1.6) * 2 * 2.2 / (2 + 1.2), abs=1e-12)
    # a term listed twice counts twice
    twice = scoring.bm25_scores(["alpha", "alpha"], index)
    assert twice["A"] == pytest.approx(2 * default["A"], abs=1e-12)
    # two different terms add
    both = scoring.bm25_scores(["alpha", "beta"], index)
    assert both["A"] == pytest.approx(default["A"] + scoring.bm25_scores(["beta"], index)["A"], abs=1e-12)
    assert scoring.bm25_scores([], index) == {} and scoring.bm25_scores(["nosuchterm"], index) == {}
    assert scoring.bm25_scores(["alpha"], index, candidates=["B"]) == {"B": default["B"]}


def test_bm25_scores_agree_with_a_direct_formula_on_random_corpora():
    rng = random.Random(21)
    vocab = ["alpha", "beta", "gamma", "delta", "omega"]
    for _ in range(25):
        docs = {f"d{i}": [rng.choice(vocab) for _ in range(rng.randint(1, 12))] for i in range(rng.randint(2, 15))}
        builder = IndexBuilder()
        for doc_id, tokens in docs.items():
            builder.add_tokens(doc_id, {}, {"holding": tokens})
        idx = builder.finish()
        n, avgdl = len(docs), sum(len(t) for t in docs.values()) / len(docs)
        query = rng.sample(vocab, rng.randint(1, 3))
        got = scoring.bm25_scores(query, idx)
        for doc_id, tokens in docs.items():
            want = 0.0
            for term in query:
                df = sum(term in t for t in docs.values())
                tf = tokens.count(term)
                if tf:
                    want += math.log(1.0 + (n - df + 0.5) / (df + 0.5)) * tf * 2.2 / (tf + 1.2 * (0.25 + 0.75 * len(tokens) / avgdl))
            assert got.get(doc_id, 0.0) == pytest.approx(want, abs=1e-12)


# ---------------------------------------------------------------------------------------------------------------- top_k
def test_top_k_equals_the_head_of_a_full_sort_with_ties_broken_by_doc_id():
    rng = random.Random(31)
    for _ in range(200):
        scores = {f"d{rng.randint(0, 999):03d}": float(rng.choice([0, 1, 1, 2, 3, 3.5, 7])) for _ in range(rng.randint(0, 40))}
        for k in (0, 1, 2, 5, 17, len(scores), len(scores) + 3):
            expected = sorted(scores.items(), key=lambda kv: (-kv[1], kv[0]))[:max(k, 0)]
            assert scoring.top_k(scores, k) == expected


def test_top_k_edge_cases():
    assert scoring.top_k({}, 5) == []
    assert scoring.top_k({"a": 1.0}, 0) == [] and scoring.top_k({"a": 1.0}, -3) == []
    assert scoring.top_k({"b": 1.0, "a": 1.0, "c": 1.0}, 2) == [("a", 1.0), ("b", 1.0)]  # equal scores: by id, whatever the dict order
    assert scoring.top_k({"c": 1.0, "a": 1.0, "b": 1.0}, 2) == [("a", 1.0), ("b", 1.0)]
    assert scoring.top_k({"x": -1.0, "y": -2.0}, 1) == [("x", -1.0)]


def test_top_k_selects_with_a_heap_not_a_full_sort(monkeypatch):
    calls = []
    real = scoring.heapq.nsmallest
    monkeypatch.setattr(scoring.heapq, "nsmallest", lambda *a, **kw: calls.append(a[0]) or real(*a, **kw))
    scoring.top_k({f"d{i}": float(i) for i in range(50)}, 3)
    assert calls == [3]


# ---------------------------------------------------------------------------------------------------------------- the engine
def test_the_engine_ranks_with_each_scoring_and_search_stays_zone_weighted_bm25(index):
    engine = RankedSearchEngine(index=index)
    assert [h.doc_id for h in engine.rank("alpha OR beta", k=10, scoring="lnc.ltc")] == ["A", "B"]
    lnc = {h.doc_id: h.rel for h in engine.rank("alpha OR beta", k=10, scoring="lnc.ltc")}
    assert lnc == scoring.lnc_ltc_scores(["alpha", "beta"], index)
    flat = {h.doc_id: h.rel for h in engine.rank("alpha OR beta", k=10, scoring="bm25_flat")}
    assert flat == scoring.bm25_scores(["alpha", "beta"], index)
    default = engine.rank("alpha OR beta", k=10)
    assert default == engine.rank("alpha OR beta", k=10, scoring="bm25") == engine.search("alpha OR beta", k=10)
    assert all(isinstance(h, Hit) and set(h.zone_scores) == {"headnote", "facts", "arguments", "holding"} for h in default)
    assert all(h.zone_scores == {} for h in engine.rank("alpha", scoring="lnc.ltc"))  # no per-zone pieces for the whole-document scorings


def test_rank_follows_the_boolean_query_and_scores_a_not_candidate_zero(index):
    engine = RankedSearchEngine(index=index)
    assert [h.doc_id for h in engine.rank("alpha AND beta", scoring="lnc.ltc")] == ["A"]
    hits = engine.rank("NOT alpha", scoring="lnc.ltc")
    assert [(h.doc_id, h.rel) for h in hits] == [("C", 0.0)]
    assert engine.rank("alpha", k=1, scoring="lnc.ltc")[0].doc_id == "A" and engine.rank("alpha", k=0, scoring="lnc.ltc") == []
    assert engine.rank("  ", scoring="bm25_flat") == []


def test_rank_rejects_an_unknown_scoring(index):
    with pytest.raises(ValueError):
        RankedSearchEngine(index=index).rank("alpha", scoring="tfidf")
