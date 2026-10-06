import json

from common.schema import DocStatutes, StatuteRef
from m2_statute import matcher
from m2_statute.mapping import load_map
from m2_statute.matcher import best_match, continuity
from m2_statute.query_parser import parse_query


def test_parse_act_first_and_section_first():
    assert [(r.act, r.section) for r in parse_query("murder under IPC 302").refs] == [("IPC", "302")]
    assert [(r.act, r.section) for r in parse_query("section 103 of the BNS").refs] == [("BNS", "103")]


def test_offence_date_picks_code():
    assert parse_query("murder", "2023-05-01").governing_act == "IPC"
    assert parse_query("murder", "2024-07-01").governing_act == "BNS"


def test_bare_section_is_unknown_not_guessed():
    qs = parse_query("section 302 murder")
    assert [(r.act, r.section) for r in qs.refs] == [("UNKNOWN", "302")]
    assert qs.notes


def test_best_match_bns_to_ipc_uses_real_map():
    qs = parse_query("BNS 103")
    doc = (StatuteRef(act="IPC", section="302"),)
    assert best_match(qs.refs, doc, load_map()) == (1.0, "BNS 103 -> IPC 302 (equivalent)")


def test_no_overlap_scores_zero():
    qs = parse_query("BNS 103")
    assert best_match(qs.refs, (StatuteRef(act="IPC", section="420"),), load_map()) is None


def test_continuity_reads_doc_statutes(tmp_path, monkeypatch):
    f = tmp_path / "doc_statutes.jsonl"
    rec = DocStatutes(doc_id="D1", refs=[StatuteRef(act="IPC", section="302")])
    f.write_text(json.dumps(rec.to_dict()) + "\n", encoding="utf-8")
    monkeypatch.setattr(matcher, "_doc_statutes_path", lambda: f)
    assert continuity(parse_query("BNS 103"), "D1") == (1.0, "BNS 103 -> IPC 302 (equivalent)")

def test_stub_ids_score_zero_without_reading_file():
    score, why = continuity(parse_query("BNS 103"), "STUB-001")
    assert score == 0.0 and why == matcher.NOT_FOUND_EXPLANATION
    assert "STUB-001" not in matcher.MISSING_DOC_IDS


def test_missing_real_doc_scores_zero_and_is_recorded(tmp_path, monkeypatch):
    f = tmp_path / "doc_statutes.jsonl"
    rec = DocStatutes(doc_id="D1", refs=[StatuteRef(act="IPC", section="302")])
    f.write_text(json.dumps(rec.to_dict()) + "\n", encoding="utf-8")
    monkeypatch.setattr(matcher, "_doc_statutes_path", lambda: f)
    matcher.MISSING_DOC_IDS.clear()
    assert continuity(parse_query("BNS 103"), "NOT-IN-FILE") == (0.0, matcher.NOT_FOUND_EXPLANATION)
    assert "NOT-IN-FILE" in matcher.MISSING_DOC_IDS