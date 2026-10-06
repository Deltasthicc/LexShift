import json

import pytest

from app import cli
from app.docmeta import build_doc_meta, describe, load_doc_meta
from common.io import write_jsonl


def run(argv, providers):
    return cli.run(cli.parse_args(argv), providers)


def test_stub_run_is_labelled_on_screen(make_providers, capsys):
    p = make_providers(stubbed={"health", "authority"})  # provider groups; they surface as the signals health, auth
    assert run(["BNS 103", "--offence-date", "2025-01-10", "-k", "4"], p) == 0
    out = capsys.readouterr().out
    assert "STUB MODE: health, auth" in out and "NOT a result" in out
    assert "not legal\nadvice" in out  # the not-legal-advice note is always printed


def test_real_run_has_no_stub_banner_and_shows_breakdown_and_evidence(make_providers, capsys):
    assert run(["murder", "-k", "4"], make_providers()) == 0
    out = capsys.readouterr().out
    assert "STUB" not in out
    assert " 1. B   final 0.875" in out
    assert "rel    [" in out and "BM25 9.50" in out
    assert 'evidence: overruled in Z\n        "placeholder sentence A"' in out
    assert "overruled per Z" in out
    assert "bad law" not in out.lower() and "dead law" not in out.lower()


def test_config_choice_changes_what_is_shown(make_providers, capsys):
    assert run(["murder", "--config", "b0", "-k", "2"], make_providers()) == 0
    out = capsys.readouterr().out
    assert "config b0" in out and "health" not in out.split("query:")[1].split("These are treatment")[0]
    assert " 1. A   final 1.000" in out


def test_verbose_shows_the_parse_weights_and_raw_signals(make_providers, capsys):
    assert run(["BNS 103", "--verbose", "-k", "2"], make_providers(offence_ids=["OFF_MURDER"])) == 0
    out = capsys.readouterr().out
    assert "weights from starting weights (untuned placeholders)" in out
    assert "IPC 302 -> OFF_MURDER" in out and "raw signals before normalisation" in out


def test_json_output_is_machine_readable_and_flags_stubs(make_providers, capsys):
    assert run(["murder", "--json", "-k", "3"], make_providers(stubbed={"health"})) == 0
    captured = capsys.readouterr()
    data = json.loads(captured.out)
    assert [d["doc_id"] for d in data] == ["B", "A", "C"]
    assert data[0]["stubbed"] == ["health"] and set(data[0]) >= {"final", "rel", "cont", "health", "auth", "explanation"}
    assert "STUB MODE" in captured.err  # the banner goes to stderr so stdout stays valid JSON


def test_bad_input_and_unbuilt_modules_are_clean_failures(make_providers, capsys):
    assert run(["murder", "--offence-date", "yesterday"], make_providers()) == 2
    assert "Invalid input" in capsys.readouterr().err
    assert run(["murder", "--config", "b9"], make_providers()) == 2
    from common.providers import Providers

    good = make_providers()

    def unbuilt(query, k=100, filters=None):
        raise NotImplementedError("M1: search() is not implemented yet.")

    broken = Providers(unbuilt, good.parse_query, good.continuity, good.health, good.authority, frozenset())
    assert run(["murder"], broken) == 2
    assert "not built yet" in capsys.readouterr().err


def test_text_from_other_modules_cannot_break_the_layout(make_providers, scenario, capsys):
    # an explanation containing the piece separator and a newline, and an evidence label/citation with separators too
    scenario["B"]["why"] = "IPC 302 | BNS 103 split\nacross two lines"
    scenario["A"]["evidence"] = [{"citing_doc": "Z | Y", "label": "overruled", "sentence": "s"}]
    assert run(["murder", "-k", "4"], make_providers(scenario)) == 0
    out = capsys.readouterr().out
    assert "IPC 302 / BNS 103 split across two lines" in out and "overruled per Z / Y" in out
    assert "split\nacross" not in out
    # every line under a result is either a signal line or an evidence line, never a mangled fragment
    for line in out.splitlines():
        if line.startswith("      ") and not line.startswith("        ") and "evidence:" not in line:
            assert line.split()[0] in ("rel", "cont", "health", "auth"), line  # evidence passages are indented further


def test_evidence_is_wrapped_in_full_and_shows_confidence_and_bench_when_the_module_gives_them():
    sentence = ("Alpha " * 40 + "is hereby overruled. " + "Omega " * 40).strip()
    ev = {"citing_doc": "Z", "label": "overruled", "sentence": sentence, "confidence": 0.9312, "citing_bench": 5}
    lines = cli.render_evidence(ev, width=60)
    assert lines[0] == "      evidence: overruled in Z (confidence 0.93, 5-judge bench)"
    body = " ".join(line.strip() for line in lines[1:])
    assert body.startswith('"Alpha') and body.endswith('Omega"') and "is hereby overruled." in body  # nothing cut
    assert all(len(line) <= 60 for line in lines[1:])
    short = cli.render_evidence(ev, width=60, limit=50)
    assert " ".join(x.strip() for x in short[1:]).endswith('..."')
    plain = cli.render_evidence({"citing_doc": "Y", "label": "doubted", "sentence": "s"})
    assert plain[0] == "      evidence: doubted in Y"  # the contract's three keys alone are enough


def test_a_missing_artefact_from_a_provider_is_a_clear_message(make_providers, capsys):
    from common.providers import Providers

    good = make_providers()

    def health_without_its_file(doc_id, offence_ids=None):
        raise FileNotFoundError("doc_health.jsonl not found; build it with `python -m m3_treatment.scores build`")

    broken = Providers(good.search, good.parse_query, good.continuity, health_without_its_file, good.authority, frozenset())
    assert run(["murder"], broken) == 2
    err = capsys.readouterr().err
    assert "could not find its data" in err and "doc_health.jsonl not found" in err and "Traceback" not in err


def test_render_survives_a_piece_that_is_not_a_signal_line():
    from common.schema import Result

    r = Result("X", 0.5, 0.5, 0.5, 0.5, 0.5, "rel 0.50 x 0.50 = 0.250 | something else entirely")
    out = cli.render([r], {})
    assert "rel    [" in out and "      something else entirely" in out


def test_verbose_with_an_unbuilt_statute_module_does_not_crash(make_providers, capsys):
    from common.providers import Providers

    good = make_providers()

    def unbuilt(query, offence_date=None):
        raise NotImplementedError("M2: parse_query() is not implemented yet.")

    broken = Providers(good.search, unbuilt, good.continuity, good.health, good.authority, frozenset())
    assert run(["murder", "--config", "b0", "--verbose", "-k", "2"], broken) == 0
    assert "query statutes: not used by this config" in capsys.readouterr().out
    assert run(["murder", "--config", "full", "--verbose", "-k", "2"], broken) == 2  # full genuinely needs M2
    assert "not built yet" in capsys.readouterr().err


def test_a_bug_in_a_module_reads_as_one_clear_line_and_debug_shows_the_traceback(make_providers, capsys):
    from common.providers import Providers

    good = make_providers()

    def buggy_search(query, k=100, filters=None):
        return [][3]  # an IndexError from inside the module, like a parser reading past the end of its tokens

    broken = Providers(buggy_search, good.parse_query, good.continuity, good.health, good.authority, frozenset())
    assert run(["murder AND"], broken) == 3
    err = capsys.readouterr().err
    assert "Unexpected error in a module (IndexError)" in err and "--debug" in err and "Traceback" not in err
    with pytest.raises(IndexError):
        run(["murder AND", "--debug"], broken)


def test_contract_violation_is_reported(make_providers, scenario, capsys):
    scenario["A"]["health"] = 2.0
    assert run(["murder"], make_providers(scenario)) == 3
    assert "breaks its contract" in capsys.readouterr().err


def test_no_results_message(make_providers, capsys):
    assert run(["murder"], make_providers({})) == 0
    assert "No results." in capsys.readouterr().out


# --------------------------------------------------------------------- docmeta
def test_doc_meta_is_derived_without_the_full_text_and_shown(tmp_path, write_config, monkeypatch, make_providers, capsys):
    cfg = write_config(tmp_path / "c.yaml", {"paths": {"judgments": str(tmp_path / "j.jsonl"), "doc_meta": str(tmp_path / "m.jsonl")}})
    monkeypatch.setenv("LEXSHIFT_CONFIG", str(cfg))
    write_jsonl(tmp_path / "j.jsonl", [
        {"doc_id": "B", "title": "State v. Example", "date": "2019-03-04", "bench_size": 5, "text": "very long text " * 100},
        {"doc_id": "A", "title": "Another v. Case", "date": "2001-01-01", "bench_size": None, "text": "t"},
    ])
    assert build_doc_meta() == 2
    meta = load_doc_meta()
    assert set(meta["B"]) == {"doc_id", "title", "date", "bench_size"}  # no text
    assert describe(meta["B"]) == "State v. Example (2019-03-04, 5-judge bench)"
    assert describe(meta["A"]) == "Another v. Case (2001-01-01)"
    assert run(["murder", "-k", "2"], make_providers()) == 0
    assert "State v. Example (2019-03-04, 5-judge bench)" in capsys.readouterr().out


def test_doc_meta_absent_is_fine_and_missing_corpus_is_a_clear_error(tmp_path, write_config, monkeypatch):
    cfg = write_config(tmp_path / "c.yaml", {"paths": {"judgments": str(tmp_path / "none.jsonl"), "doc_meta": str(tmp_path / "none_meta.jsonl")}})
    monkeypatch.setenv("LEXSHIFT_CONFIG", str(cfg))
    assert load_doc_meta() == {}
    with pytest.raises(FileNotFoundError, match="M1 produces"):
        build_doc_meta()
    assert describe(None) == "" and describe({"doc_id": "x"}) == ""
