"""The conformance checker (eval/conformance.py), tested on small synthetic artefacts and substitute parsers, so it does not
depend on how far M1, M2 or M3 have got."""

import json
import sys
import types

import pytest

from common.io import write_jsonl
from eval import conformance
from eval.conformance import Report, check_m1_data, check_m2_api, check_m2_data, check_m3_data, coram_count, render, run


def judgment(doc_id, date="2025-01-02", bench=2, text=None, reporter=("[2025] 1 S.C.R. 1",), zones=None):
    text = text or "[C.T. Ravikumar* and Sanjay Kumar, JJ.] The appeal under Section 302 IPC is allowed."
    return {"doc_id": doc_id, "title": f"A v. B {doc_id}", "date": date, "bench_size": bench, "judges": ["x", "y"],
            "reporter_citations": list(reporter), "zones": zones if zones is not None else {"holding": text}, "text": text}


@pytest.fixture
def workspace(tmp_path, write_config, monkeypatch):
    paths = {k: str(tmp_path / f"{k}.out") for k in ("judgments", "doc_statutes", "citations", "doc_health", "statute_map")}
    paths["index_dir"] = str(tmp_path / "index")
    cfg_path = write_config(tmp_path / "config.yaml", {"paths": paths})
    monkeypatch.setenv("LEXSHIFT_CONFIG", str(cfg_path))
    from common.config import load_config

    return types.SimpleNamespace(dir=tmp_path, paths=paths, cfg=load_config())


def levels(rep, module, check_contains):
    return [f.level for f in rep.items if f.module == module and check_contains in f.check]


def test_coram_reader_handles_both_printed_shapes_and_authorship_notes():
    assert coram_count("[C.T. Ravikumar* and Sanjay Kumar, JJ.]") == 2
    assert coram_count("[DIPAK MISRA, CJI, R.F. NARIMAN AND INDU MALHOTRA, JJ.]") == 3
    assert coram_count("[Abhay S. Oka, Ahsanuddin Amanullah* and Augustine George Masih, JJ.]") == 3
    assert coram_count("no coram line") is None


def test_missing_artefacts_are_info_not_failure(workspace):
    rep = Report()
    assert check_m1_data(rep, workspace.cfg) == []
    check_m2_data(rep, workspace.cfg, [])
    check_m3_data(rep, workspace.cfg, [])
    assert {f.level for f in rep.items} <= {"INFO", "WARN"}  # nothing built yet is not a contract violation


def test_a_conforming_corpus_passes_the_m1_data_checks(workspace):
    docs = [judgment(f"{2000 + i}_1_{i}_{i + 5}_EN", date=f"{2000 + i}-03-01") for i in range(6)]
    write_jsonl(workspace.paths["judgments"], docs)
    rep = Report()
    check_m1_data(rep, workspace.cfg)
    assert [f for f in rep.items if f.level == "FAIL"] == []
    assert levels(rep, "M1", "matches the Judgment contract") == ["PASS"]
    assert levels(rep, "M1", "bench_size agrees") == ["PASS"]


def test_each_contract_breach_in_the_corpus_is_reported_to_m1(workspace):
    docs = [judgment("2025_1_1_11_EN", date="02 January 2025", bench=2),  # non-ISO date
            judgment("2025_1_12_20_EN", bench=0),  # bench 0 although the coram line names two judges
            judgment("2025_1_21_30_EN", bench=2,
                     text="[Abhay Oka, Bela Trivedi and Chandra Dev, JJ.] The appeal is allowed. Section 302 IPC."),  # 3 judges as 2
            judgment("not-a-pattern", reporter=()),
            judgment("2025_1_1_11_EN")]  # duplicate id
    write_jsonl(workspace.paths["judgments"], docs)
    rep = Report()
    check_m1_data(rep, workspace.cfg)
    failed = {f.check for f in rep.items if f.level == "FAIL"}
    assert "judgments.jsonl matches the Judgment contract" in failed
    assert "doc_ids are unique" in failed
    assert "bench_size is a positive int or None" in failed
    assert "benches of 3 or more judges are recorded" in failed
    assert levels(rep, "M1", "doc_id follows") == ["WARN"] and levels(rep, "M1", "reporter_citations filled") == ["WARN"]
    detail = next(f.detail for f in rep.items if f.check == "judgments.jsonl matches the Judgment contract")
    assert "ISO date" in detail


def test_control_characters_and_a_single_year_are_flagged(workspace):
    docs = [judgment(f"2025_1_{i}_{i + 2}_EN", text=f"[A and B, JJ.] The appeal\x08 is allowed. IPC {i}") for i in range(4)]
    write_jsonl(workspace.paths["judgments"], docs)
    rep = Report()
    check_m1_data(rep, workspace.cfg)
    assert levels(rep, "M1", "free of control characters") == ["WARN"]
    assert levels(rep, "M1", "spans more than one year") == ["WARN"]


def test_the_index_and_the_corpus_must_cover_the_same_documents(workspace):
    docs = [judgment(f"2025_1_{i}_{i + 2}_EN") for i in range(3)]
    write_jsonl(workspace.paths["judgments"], docs)
    write_jsonl(workspace.dir / "index" / "tokenized_judgments.jsonl", [{"doc_id": d["doc_id"]} for d in docs[:2]])
    rep = Report()
    check_m1_data(rep, workspace.cfg)
    assert levels(rep, "M1", "index and judgments.jsonl cover") == ["FAIL"]


def test_m2_data_checks_catch_missing_coverage_empty_offence_ids_and_paragraph_numbers(workspace):
    docs = [judgment("D1", text="[A and B, JJ.] Section 302 IPC applies. The order under IPC. 16. Thus we hold."), judgment("D2")]
    write_jsonl(workspace.paths["judgments"], docs)
    refs = [{"act": "IPC", "section": "302", "offence_id": None, "count": 1, "zone": None},
            {"act": "IPC", "section": "16", "offence_id": None, "count": 1, "zone": None}]  # 16 is a paragraph number
    write_jsonl(workspace.paths["doc_statutes"], [{"doc_id": "D1", "refs": refs}])  # D2 missing
    (workspace.dir / "statute_map.out").write_text(
        "old_act,old_section,new_act,new_section,relation,weight,source,note\nIPC,302,BNS,103,equivalent,1.0,a blog,\n", encoding="utf-8")
    rep = Report()
    check_m2_data(rep, workspace.cfg, docs)
    assert levels(rep, "M2", "covers every judgment") == ["FAIL"]
    assert levels(rep, "M2", "offence_id is filled") == ["WARN"]
    assert levels(rep, "M2", "not paragraph numbers") == ["FAIL"]
    assert levels(rep, "M2", "planned 20-40") == ["WARN"]


def install_fake_parser(monkeypatch, parser):
    mod = types.ModuleType("m2_statute")
    mod.parse_query = parser
    monkeypatch.setitem(sys.modules, "m2_statute", mod)


def test_m2_api_check_passes_a_parser_that_reads_every_required_form(monkeypatch):
    from common.schema import QueryStatutes, StatuteRef

    answers = dict(conformance.REQUIRED_FORMS)

    def parser(query, offence_date=None):
        if offence_date == "31/12/2024":
            raise ValueError("bad date")
        refs = [StatuteRef(act=a, section=s) for a, s in sorted(answers.get(query, set()))]
        if query == "section 103":
            refs = [StatuteRef(act="BNS" if offence_date >= "2024-07-01" else "IPC", section="103")]
        return QueryStatutes(query=query, offence_date=offence_date, governing_act=None, refs=refs)

    install_fake_parser(monkeypatch, parser)
    rep = Report()
    check_m2_api(rep)
    assert [f for f in rep.items if f.level in ("FAIL", "WARN")] == []


def test_m2_api_check_reports_each_failing_form_and_the_unresolved_bare_number(monkeypatch):
    from common.schema import QueryStatutes, StatuteRef

    def weak(query, offence_date=None):
        refs = [StatuteRef(act="IPC", section="302")] if query == "IPC 302" else (
            [StatuteRef(act="UNKNOWN", section="302")] if "302" in query else [])
        return QueryStatutes(query=query, offence_date=offence_date, governing_act=None, refs=refs)

    install_fake_parser(monkeypatch, weak)
    rep = Report()
    check_m2_api(rep)
    forms = next(f for f in rep.items if "statute forms" in f.check)
    assert forms.level == "FAIL" and "u/s 302/34 IPC" in forms.detail and "Sections 302 and 307" in forms.detail
    assert levels(rep, "M2", "collision resolution") == ["FAIL"]
    assert levels(rep, "M2", "malformed offence date") == ["WARN"]  # the weak parser accepts '31/12/2024'


def test_m3_data_checks_cover_contract_coverage_and_the_bench_check(workspace):
    docs = [judgment("A_EN"), judgment("B_EN")]
    cit = {"citing_doc": "B_EN", "cited_doc": "A_EN", "cited_raw": "x", "window": "w", "is_appeal_history": False, "label": "overruled",
           "confidence": 0.9, "citing_bench": None, "cited_bench": 2, "valid_negative": False}
    unresolved = {**cit, "cited_doc": None, "label": "neutral", "confidence": 0.0}
    write_jsonl(workspace.paths["citations"], [cit, unresolved])
    write_jsonl(workspace.paths["doc_health"], [{"doc_id": "A_EN", "health": 1.0, "authority": 0.5, "evidence": []}])  # B_EN missing
    rep = Report()
    check_m3_data(rep, workspace.cfg, docs)
    assert levels(rep, "M3", "Citation contract") == ["PASS"] and levels(rep, "M3", "covers exactly the corpus") == ["FAIL"]
    assert levels(rep, "M3", "unknown bench") == ["WARN"]  # the only negative has an unknown citing bench
    assert any("resolution rate" in f.check and "1/2" in f.detail for f in rep.items)


def test_run_renders_only_the_requested_module(workspace):
    write_jsonl(workspace.paths["judgments"], [judgment("2025_1_1_2_EN", date="02 January 2025")])
    text = render(run({"m3"}))
    assert "== M3 ==" in text and "== M1 ==" not in text and "== M2 ==" not in text  # the corpus is read, but not reported as M1's


def test_the_json_form_is_machine_readable_and_the_exit_code_follows_the_failures(workspace, capsys):
    write_jsonl(workspace.paths["judgments"], [judgment("2025_1_1_2_EN")])
    assert conformance.main(["--module", "m3", "--json"]) == 0
    assert json.loads(capsys.readouterr().out) == [
        {"module": "M3", "level": "INFO", "check": "citations.jsonl and doc_health.jsonl", "detail": "not built yet"}]
    rep = Report()
    rep.add("M1", "FAIL", "x")
    assert rep.count("FAIL") == 1 and render(rep).splitlines()[-1].startswith("1 FAIL")
