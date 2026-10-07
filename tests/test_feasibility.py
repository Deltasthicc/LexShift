"""eval.feasibility: counts that tell the person writing queries whether the corpus can answer them. It never grades."""

from __future__ import annotations

import json
from collections import Counter

import pytest

import eval.feasibility as feasibility
from common.schema import Hit, Query
from eval.feasibility import Row, content_terms, mention_pattern, section_numbers, verdict


def test_content_terms_drop_stop_words_operators_and_code_names():
    assert content_terms("punishment for murder under section 103 BNS") == ["punishment", "murder"]
    # "BNS" must not be required: the IPC-era judgments that answer a BNS query never contain the word
    assert "bns" not in content_terms("common intention joint liability BNS 3(5)")
    assert content_terms("section 80") == []
    assert content_terms("anticipatory bail anticipatory bail", limit=6) == ["anticipatory", "bail"]
    assert len(content_terms("one two three four five six seven eight")) == 6


def test_section_numbers_are_read_from_the_query():
    assert section_numbers("punishment for murder under section 103 BNS") == ["103"]
    assert section_numbers("common intention joint liability BNS 3(5)") == ["3(5)"]
    assert section_numbers("arrest guidelines family welfare committee section 498A") == ["498A"]
    assert section_numbers("sections 302 and 307, then 302 again") == ["302", "307"]
    assert section_numbers("a 2025 query with no section") == []


@pytest.mark.parametrize("text, hit", [
    ("convicted under Section 103 of the BNS", True),
    ("under Sections 100, 103 and 105 of the Code", True),
    ("u/s 103 of the Act", True),
    ("S. 103 reads", True),
    ("sec. 103", True),
    ("SECTION 103", True),
    ("paragraph 103 of the judgment", False),
    ("Section 1030 was amended", False),
    ("in 2103 cases", False),
    ("IPC. 103. We have heard", False),
    ("section 10", False),
])
def test_a_mention_is_a_section_reference_not_a_paragraph_number(text, hit):
    assert bool(mention_pattern("103").search(text)) is hit


def test_the_pattern_handles_numbers_with_letters_and_brackets():
    assert mention_pattern("498A").search("under Section 498A IPC")
    assert not mention_pattern("498A").search("Section 498 IPC")
    assert mention_pattern("3(5)").search("Section 3(5) of the BNS")
    assert mention_pattern("120B").search("sections 34 and 120B")


def _row(**kw):
    base = dict(qid="q", type="A", split="dev", text="t", offence_date=None, candidates=100, all_terms=50, sections={})
    base.update(kw)
    return Row(**base)


def test_verdict_levels():
    assert verdict(_row(), ["2025"])[0] == "ok"
    assert verdict(_row(all_terms=2), ["2025"])[0] == "thin"
    assert verdict(_row(all_terms=0), ["2025"])[0] == "empty"
    assert verdict(_row(candidates=0), ["2025"])[0] == "empty"
    assert verdict(_row(sections={"103": 1}), ["2025"])[0] == "thin"
    assert verdict(_row(sections={"103": 0}), ["2025"])[0] == "empty"
    assert verdict(_row(all_terms=None), ["2025"])[0] == "ok"  # a count that could not be made is not a zero


def test_a_doctrine_query_on_a_one_year_corpus_is_flagged():
    level, note = verdict(_row(type="C"), ["2025", "2025"])
    assert level == "thin" and "one year only (2025)" in note
    assert verdict(_row(type="C"), ["2013", "2025"])[0] == "ok"
    assert verdict(_row(type="A"), ["2025"])[0] == "ok"


# ----------------------------------------------------------------------------------------------- the command
@pytest.fixture
def corpus(eval_workspace, monkeypatch):
    records = [
        {"doc_id": "D1", "title": "A v. State", "date": "2019-03-04", "text": "Convicted under Section 103 of the Code. Murder."},
        {"doc_id": "D2", "title": "B v. State", "date": "2025-01-02", "text": "paragraph 103 only; nothing else"},
        {"doc_id": "D3", "title": "C v. State", "date": "2025-02-02", "text": "Sections 100, 103 and 105 apply"},
    ]
    eval_workspace.judgments_path.write_text("".join(json.dumps(r) + "\n" for r in records), encoding="utf-8")
    monkeypatch.setattr(feasibility, "load_providers", lambda cfg=None: eval_workspace.providers)
    return eval_workspace


def test_scan_counts_section_mentions_and_years(corpus):
    counts, years, total = feasibility.scan_corpus(corpus.judgments_path, ["103", "999"])
    assert counts == {"103": 2, "999": 0} and total == 3 and years == Counter({"2019": 1, "2025": 2})


def test_the_command_reports_every_query_and_never_a_grade(corpus, capsys):
    corpus.write_queries([
        {"qid": "q1", "text": "murder under section 103 BNS", "offence_date": "2025-01-10", "split": "dev", "type": "A"},
        {"qid": "q2", "text": "section 999", "offence_date": "2025-01-10", "split": "test", "type": "D"},
    ])
    assert feasibility.main([]) == 0
    out = capsys.readouterr().out
    assert "Corpus: 3 judgments" in out and "q1" in out and "q2" in out
    assert "s.103: 2" in out and "s.999: 0" in out and "no judgment mentions section 999" in out
    assert "grade" not in out.lower().replace("not judgements", "")


def test_json_output(corpus, capsys):
    corpus.write_queries([{"qid": "q1", "text": "murder under section 103", "offence_date": None, "split": "dev", "type": "A"}])
    assert feasibility.main(["--json"]) == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["corpus"]["documents"] == 3 and payload["rows"][0]["sections"] == {"103": 2}


def test_strict_fails_on_an_empty_query(corpus, capsys):
    corpus.write_queries([{"qid": "q2", "text": "section 999", "offence_date": None, "split": "test", "type": "D"}])
    assert feasibility.main(["--strict"]) == 1
    assert feasibility.main([]) == 0


def test_with_no_hand_made_queries_the_examples_are_used_and_said_so(corpus, capsys):
    corpus.queries_path.write_text("", encoding="utf-8")
    assert feasibility.main([]) == 0
    out = capsys.readouterr().out
    assert "suggested examples" in out and "dev01" in out


def test_it_refuses_a_stub_search(corpus, monkeypatch, make_providers, capsys):
    monkeypatch.setattr(feasibility, "load_providers", lambda cfg=None: make_providers(stubbed=("search",)))
    assert feasibility.main([]) == 2
    assert "fixed-value stub" in capsys.readouterr().err


def test_it_needs_a_corpus(corpus, capsys):
    corpus.judgments_path.unlink()
    assert feasibility.main([]) == 2
    assert "has not been built" in capsys.readouterr().err


def test_a_query_the_parser_cannot_read_is_not_counted_as_zero(corpus, monkeypatch, make_providers):
    providers = make_providers()

    def search(query, k=100, filters=None):
        if " AND " in query:
            raise IndexError("end of query")
        return [Hit("A", 1.0)]

    object.__setattr__(providers, "search", search)
    rows = feasibility.analyse([Query("q", "murder intention", None, "dev", "A")], providers, {}, Counter({"2025": 3}), 100)
    assert rows[0].candidates == 1 and rows[0].all_terms is None and rows[0].verdict == "ok"


# ------------------------------------------------------------------------------------------------------------ the target estimate
def _frow(qid, type_="A", all_terms=None, sections=None):
    from eval.feasibility import Row

    return Row(qid=qid, type=type_, split="dev", text=qid, offence_date=None, candidates=100, all_terms=all_terms, sections=sections or {})


def test_matches_is_the_smaller_of_the_word_count_and_the_section_count_and_type_d_uses_sections_only():
    from eval.feasibility import matches

    assert matches(_frow("a", all_terms=7)) == 7
    assert matches(_frow("b", all_terms=20, sections={"3": 2})) == 2  # the section is the limit
    assert matches(_frow("c", all_terms=1, sections={"3": 9})) == 1  # the words are the limit
    assert matches(_frow("d", "D", all_terms=None, sections={"103": 4})) == 4
    assert matches(_frow("e", "D", all_terms=50, sections={"103": 4})) == 4  # a bare-number query is not counted by its words
    assert matches(_frow("f", all_terms=0)) == 0


def test_the_size_estimate_is_hand_checkable_and_separates_queries_that_need_specific_judgments():
    from eval.feasibility import size_for_target

    rows = [_frow("q1", all_terms=5), _frow("q2", all_terms=20, sections={"3": 2}), _frow("q3", "D", sections={"103": 4}), _frow("q4", all_terms=0), _frow("q5", all_terms=12)]
    est = size_for_target(rows, total=100, target=10)
    assert est["reach"] == ["q5"] and est["below"] == ["q1", "q2", "q3"] and est["none"] == ["q4"]
    # corpus size at which each query with matches would reach 10, if matches grew in proportion: 100 * 10 / matches
    #   q5 83.3, q1 200, q3 250, q2 500; the median of the four is the third (250), 90% of four rounds up to the fourth (500)
    assert est["size_for_median"] == 250 and est["size_for_share"] == 500


def test_the_size_estimate_has_no_number_when_no_query_matches_anything():
    from eval.feasibility import size_for_target

    est = size_for_target([_frow("q1", all_terms=0), _frow("q2", all_terms=0)], total=100, target=10)
    assert est["size_for_share"] is None and est["none"] == ["q1", "q2"]
