"""End to end on a four-judgment corpus in a temporary directory, with a fake LLM in place of Gemini."""

import json

import pytest
import yaml

from common import config as common_config
from common import contracts
from common.config import DEFAULT_CONFIG
from common.io import read_jsonl, write_jsonl


def judgment(doc_id, title, date, bench, text, cites=()):
    return {"doc_id": doc_id, "title": title, "date": date, "bench_size": bench, "judges": [], "reporter_citations": list(cites), "zones": {}, "text": text}


KOUSHAL = judgment(
    "2013_17_116_254", "SURESH KUMAR KOUSHAL AND ANOTHER versus NAZ FOUNDATION AND OTHERS", "2013-12-11", 2,
    "The High Court in Naz Foundation v. Govt. of NCT of Delhi, 2010 Cri LJ 94 was set aside. "
    "We hold that Section 377 IPC does not suffer from the vice of unconstitutionality.",
    ["[2013] 17 S.C.R. 116"],
)
NAVTEJ = judgment(
    "2018_7_379_746", "NAVTEJ SINGH JOHAR & ORS. versus UNION OF INDIA", "2018-09-06", 5,
    "The petitioners relied on Suresh Kumar Koushal & Anr. v. Naz Foundation & Ors. (2014) 1 SCC 1 : [2013] 17 SCR 116 "
    "in their submissions. Many other points were urged. For all these reasons, Suresh Kumar Koushal (supra) needs to be, "
    "and is hereby, overruled. We follow Common Cause v. Union of India (2018) 5 SCC 1 on dignity.",
    ["[2018] 7 S.C.R. 379"],
)
COMMON_CAUSE = judgment("2018_5_1_100", "COMMON CAUSE versus UNION OF INDIA & ORS.", "2018-03-09", 5, "Dignity in dying is a facet of Article 21.", ["[2018] 5 S.C.R. 1"])
SMALL = judgment(
    "2019_1_1_9", "A. SMALL BENCH versus STATE OF GOA", "2019-01-01", 2,
    "With respect, Navtej Singh Johar & Ors. v. Union of India (2018) 10 SCC 1 : [2018] 7 SCR 379 is overruled by us. "
    "Nothing else arises.",
)


class FakeLLM:
    """Labels a window `overruled` if the word follows the target closely, `followed` if "follow" just precedes it."""

    def __call__(self, prompt):
        out = []
        for chunk in prompt.split("Window ")[1:]:
            i, body = chunk.split(":\n", 1)
            after = body.split("]]", 1)[1][:60] if "]]" in body else ""
            before = body.split("[[", 1)[0][-30:]
            label = "overruled" if "overruled" in after else ("followed" if "follow" in before.lower() else "neutral")
            out.append({"id": int(i), "label": label, "confidence": 0.95})
        return json.dumps(out)


@pytest.fixture()
def project(tmp_path, monkeypatch):
    cfg = yaml.safe_load(open(DEFAULT_CONFIG, encoding="utf-8"))
    for key in ("judgments", "citations", "doc_health", "doc_statutes", "treatment_gold"):
        cfg["paths"][key] = str(tmp_path / f"{key}.out")
    m3 = cfg["m3_treatment"]
    m3["mentions"] = str(tmp_path / "mentions.jsonl")
    m3["reports_dir"] = str(tmp_path / "reports")
    m3["labelling_dir"] = str(tmp_path / "labelling")
    m3["llm"]["cache"] = str(tmp_path / "llm.jsonl")
    m3["llm"]["min_interval_s"] = 0
    m3["resolver"].update(min_stop_df=3, max_token_df=0.5)
    path = tmp_path / "config.yaml"
    path.write_text(yaml.safe_dump(cfg), encoding="utf-8")
    monkeypatch.setenv("LEXSHIFT_CONFIG", str(path))
    common_config._load.cache_clear()
    write_jsonl(cfg["paths"]["judgments"], [KOUSHAL, NAVTEJ, COMMON_CAUSE, SMALL])
    from m3_treatment import scores

    scores._table.cache_clear()
    yield cfg
    common_config._load.cache_clear()
    scores._table.cache_clear()


def test_pipeline_end_to_end(project):
    from m3_treatment import pipeline
    from m3_treatment.scores import authority, health

    rep = pipeline.run_extract()
    assert rep["resolved"] >= 3 and rep["appeal_history"] >= 1
    mentions = pipeline.load_mentions()
    naz_hc = [m for m in mentions if "Govt. of NCT" in m["cited_raw"]]
    assert naz_hc and all(m["is_appeal_history"] for m in naz_hc)  # "set aside" High Court judgment: a reversal

    with pytest.raises(RuntimeError, match="label-llm"):
        pipeline.run_citations("llm")  # no silent fallback when labels are missing
    info = pipeline.run_label_llm(dry_run=True)
    assert info["to_label"] > 0 and "labelled" not in info
    info = pipeline.run_label_llm(call=FakeLLM())
    assert info["labelled"] == info["to_label"]

    out = pipeline.run_citations("llm")
    assert out["valid_negatives"] >= 1
    rows = list(read_jsonl(project["paths"]["citations"]))
    small = [r for r in rows if r["citing_doc"] == "2019_1_1_9" and r["cited_doc"] == "2018_7_379_746"]
    assert small and small[0]["label"] == "overruled" and not small[0]["valid_negative"]  # 2 judges cannot overrule 5

    pipeline.run_health()
    h, ev = health("2013_17_116_254")
    assert h == pytest.approx(0.1)
    assert ev[0]["citing_doc"] == "2018_7_379_746" and ev[0]["label"] == "overruled" and "overruled" in ev[0]["sentence"]
    assert contracts.check_health((h, ev)) == []
    assert health("2018_7_379_746")[0] == 1.0  # the invalid smaller-bench "overruling" does not count
    assert health("2018_5_1_100")[0] == 1.0
    for d in ("2013_17_116_254", "2018_7_379_746", "2018_5_1_100", "2019_1_1_9"):
        assert contracts.check_authority(authority(d)) == []
    assert authority("2018_5_1_100") > authority("2019_1_1_9")  # cited and followed vs never cited
    with pytest.raises(KeyError):
        health("NOT-IN-CORPUS")


def test_point_level_health_uses_offence_ids(project):
    from m3_treatment import pipeline
    from m3_treatment.scores import health

    write_jsonl(project["paths"]["doc_statutes"], [{"doc_id": "2018_7_379_746", "refs": [{"act": "IPC", "section": "377", "offence_id": "OFF_UNNATURAL", "count": 3, "zone": None}]}])
    pipeline.run_extract()
    pipeline.run_label_llm(call=FakeLLM())
    pipeline.run_citations("llm")
    pipeline.run_health()
    assert health("2013_17_116_254", ["OFF_UNNATURAL"])[0] == pytest.approx(0.1)
    assert health("2013_17_116_254", ["OFF_MURDER"])[0] == 1.0  # the overruling was about a different offence
    assert health("2013_17_116_254")[0] == pytest.approx(0.1)


def test_scores_build_requires_the_build_verb(capsys):
    from m3_treatment.scores import main

    assert main([]) == 2


def test_zero_shot_labels_are_not_reused_once_few_shot_examples_exist(project):
    """Regression: the cache key ignored the few-shot examples, so labels made before the gold set existed stayed
    zero-shot forever while the F1 table called them few-shot."""
    from common.io import write_delimited
    from m3_treatment import pipeline

    pipeline.run_extract()
    first = pipeline.run_label_llm(call=FakeLLM())
    assert first["prompt"] == "zero-shot" and first["labelled"] > 0

    # the gold set arrives: label every distinct window by hand (here: the same rule as the fake model)
    windows = list(dict.fromkeys(m["marked_window"] for m in pipeline.load_mentions() if not m["is_self"]))
    rule = lambda w: "overruled" if "overruled" in w.split("]]", 1)[1][:60] else "neutral"  # noqa: E731
    gold_rows = [{"window_id": f"w{i}", "window": w, "gold_label": rule(w), "labeller": "L1"} for i, w in enumerate(windows)]
    gold_path = project["paths"]["treatment_gold"]
    write_delimited(gold_path, ("window_id", "window", "gold_label", "labeller"), gold_rows[:-1])

    dry = pipeline.run_label_llm(dry_run=True)
    assert dry["prompt"].endswith(")") and "shot" in dry["prompt"] and dry["prompt"] != "zero-shot"
    assert dry["already_cached"] == 0  # nothing labelled zero-shot is reused under the few-shot prompt

    pool = pipeline.fewshot_pool()
    assert pool and (pipeline._pool_path()).exists()
    write_delimited(gold_path, ("window_id", "window", "gold_label", "labeller"), gold_rows)  # more gold later
    assert pipeline.fewshot_pool() == pool  # the frozen pool does not move, so the cache stays valid

    seen = []

    class Recording(FakeLLM):
        def __call__(self, prompt):
            seen.append("Labelled examples:" in prompt)
            return super().__call__(prompt)

    pipeline.run_label_llm(call=Recording())
    assert seen and all(seen)  # every request carried the examples
    ev = pipeline.run_evaluate()
    assert ev["prompt"] == f"{len(pool)}-shot" and "skipped" not in ev["llm"]
    assert f"LLM {len(pool)}-shot" in ev["markdown"]
    assert pipeline.run_citations("llm")["records"] > 0


def test_missing_bench_sizes_stop_the_build_loudly(project, capsys):
    """Regression: without bench sizes no overruling could lower a score, and nothing said so."""
    from m3_treatment import pipeline

    no_bench = [{**j, "bench_size": None} for j in (KOUSHAL, NAVTEJ, COMMON_CAUSE, SMALL)]  # no coram line in these texts
    write_jsonl(project["paths"]["judgments"], no_bench)
    assert pipeline.main(["extract"]) == 1
    err = capsys.readouterr().err
    assert "[ERROR]" in err and "bench" in err
    from m3_treatment.citations import main as citations_main

    assert citations_main(["build"]) == 1  # the build stops instead of writing scores that cannot work

    # run the remaining steps by hand anyway: health() says why nothing was lowered
    pipeline.run_label_llm(call=FakeLLM())
    pipeline.run_citations("llm")
    rep = pipeline.run_health()
    assert rep["lowered_health"] == {} and rep["negatives_not_counted"].get("unknown bench")
    assert rep["warnings"] and "bench" in rep["warnings"][0]
    assert "M1 data checks" in (pipeline._report_dir() / "resolution.md").read_text(encoding="utf-8")
