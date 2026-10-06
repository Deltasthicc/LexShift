"""End-to-end tests of `python -m eval.run_ablation` on a temporary workspace with fake providers.

Every query sees the same four candidates (tests/conftest.py SCENARIO) judged A=0 (overruled), B=2, C=1, D=1, so the hand
computed nDCG@10 are:   b0 order A B C D -> 0.6836     full order B A C D -> 0.9515
"""

import csv
import json
import math

import pytest
import yaml

import eval.run_ablation as run_ablation
from common.config import load_config

QUERIES = [
    {"qid": "dev1", "text": "murder", "offence_date": "2025-01-10", "split": "dev", "type": "A"},
    {"qid": "dev2", "text": "common intention", "offence_date": None, "split": "dev", "type": "C"},
    {"qid": "test1", "text": "BNS 103", "offence_date": "2025-01-10", "split": "test", "type": "A"},
    {"qid": "test2", "text": "overruled doctrine", "offence_date": None, "split": "test", "type": "C"},
    {"qid": "test3", "text": "no judgements yet", "offence_date": None, "split": "test", "type": "B"},
]
GRADES = {"A": 0, "B": 2, "C": 1, "D": 1}

NDCG_B0 = (3 / math.log2(3) + 1 / 2 + 1 / math.log2(5)) / (3 + 1 / math.log2(3) + 1 / 2)
NDCG_FULL = (3 + 0 + 1 / 2 + 1 / math.log2(5)) / (3 + 1 / math.log2(3) + 1 / 2)


@pytest.fixture
def workspace(tmp_path, write_config, monkeypatch, make_providers):
    (tmp_path / "queries.jsonl").write_text("\n".join(json.dumps(q) for q in QUERIES) + "\n", encoding="utf-8")
    rows = ["qid\tdoc_id\tgrade"] + [f"{q['qid']}\t{d}\t{g}" for q in QUERIES[:4] for d, g in GRADES.items()]
    (tmp_path / "qrels.tsv").write_text("\n".join(rows) + "\n", encoding="utf-8")
    (tmp_path / "gold.csv").write_text(
        "overruled_doc_id,overruling_doc_id,point,source,verified_by\nA,Z,adultery,the judgment,L1\n", encoding="utf-8")
    cfg_path = write_config(tmp_path / "config.yaml", {
        "paths": {"queries": str(tmp_path / "queries.jsonl"), "qrels": str(tmp_path / "qrels.tsv"),
                  "gold_overrulings": str(tmp_path / "gold.csv"), "results_dir": str(tmp_path / "results")},
        "ranking": {"use_tuned": True, "tuned_file": str(tmp_path / "weights_tuned.yaml")},
    })
    monkeypatch.setenv("LEXSHIFT_CONFIG", str(cfg_path))
    state = {"providers": make_providers()}
    monkeypatch.setattr(run_ablation, "load_providers", lambda cfg=None: state["providers"])
    state["dir"] = tmp_path
    state["results"] = tmp_path / "results"
    state["tuned"] = tmp_path / "weights_tuned.yaml"
    state["make_providers"] = make_providers
    return state


def read_csv(path):
    with open(path, encoding="utf-8", newline="") as fh:
        return list(csv.DictReader(fh))


def test_test_split_report_matches_hand_computed_numbers(workspace, capsys):
    assert run_ablation.main(["--split", "test", "--no-plots"]) == 0
    rows = {r["config"]: r for r in read_csv(workspace["results"] / "ablation_test.csv")}
    assert set(rows) == {"b0", "b1", "full"}
    assert rows["b0"]["n_queries"] == "2"  # test3 has no judgements and is skipped
    assert float(rows["b0"]["nDCG@10"]) == pytest.approx(NDCG_B0, abs=1e-3)
    assert float(rows["full"]["nDCG@10"]) == pytest.approx(NDCG_FULL, abs=1e-3)
    assert float(rows["full"]["nDCG@10"]) > float(rows["b0"]["nDCG@10"])
    assert float(rows["b0"]["harmful@10"]) == pytest.approx(0.1)  # A, the one known-overruled case, is in everyone's top 4
    md = (workspace["results"] / "ablation_test.md").read_text(encoding="utf-8")
    assert "2 queries" in md and "test3" in md and "starting weights (untuned placeholders)" in md
    assert "STUB RUN" not in md and "Difference from b0" in md and "nDCG@10 by query type" in md
    assert (workspace["results"] / "per_query_test.csv").exists()
    assert not list(workspace["results"].glob("stub_*"))
    assert "wrote" in capsys.readouterr().out


def test_stub_providers_are_refused_by_default(workspace, capsys):
    workspace["providers"] = workspace["make_providers"](stubbed={"health"})
    assert run_ablation.main(["--split", "test", "--no-plots"]) == 2
    assert "Refusing to run" in capsys.readouterr().out
    assert not workspace["results"].exists()


def test_search_stub_is_refused_even_for_the_bm25_baseline(workspace, capsys):
    workspace["providers"] = workspace["make_providers"](stubbed={"search"})
    assert run_ablation.main(["--configs", "b0", "--no-plots"]) == 2
    assert "search" in capsys.readouterr().out


def test_unused_stubs_do_not_block_a_baseline_only_run(workspace):
    workspace["providers"] = workspace["make_providers"](stubbed={"health"})
    assert run_ablation.main(["--configs", "b0,b1", "--no-plots"]) == 0
    assert not list(workspace["results"].glob("stub_*"))


def test_allow_stubs_labels_everything_as_stub_and_saves_no_weights(workspace):
    workspace["providers"] = workspace["make_providers"](stubbed={"health"})
    assert run_ablation.main(["--tune", "--split", "test", "--allow-stubs", "--no-plots"]) == 0
    names = {p.name for p in workspace["results"].iterdir()}
    assert {"stub_ablation_test.csv", "stub_ablation_test.md", "stub_per_query_test.csv"} <= names
    assert "ablation_test.csv" not in names
    assert "STUB RUN" in (workspace["results"] / "stub_ablation_test.md").read_text(encoding="utf-8")
    assert not workspace["tuned"].exists()


def test_tune_uses_dev_only_saves_weights_and_reports_test(workspace, monkeypatch):
    seen = []
    real = run_ablation.tune_config

    def spy(name, collected, queries, *a, **kw):
        seen.append((name, sorted(q.qid for q in queries), sorted(collected)))
        return real(name, collected, queries, *a, **kw)

    monkeypatch.setattr(run_ablation, "tune_config", spy)
    assert run_ablation.main(["--tune", "--split", "test", "--no-plots"]) == 0
    assert {n for n, _, _ in seen} == {"b1", "full"}
    assert all(qids == ["dev1", "dev2"] and keys == ["dev1", "dev2"] for _, qids, keys in seen)  # no test query touched
    saved = yaml.safe_load(workspace["tuned"].read_text(encoding="utf-8"))
    assert set(saved) == {"b1", "full"} and math.isclose(sum(saved["full"].values()), 1.0, abs_tol=1e-3)
    md = (workspace["results"] / "ablation_test.md").read_text(encoding="utf-8")
    assert "tuned on dev (this run)" in md and "optimistic" not in md
    # the saved weights are what a later plain run uses
    assert run_ablation.main(["--split", "test", "--no-plots"]) == 0
    md = (workspace["results"] / "ablation_test.md").read_text(encoding="utf-8")
    assert "b1: tuned on dev" in md and "full: tuned on dev" in md and "b0: starting weights" in md


def test_tune_alone_reports_dev_and_flags_it_as_optimistic(workspace):
    assert run_ablation.main(["--tune", "--no-plots"]) == 0
    md = (workspace["results"] / "ablation_dev.md").read_text(encoding="utf-8")
    assert "optimistic" in md and not (workspace["results"] / "ablation_test.md").exists()


def test_nothing_to_evaluate_is_reported_not_faked(workspace, capsys):
    (workspace["dir"] / "queries.jsonl").write_text("", encoding="utf-8")
    assert run_ablation.main(["--no-plots"]) == 2
    assert "No queries" in capsys.readouterr().out

    (workspace["dir"] / "queries.jsonl").write_text(json.dumps(QUERIES[0]) + "\n", encoding="utf-8")
    (workspace["dir"] / "qrels.tsv").write_text("qid\tdoc_id\tgrade\n", encoding="utf-8")
    assert run_ablation.main(["--no-plots"]) == 2
    assert "no judgements" in capsys.readouterr().out


def test_no_judged_queries_in_the_split(workspace, capsys):
    dev = [q for q in QUERIES if q["split"] == "dev"]
    (workspace["dir"] / "queries.jsonl").write_text("\n".join(json.dumps(q) for q in dev) + "\n", encoding="utf-8")
    rows = ["qid\tdoc_id\tgrade"] + [f"{q['qid']}\t{d}\t{g}" for q in dev for d, g in GRADES.items()]
    (workspace["dir"] / "qrels.tsv").write_text("\n".join(rows) + "\n", encoding="utf-8")
    assert run_ablation.main(["--split", "test", "--no-plots"]) == 2
    assert "No test queries" in capsys.readouterr().out


def test_unknown_config_and_bad_qrels_are_clean_errors(workspace, capsys):
    from m4_rank.weights import WeightsError

    with pytest.raises(WeightsError):
        run_ablation.main(["--configs", "b9"])
    (workspace["dir"] / "qrels.tsv").write_text("qid\tdoc_id\tgrade\nghost\tA\t2\n", encoding="utf-8")
    assert run_ablation.main(["--no-plots"]) == 2
    assert "unknown qid" in capsys.readouterr().out


def test_chart_is_written_when_matplotlib_is_available(workspace):
    pytest.importorskip("matplotlib")
    assert run_ablation.main(["--split", "test"]) == 0
    png = workspace["results"] / "ablation_test.png"
    assert png.exists() and png.stat().st_size > 1000


def test_shipped_config_uses_the_documented_evaluation_settings():
    ev = load_config()["evaluation"]
    assert ev["depth"] == 20 and ev["relevant_threshold"] == 1 and ev["gain"] == "exp"
