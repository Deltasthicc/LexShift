"""The connections between modules, tested against the real code and, where it exists, the real data.

These tests pin the integration fixes made when M1, M2 and M3 were merged with M4 (DECISIONS.md D-026) and they run the real
M1 search over the corpus M1 committed. They skip, with a reason, when a dependency is missing (NLTK data, the committed index)
instead of failing on a machine that has not got it.
"""

import io
import contextlib
import json
import subprocess
import sys
from pathlib import Path

import pytest

from common import contracts
from common.schema import Hit
from m3_treatment.resolver import _PATH_ID, bench_from_text, year_of
from m4_rank.rank import ArtefactError, as_hit, load_checked

ROOT = Path(__file__).resolve().parents[1]
INDEX = ROOT / "data" / "processed" / "index" / "inverted_index.json"


# ---------------------------------------------------------------- M3 reads the formats the real corpus has
@pytest.mark.parametrize("date,year", [
    ("2025-01-02", 2025), ("02 January 2025", 2025), ("11-12-2013", 2013), ("2013", 2013), ("", None), (None, None), ("no year", None),
])
def test_m3_reads_the_year_from_any_date_shape(date, year):
    assert year_of(date) == year


@pytest.mark.parametrize("doc_id,ok", [
    ("2013_17_116_254", True), ("2025_1_1_11_EN", True), ("2018_7_379_746_EN", True),
    ("2025_1_1", False), ("abc_1_2_3", False), ("2025_1_1_11_ENGLISH_X", False),
])
def test_m3_resolver_accepts_the_dataset_file_stem_as_doc_id(doc_id, ok):
    assert bool(_PATH_ID.match(doc_id)) is ok


def test_m3_reads_both_printed_coram_shapes_and_still_ignores_authorship_notes():
    older = "[DIPAK MISRA, CJI, R.F. NARIMAN, A.M. KHANWILKAR, DR. D.Y. CHANDRACHUD AND INDU MALHOTRA, JJ.] text"
    recent = "Kim Wansoo v. State 02 January 2025 [C.T. Ravikumar* and Sanjay Kumar, JJ.] Issue for Consideration"
    three = "[Abhay S. Oka, Ahsanuddin Amanullah* and Augustine George Masih, JJ.]"
    assert bench_from_text(older) == 5 and bench_from_text(recent) == 2 and bench_from_text(three) == 3
    assert bench_from_text("[for himself and Khanwilkar, J.] we hold") is None  # an authorship note is not a coram line
    assert bench_from_text("no coram here") is None


# ------------------------------------------------------------------------------------- M4 accepts what the modules return
class ForeignHit:
    """M1 used to define its own Hit class with the same fields."""

    def __init__(self, doc_id, rel, zone_scores=None):
        self.doc_id, self.rel, self.zone_scores = doc_id, rel, zone_scores


def test_as_hit_accepts_any_object_with_the_three_fields_and_leaves_the_rest_to_the_contract():
    h = as_hit(ForeignHit("d1", 2.5, {"holding": 1.0}))
    assert isinstance(h, Hit) and (h.doc_id, h.rel, h.zone_scores) == ("d1", 2.5, {"holding": 1.0})
    assert as_hit(ForeignHit("d2", 1.0)).zone_scores == {}
    assert as_hit({"doc_id": "d3", "rel": 0.5}).zone_scores == {}
    original = Hit("d4", 1.0)
    assert as_hit(original) is original
    assert as_hit("garbage") == "garbage" and as_hit(None) is None  # returned unchanged so check_hits reports it
    assert contracts.check_hits([as_hit(ForeignHit("a", 2.0)), as_hit(ForeignHit("b", -1.0))], 5)  # bad content is still caught


def test_rank_works_with_a_provider_that_returns_foreign_hits(make_providers):
    from common.providers import Providers
    from m4_rank.rank import rank

    good = make_providers()
    foreign = Providers(lambda q, k=100, filters=None: [ForeignHit("A", 3.0), ForeignHit("B", 1.0)], good.parse_query,
                        good.continuity, good.health, good.authority, frozenset())
    assert [r.doc_id for r in rank("q", None, k=2, config="b0", providers=foreign)] == ["A", "B"]


def test_load_checked_turns_unloadable_modules_into_one_clear_error_and_keeps_stdout_clean(capsys):
    def noisy_loader(cfg):
        print("Loading index...")
        return "providers"

    assert load_checked(noisy_loader) == "providers"
    captured = capsys.readouterr()
    assert captured.out == "" and "Loading index..." in captured.err  # a module's chatter never reaches machine-readable stdout

    for exc in (ImportError("no nltk"), LookupError("stopwords"), FileNotFoundError("index"), RuntimeError("corpus")):
        def failing(cfg, exc=exc):
            raise exc

        with pytest.raises(ArtefactError, match=type(exc).__name__):
            load_checked(failing)


def test_a_search_stub_makes_every_signal_a_stub_even_when_the_other_modules_are_real(make_providers):
    from m4_rank.rank import rank

    p = make_providers(stubbed={"search"})
    assert rank("q", None, k=2, config="full", providers=p)[0].stubbed == ["rel", "cont", "health", "auth"]


def test_control_characters_never_reach_the_screen_or_the_judges_sheet():
    from app.cli import render_evidence
    from eval.pool import safe_cell
    from m4_rank.explain import strip_controls

    dirty = "of law and as such,\x08 \x07the appeal\x0c is allowed"
    assert strip_controls(dirty) == "of law and as such, the appeal is allowed"
    assert strip_controls("keep\nnewlines\tand tabs") == "keep\nnewlines\tand tabs"
    assert "\x08" not in " ".join(render_evidence({"citing_doc": "X", "label": "overruled", "sentence": dirty}))
    assert safe_cell("\x08=SUM(1)") == "'=SUM(1)"  # stripped first, then the formula guard applies


# --------------------------------------------------------------- M1: the real search over the corpus M1 committed
@pytest.fixture(scope="module")
def m1():
    if not INDEX.exists():
        pytest.skip("M1's committed index is not present")
    try:
        with contextlib.redirect_stdout(io.StringIO()):
            from m1_index import searcher
    except (LookupError, RuntimeError, ImportError) as exc:
        pytest.skip(f"M1 cannot be imported here: {exc}")
    return searcher


def test_m1_plain_text_is_told_apart_from_boolean_syntax(m1):
    plain = ["BNS 103", "punishment for murder under section 103 BNS", "BNS 3(5)", "common intention (section 34)",
             "u/s 120-B IPC", "cheating and dishonestly inducing delivery", "what is 'cheating'?", "murder, intention"]
    boolean = ["murder AND intention", "ipc OR bns", "ipc AND NOT bns", '"common intention"', '"common intention" /s murder',
               "murder /p intention", "murder /10 intention", "(murder OR theft) AND intention"]
    assert all(m1.is_plain_text(q) for q in plain), [q for q in plain if not m1.is_plain_text(q)]
    assert not any(m1.is_plain_text(q) for q in boolean), [q for q in boolean if m1.is_plain_text(q)]


def test_m1_answers_free_text_boolean_and_edge_queries_with_contract_valid_shared_hits(m1):
    from m1_index import search

    for query in ("BNS 103", "punishment for murder under section 103 BNS", "BNS 3(5)", "u/s 120-B IPC", "murder AND intention",
                  '"common intention" /s murder'):
        hits = search(query, k=10)
        assert hits, query
        assert all(type(h) is Hit for h in hits), "M1 must return common.schema.Hit"
        assert contracts.check_hits(hits, 10) == [], query
    for query in ("", "   ", "the", "O'Brien"):
        assert search(query, k=5) == [] or contracts.check_hits(search(query, k=5), 5) == []  # never an exception


def test_m1_year_and_bench_filters_work_on_the_real_metadata(m1):
    from m1_index import search

    total = len(search("murder", k=500))
    assert total > 0
    in_2025 = len(search("murder", k=500, filters={"year": 2025}))
    assert in_2025 == total  # the committed sample is 2025 only; this was 0 before the date fix
    assert len(search("murder", k=500, filters={"min_year": 2025})) == total
    assert len(search("murder", k=500, filters={"max_year": 2024})) == 0
    assert len(search("murder", k=500, filters={"year": 1999})) == 0


def test_m1_results_are_ranked_deterministic_and_respect_k(m1):
    from m1_index import search

    a, b = search("murder AND intention", k=7), search("murder AND intention", k=7)
    assert [(h.doc_id, h.rel) for h in a] == [(h.doc_id, h.rel) for h in b]
    assert len(a) <= 7 and [h.rel for h in a] == sorted((h.rel for h in a), reverse=True)
    assert search("murder", k=0) == []


def test_importing_m1_prints_nothing_and_does_not_load_the_index():
    code = ("import io, contextlib, sys\nbuf = io.StringIO()\n"
            "with contextlib.redirect_stdout(buf):\n    import m1_index\n"
            "import m1_index.searcher as s\nprint(len(buf.getvalue()), s._engine is None)")
    run = subprocess.run([sys.executable, "-c", code], cwd=ROOT, capture_output=True, text=True, timeout=120)
    if run.returncode != 0 and ("stopwords" in run.stderr or "nltk" in run.stderr.lower()):
        pytest.skip("NLTK stopwords are not installed here")
    assert run.returncode == 0, run.stderr[-400:]
    assert run.stdout.split() == ["0", "True"]  # nothing printed, engine not built at import


def test_the_real_chain_returns_real_hits_through_rank(m1, make_providers):
    """M1's real search feeding M4's rank(): the Hit class and the scores flow through unchanged."""
    from common.providers import Providers
    from m1_index import search
    from m4_rank.rank import rank

    good = make_providers()
    real_search = Providers(search, good.parse_query, good.continuity, good.health, good.authority, frozenset({"statute", "health", "authority"}))
    # health and authority fixtures only know ids A-D, so rank with b0 (BM25 only): the real M1 ids flow through
    results = rank("BNS 103", "2025-01-10", k=5, config="b0", providers=real_search)
    assert len(results) == 5 and all(r.doc_id.startswith("2025_") for r in results)
    assert results[0].final == 1.0 and results[0].raw["rel"] > results[-1].raw["rel"] > 0
    assert json.dumps([r.to_dict() for r in results])  # serialisable end to end
