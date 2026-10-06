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
