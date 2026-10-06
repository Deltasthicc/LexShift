"""M4 against M3's REAL health() and authority().

A small synthetic corpus (fictional parties; the judgment ids follow the dataset's `<year>_<vol>_<page>_<n>` pattern that M3's
resolver reads) goes through M3's actual pipeline (extract, label with a fake LLM, citations, health) in a temporary directory.
M4's rank() and CLI are then driven by M3's real lookup functions, with M1 and M2 replaced by small fixtures, to check that

  * M3's output satisfies the contracts M4 enforces at runtime,
  * an overruled precedent really drops under the full system and its evidence reaches the screen,
  * the stub flags cover exactly the signals that are still stubs.

The fake LLM stands in for Gemini: the pipeline is real, only the label source is a fixture.
"""

import json

import pytest
import yaml

from app import cli
from common import config as common_config
from common import contracts
from common.config import DEFAULT_CONFIG
from common.io import write_jsonl
from common.providers import Providers
from common.schema import Hit, QueryStatutes
from m3_treatment import pipeline, scores
from m4_rank.rank import rank

OLD, NEW, GOOD, LONER, SMALLER = "2013_1_100_10", "2018_9_300_20", "2015_2_200_15", "2016_3_50_30", "2019_4_60_40"


def judgment(doc_id, title, date, bench, text, cites):
    return {"doc_id": doc_id, "title": title, "date": date, "bench_size": bench, "judges": [], "reporter_citations": cites,
            "zones": {}, "text": text}


CORPUS = [
    judgment(OLD, "ALPHA PETITIONER versus STATE OF GOA", "2013-05-01", 2,
             "The appellant relied on a settled line of authority. The appeal is dismissed.", ["[2013] 1 S.C.R. 100"]),
    judgment(NEW, "BETA PETITIONER versus UNION OF INDIA", "2018-09-06", 5,
             "Counsel relied on Alpha Petitioner v. State of Goa (2013) 1 SCC 1 : [2013] 1 SCR 100 in the submissions. "
             # a realistic judgment has long sentences: the sentence that does the overruling sits well past character 220
             "Several other points were urged before us at considerable length by learned counsel appearing for the petitioners, "
             "by the learned Additional Solicitor General appearing for the Union, and by the interveners, each of whom took us "
             "through the legislative history, the earlier decisions of this Court and the comparative material placed on record. "
             "For all these reasons, Alpha Petitioner (supra) needs to be, and is hereby, overruled. "
             "We follow Gamma Respondent v. State of Kerala (2015) 2 SCC 2 : [2015] 2 SCR 200 on this point.",
             ["[2018] 9 S.C.R. 300"]),
    judgment(GOOD, "GAMMA RESPONDENT versus STATE OF KERALA", "2015-03-01", 3,
             "The principle is settled and the appeal is allowed.", ["[2015] 2 S.C.R. 200"]),
    judgment(LONER, "DELTA PARTY versus STATE OF ASSAM", "2016-02-02", 3, "Nothing here cites an earlier case.", ["[2016] 3 S.C.R. 50"]),
    judgment(SMALLER, "EPSILON LTD versus STATE OF GOA", "2019-01-01", 2,
             "With respect, Beta Petitioner v. Union of India (2018) 3 SCC 3 : [2018] 9 SCR 300 is overruled by us.",
             ["[2019] 4 S.C.R. 60"]),
]


class FakeLLM:
    """Stands in for Gemini: `overruled` if the word follows the target closely, `followed` if "follow" just precedes it."""

    def __call__(self, prompt):
        out = []
        for chunk in prompt.split("Window ")[1:]:
            i, body = chunk.split(":\n", 1)
            after = body.split("]]", 1)[1][:60] if "]]" in body else ""
            before = body.split("[[", 1)[0][-30:]
            label = "overruled" if "overruled" in after else ("followed" if "follow" in before.lower() else "neutral")
            out.append({"id": int(i), "label": label, "confidence": 0.95})
        return json.dumps(out)


@pytest.fixture
def m3_artefacts(tmp_path, monkeypatch):
    """Run M3's real pipeline on CORPUS in a temp dir; leave config pointing at the files it wrote."""
    cfg = yaml.safe_load(open(DEFAULT_CONFIG, encoding="utf-8"))
    for key in ("judgments", "citations", "doc_health", "doc_statutes", "treatment_gold"):
        cfg["paths"][key] = str(tmp_path / f"{key}.out")
    m3 = cfg["m3_treatment"]
    m3["mentions"], m3["reports_dir"] = str(tmp_path / "mentions.jsonl"), str(tmp_path / "reports")
    m3["labelling_dir"], m3["llm"]["cache"], m3["llm"]["min_interval_s"] = str(tmp_path / "labelling"), str(tmp_path / "llm.jsonl"), 0
    m3["resolver"].update(min_stop_df=3, max_token_df=0.5)  # a five-judgment corpus has no meaningful document frequencies
    cfg["ranking"]["use_tuned"] = False
    path = tmp_path / "config.yaml"
    path.write_text(yaml.safe_dump(cfg), encoding="utf-8")
    monkeypatch.setenv("LEXSHIFT_CONFIG", str(path))
    common_config._load.cache_clear()
    scores._table.cache_clear()
    write_jsonl(cfg["paths"]["judgments"], CORPUS)
    pipeline.run_extract()
    pipeline.run_label_llm(call=FakeLLM())
    pipeline.run_citations("llm")
    pipeline.run_health()
    yield cfg
    common_config._load.cache_clear()
    scores._table.cache_clear()


def providers_with_real_m3(order=(OLD, GOOD, NEW, LONER), stubbed=frozenset({"search", "statute"})):
    """M1 and M2 are fixtures (search ranks OLD first by text); health and authority are M3's real functions."""
    rels = {d: 20.0 - 4 * i for i, d in enumerate(order)}

    def search(query, k=100, filters=None):
        return [Hit(d, rels[d]) for d in sorted(rels, key=lambda x: -rels[x])][:k]

    def parse_query(query, offence_date=None):
        return QueryStatutes(query=query, offence_date=offence_date, governing_act=None)

    return Providers(search, parse_query, lambda qs, d: (1.0, "fixture continuity"), scores.health, scores.authority, stubbed)


def ids(results):
    return [r.doc_id for r in results]


def test_m3_output_satisfies_the_contracts_m4_enforces(m3_artefacts):
    for d in (OLD, NEW, GOOD, LONER, SMALLER):
        assert contracts.check_health(scores.health(d)) == [], d
        assert contracts.check_health(scores.health(d, ["OFF_ANYTHING"])) == [], d
        assert contracts.check_authority(scores.authority(d)) == [], d


def test_an_overruled_precedent_drops_under_the_full_system_with_m3_evidence(m3_artefacts):
    p = providers_with_real_m3()
    b0 = rank("any query", None, k=4, config="b0", providers=p)
    full = rank("any query", None, k=4, config="full", providers=p)
    assert contracts.check_results(full, 4, {OLD, GOOD, NEW, LONER}) == []
    assert ids(b0)[0] == OLD  # the most relevant text ...
    assert ids(full).index(OLD) > ids(full).index(GOOD)  # ... is overtaken once its overruling counts
    old = next(r for r in full if r.doc_id == OLD)
    assert old.health == pytest.approx(0.1) and old.raw["health"] == pytest.approx(0.1)
    assert old.evidence and old.evidence[0]["citing_doc"] == NEW and old.evidence[0]["label"] == "overruled"
    assert "overruled" in old.evidence[0]["sentence"] and f"overruled per {NEW}" in old.explanation
    # M3 adds keys next to the contract's three; M4 passes them through untouched
    assert {"confidence", "citing_bench", "offence_ids"} <= set(old.evidence[0])
    assert next(r for r in full if r.doc_id == GOOD).health == 1.0


def test_a_smaller_bench_cannot_overrule_a_larger_one_end_to_end(m3_artefacts):
    # SMALLER (2 judges) says it overrules NEW (5 judges): M3's bench check must keep NEW healthy
    p = providers_with_real_m3(order=(NEW, OLD, GOOD, LONER))
    new = next(r for r in rank("q", None, k=4, config="full", providers=p) if r.doc_id == NEW)
    assert new.health == 1.0
    assert all(e["label"] != "overruled" for e in new.evidence)


def test_stub_flags_name_only_the_signals_that_are_still_stubs(m3_artefacts):
    p = providers_with_real_m3()
    full = rank("q", None, k=4, config="full", providers=p)
    assert full[0].stubbed == ["rel", "cont"]  # search and statute are fixtures; health and auth are real
    assert rank("q", None, k=4, config="b0", providers=p)[0].stubbed == ["rel"]


def test_point_level_health_flows_from_the_query_offences(m3_artefacts):
    # no doc_statutes.jsonl exists, so the overruling's offence ids are unknown and the penalty always applies
    p = providers_with_real_m3()
    assert scores.health(OLD, ["OFF_MURDER"])[0] == pytest.approx(0.1)
    full = rank("q", None, k=4, config="full", providers=p)
    assert next(r for r in full if r.doc_id == OLD).health == pytest.approx(0.1)


def overruled_block(out: str) -> str:
    """The text of the OVERRULED evidence item on screen (not any other item that happens to quote the same words)."""
    block = out.split(f"evidence: overruled in {NEW}", 1)[1]
    return block.split("\n      evidence:", 1)[0].split("\n\n", 1)[0]


def test_the_demo_shows_the_overruling_sentence_not_just_its_beginning(m3_artefacts, capsys):
    p = providers_with_real_m3()
    assert cli.run(cli.parse_args(["any query", "-k", "4"]), p) == 0
    out = capsys.readouterr().out
    assert f"evidence: overruled in {NEW} (confidence 0.95, 5-judge bench)" in out  # M3's extra keys are shown
    # M3's window is three sentences and the overruling one is the middle sentence, well past character 220:
    # it must be inside THIS item, not merely somewhere on screen
    assert "is hereby, overruled" in overruled_block(out)
    assert len(overruled_block(out)) > 400


def test_a_shorter_excerpt_is_available_on_request_and_marked_as_cut(m3_artefacts, capsys):
    assert cli.run(cli.parse_args(["any query", "-k", "4", "--evidence-chars", "120"]), providers_with_real_m3()) == 0
    block = overruled_block(capsys.readouterr().out)
    assert block.rstrip().endswith('..."') and "is hereby, overruled" not in block


def test_a_document_missing_from_doc_health_is_a_clear_message_not_a_traceback(m3_artefacts, capsys):
    p = providers_with_real_m3(order=(OLD, "9999_9_9_9", GOOD, NEW))
    assert cli.run(cli.parse_args(["q", "-k", "4"]), p) == 2
    err = capsys.readouterr().err
    assert "could not find its data" in err and "health(9999_9_9_9)" in err and "doc_health.jsonl" in err
    assert "Traceback" not in err


def test_the_other_tools_report_a_missing_artefact_the_same_way(m3_artefacts, tmp_path, capsys, monkeypatch):
    import eval.pool as pool
    import eval.run_ablation as run_ablation

    # treated as real providers here (the tools refuse stubs), so the missing id is what stops them
    p = providers_with_real_m3(order=(OLD, "9999_9_9_9", GOOD, NEW), stubbed=frozenset())
    for module in (pool, run_ablation):
        monkeypatch.setattr(module, "load_providers", lambda cfg=None: p)
    cfg = yaml.safe_load(open(common_config.config_path(), encoding="utf-8"))
    cfg["paths"]["queries"], cfg["paths"]["qrels"] = str(tmp_path / "q.jsonl"), str(tmp_path / "qrels.tsv")
    cfg["evaluation"]["judging_dir"] = str(tmp_path / "judging")
    (tmp_path / "q.jsonl").write_text(json.dumps({"qid": "d1", "text": "t", "offence_date": None, "split": "dev", "type": "A"}) + "\n")
    (tmp_path / "qrels.tsv").write_text("qid\tdoc_id\tgrade\nd1\t" + OLD + "\t2\n")
    path = tmp_path / "cfg2.yaml"
    path.write_text(yaml.safe_dump(cfg), encoding="utf-8")
    monkeypatch.setenv("LEXSHIFT_CONFIG", str(path))
    common_config._load.cache_clear()
    assert pool.main(["--round", "r1", "--depth", "4"]) == 2
    assert "could not find its data" in capsys.readouterr().out
    assert run_ablation.main(["--split", "dev", "--no-plots"]) == 2
    assert "could not find its data" in capsys.readouterr().out


def test_demo_path_never_imports_the_llm_client():
    import subprocess
    import sys

    code = ("import sys; import m3_treatment, m4_rank, app.cli; "
            "bad = [m for m in sys.modules if m.startswith(('google', 'sklearn', 'scipy'))]; print(bad); sys.exit(1 if bad else 0)")
    result = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True)
    assert result.returncode == 0, result.stdout + result.stderr
