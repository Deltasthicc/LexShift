"""The compact index and the optimised engine give the same answers as the dict-of-dicts implementation they replaced.

The golden files in tests/m1_golden/ were recorded from that implementation before it was changed:
  golden_small.json          a hand-made corpus of 8 judgments (zone order, a phrase that spans a zone boundary, an empty zone, ...)
                             with 172 queries: terms, plain text, AND / OR / NOT, nesting, phrases, proximity, filters, malformed input
  golden_real_excerpts.json.gz  78 real judgments (every 6th of the 468-judgment corpus, each zone cut to 2000 characters, so the file
                             is small and does not depend on the corpus file, which keeps growing) with 172 queries
The same 163-query comparison was also run once on the complete 468-judgment corpus (build, save, load, search) and passed; that
corpus is no longer the file in data/processed/, so only the excerpts are kept as a fixture.

What "identical" means: the same documents with `rel` and every zone score equal to 1e-9. Where several documents have exactly the
same score the old engine's order was the order of a Python set of strings (it changed from run to run), so such a group is compared
as a set; the new engine orders it by document id.
"""

from __future__ import annotations

import gzip
import hashlib
import json
from pathlib import Path

import pytest

pytest.importorskip("nltk")
try:
    from m1_index.index import InvertedIndex
    from m1_index.searcher import RankedSearchEngine
except (LookupError, RuntimeError, ImportError) as exc:  # NLTK stop words missing, for example
    pytest.skip(f"M1 cannot be imported here: {exc}", allow_module_level=True)

from common.schema import Judgment

ROOT = Path(__file__).resolve().parents[1]
GOLDEN = Path(__file__).resolve().parent / "m1_golden"
TOL = 1e-9


def sha(obj) -> str:
    return hashlib.sha1(json.dumps(obj, sort_keys=True).encode()).hexdigest()


def index_digest(idx: InvertedIndex, term: str) -> dict:
    post = idx.postings_map.get(term, {})
    rows = [[d, e["positions"], sorted(e["zones"].items()), e["tf"]] for d, e in post.items()]
    return {"df": idx.df(term), "n_postings": len(rows), "sha1": sha(rows), "doc_order": [r[0] for r in rows][:5]}


def assert_same_ranking(golden_hits: list[dict], hits, n_all: int, k: int, label: str) -> None:
    """The recorded top-k and the new top-k agree: same scores position by position, same documents inside every group of equal
    scores (the group cut by k excepted), same zone scores where they were recorded."""
    assert len(hits) == len(golden_hits), label
    for position, (g, h) in enumerate(zip(golden_hits, hits)):
        assert h.rel == pytest.approx(g["r"], abs=TOL), f"{label}: rel at rank {position}"
    # groups of exactly equal recorded scores
    start = 0
    while start < len(golden_hits):
        end = start
        while end + 1 < len(golden_hits) and golden_hits[end + 1]["r"] == golden_hits[start]["r"]:
            end += 1
        cut_by_k = end == len(golden_hits) - 1 and n_all > k
        want = {g["d"] for g in golden_hits[start:end + 1]}
        got = {h.doc_id for h in hits[start:end + 1]}
        if not cut_by_k:
            assert got == want, f"{label}: documents tied at rel={golden_hits[start]['r']}"
        else:
            assert len(got) == len(want), label
        start = end + 1
    by_id = {h.doc_id: h for h in hits}
    for g in golden_hits:
        if "z" in g and g["d"] in by_id:
            for zone, value in g["z"].items():
                assert by_id[g["d"]].zone_scores[zone] == pytest.approx(value, abs=TOL), f"{label}: {g['d']} {zone}"
    # the new order inside a group of equal scores is by document id
    for a, b in zip(hits, hits[1:]):
        if a.rel == b.rel:
            assert a.doc_id < b.doc_id, f"{label}: ties are ordered by document id"


def check_engine(eng: RankedSearchEngine, golden: dict) -> None:
    for rec in golden["queries"]:
        label = f"{rec['q']!r} filters={rec['f']} k={rec['k']}"
        hits = eng.search(rec["q"], k=rec["k"], filters=rec["f"])
        full = eng.search(rec["q"], k=10 ** 6, filters=rec["f"])
        assert len(full) == rec["n_all"], f"{label}: number of matching documents"
        assert sha(sorted(round(h.rel, 9) for h in full)) == rec["all_rel_sha1"], f"{label}: the scores of all matching documents"
        assert_same_ranking(rec["hits"], hits, rec["n_all"], rec["k"], label)


def check_index(idx: InvertedIndex, golden: dict) -> None:
    assert idx.stats["terms"] == golden["n_terms"] == len(idx.postings_map)
    assert idx.stats["postings"] == golden["n_postings"]
    assert idx.stats["positions"] == golden["n_positions"]
    assert sha(idx.doc_lengths) == golden["doc_lengths_sha1"]
    assert sha(idx.doc_meta) == golden["doc_meta_sha1"]
    for term, digest in golden["index"].items():
        assert index_digest(idx, term) == digest, term


# ---------------------------------------------------------------------------------------------------- the hand-made corpus
@pytest.fixture(scope="module")
def small():
    golden = json.loads((GOLDEN / "golden_small.json").read_text(encoding="utf-8"))
    idx = InvertedIndex.build(Judgment.from_dict(d) for d in golden["judgments"])
    return golden, idx, RankedSearchEngine(index=idx)


def test_the_small_index_has_the_old_postings_lengths_and_metadata(small):
    golden, idx, eng = small
    check_index(idx, golden)
    assert eng.doc_count == golden["doc_count"]
    for zone, value in golden["avg_zone_length"].items():
        assert eng.avg_zone_length[zone] == pytest.approx(value, abs=TOL)


def test_the_small_corpus_answers_every_recorded_query_as_before(small):
    golden, _, eng = small
    assert len(golden["queries"]) > 150
    check_engine(eng, golden)


def test_a_phrase_still_matches_across_a_zone_boundary_as_it_always_did(small):
    """Positions restart at 0 in every zone and the zones are joined, so "alpha gamma" matches a judgment whose headnote ends
    with alpha... at position 0 and whose facts have gamma at position 1. This is the old behaviour, kept on purpose and recorded."""
    _, _, eng = small
    assert [h.doc_id for h in eng.search('"alpha gamma"')] == ["2025_1_12_22_EN"]
    assert eng.search('"beta delta"') == []


# ---------------------------------------------------------------------------------------------------- real judgment excerpts
@pytest.fixture(scope="module")
def real():
    golden = json.loads(gzip.open(GOLDEN / "golden_real_excerpts.json.gz", "rt", encoding="utf-8").read())
    idx = InvertedIndex.build(Judgment.from_dict(d) for d in golden["judgments"])
    return golden, idx, RankedSearchEngine(index=idx)


def test_the_real_excerpts_index_has_the_old_postings_lengths_and_metadata(real):
    golden, idx, eng = real
    check_index(idx, golden)
    assert eng.doc_count == golden["doc_count"] == 78
    for zone, value in golden["avg_zone_length"].items():
        assert eng.avg_zone_length[zone] == pytest.approx(value, abs=TOL)


def test_the_real_excerpts_answer_every_recorded_query_as_before(real):
    golden, _, eng = real
    assert len(golden["queries"]) > 150 and sum(1 for q in golden["queries"] if q["n_all"]) > 100
    check_engine(eng, golden)


def test_a_saved_and_reloaded_index_answers_the_same(real, tmp_path):
    golden, idx, _ = real
    idx.save(tmp_path)
    again = InvertedIndex.load(tmp_path)
    check_index(again, golden)
    check_engine(RankedSearchEngine(index=again), golden)
