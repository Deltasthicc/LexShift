import math

import pytest
import yaml

from common.config import load_config
from common.schema import Query
from eval.loaders import EvalDataError, load_overruled, load_qrels, load_queries
from eval.tuning import TuningError, save_tuned, simplex_grid, tune_config
from m4_rank.rank import collect
from m4_rank.weights import SIGNALS, load_weights, normalise_weights


# --------------------------------------------------------------------- loaders
def test_missing_files_mean_nothing_yet(tmp_path):
    assert load_queries(tmp_path / "q.jsonl") == []
    assert load_qrels(tmp_path / "qrels.tsv") == {}
    assert load_overruled(tmp_path / "gold.csv") == set()


def write(path, text):
    path.write_text(text, encoding="utf-8", newline="\n")
    return path


def test_queries_load_and_reject_duplicates_and_bad_values(tmp_path):
    good = '{"qid": "q1", "text": "murder", "offence_date": "2025-01-10", "split": "dev", "type": "A"}\n'
    assert load_queries(write(tmp_path / "q.jsonl", good))[0].offence_date == "2025-01-10"
    with pytest.raises(EvalDataError, match="duplicate"):
        load_queries(write(tmp_path / "d.jsonl", good + good))
    with pytest.raises(EvalDataError):
        load_queries(write(tmp_path / "b.jsonl", good.replace('"dev"', '"validation"')))


def test_qrels_load_validate_and_reject_conflicts(tmp_path):
    header = "qid\tdoc_id\tgrade\n"
    ok = write(tmp_path / "ok.tsv", header + "q1\tA\t2\nq1\tB\t0\nq1\tA\t2\nq2\tC\t1\n")  # identical repeat is fine
    assert load_qrels(ok) == {"q1": {"A": 2, "B": 0}, "q2": {"C": 1}}
    with pytest.raises(EvalDataError, match="conflicting"):
        load_qrels(write(tmp_path / "c.tsv", header + "q1\tA\t2\nq1\tA\t1\n"))
    with pytest.raises(EvalDataError):
        load_qrels(write(tmp_path / "g.tsv", header + "q1\tA\t3\n"))
    with pytest.raises(EvalDataError):
        load_qrels(write(tmp_path / "n.tsv", header + "q1\tA\tmaybe\n"))
    with pytest.raises(EvalDataError, match="unknown qid"):
        load_qrels(ok, known_qids={"q1"})
    with pytest.raises(EvalDataError, match="header"):
        load_qrels(write(tmp_path / "h.tsv", "query\tdoc\tgrade\nq1\tA\t2\n"))


def test_overruled_list(tmp_path):
    csv = "overruled_doc_id,overruling_doc_id,point,source,verified_by\nA,Z,adultery,judgment,L1\nB,Y,x,y,L2\n"
    assert load_overruled(write(tmp_path / "g.csv", csv)) == {"A", "B"}
    with pytest.raises(EvalDataError, match="empty"):
        load_overruled(write(tmp_path / "e.csv", "overruled_doc_id,overruling_doc_id,point,source,verified_by\n,Z,x,y,L1\n"))


# ------------------------------------------------------------------------ grid
def test_simplex_grid_covers_the_simplex_with_floors():
    full = list(simplex_grid(SIGNALS, 0.1, {"rel": 0.3}))
    assert len(full) == 120  # compositions of the remaining 7 units over 4 signals with rel >= 3 units
    assert all(math.isclose(sum(v.values()), 1.0) for v in full)
    assert all(v["rel"] >= 0.3 - 1e-9 for v in full)
    assert len({tuple(v.values()) for v in full}) == 120
    assert len(list(simplex_grid(("rel", "cont"), 0.1))) == 11
    assert list(simplex_grid(("rel",), 0.1)) == [{"rel": 1.0}]


def test_simplex_grid_rejects_a_step_that_does_not_divide_one():
    with pytest.raises(ValueError):
        list(simplex_grid(SIGNALS, 0.3))


# ---------------------------------------------------------------------- tuning
def dev_query(qid="q1"):
    return Query(qid, "murder", None, "dev", "A")


def test_tuning_finds_weights_that_fix_the_ranking_and_prefers_the_start(make_providers):
    p = make_providers()
    collected = {"q1": collect("murder", None, SIGNALS, providers=p)}
    # B is good law and relevant, D is relevant; A (top text match) was overruled, C's statute was omitted
    qrels = {"q1": {"A": 0, "B": 2, "C": 0, "D": 1}}
    res = tune_config("full", collected, [dev_query()], qrels, None, floors={"rel": 0.3})
    start = normalise_weights(load_config()["ranking"]["configs"]["full"])
    start_trial = next(t for t in res.trials if all(math.isclose(t.weights[s], start[s]) for s in SIGNALS))
    assert start_trial.score < res.best.score == pytest.approx(1.0)  # the starting weights rank D too low
    assert res.best.weights["rel"] >= 0.3 - 1e-9 and math.isclose(sum(res.best.weights.values()), 1.0)
    assert res.n_queries == 1 and res.grid_size == len(res.trials) == 120
    # among all weight vectors that reach the best score, the chosen one is closest to the starting weights
    def dist(t):
        return sum(abs(t.weights[s] - start[s]) for s in SIGNALS)
    assert dist(res.best) <= min(dist(t) for t in res.trials if t.score >= res.best.score - 1e-12) + 1e-12


def test_tuning_is_deterministic(make_providers):
    p = make_providers()
    collected = {"q1": collect("murder", None, SIGNALS, providers=p)}
    qrels = {"q1": {"A": 0, "B": 2, "C": 0, "D": 1}}
    a = tune_config("full", collected, [dev_query()], qrels, None)
    b = tune_config("full", collected, [dev_query()], qrels, None)
    assert a.best.weights == b.best.weights and a.best.score == b.best.score


def test_a_flat_objective_falls_back_to_the_starting_weights(make_providers):
    table = {"A": dict(rel=3.0, cont=1.0, health=1.0, auth=0.5, evidence=[])}
    p = make_providers(table)
    collected = {"q1": collect("q", None, SIGNALS, providers=p)}
    res = tune_config("full", collected, [dev_query()], {"q1": {"A": 2}}, None)
    start = normalise_weights(load_config()["ranking"]["configs"]["full"])
    assert res.best.weights == pytest.approx(start)


@pytest.mark.parametrize("objective", ["harmful@10", "judged@10", "recall", ""])
def test_only_higher_is_better_ranking_metrics_can_be_tuning_objectives(make_providers, objective):
    # harmful@10 is lower-is-better, judged@10 measures the pool: optimising either would be silently wrong
    p = make_providers()
    collected = {"q1": collect("murder", None, SIGNALS, providers=p)}
    with pytest.raises(TuningError, match="higher-is-better"):
        tune_config("full", collected, [dev_query()], {"q1": {"A": 2}}, {"A"}, objective=objective)


def test_every_valid_objective_is_accepted(make_providers):
    from eval.metrics import OBJECTIVES

    p = make_providers()
    collected = {"q1": collect("murder", None, SIGNALS, providers=p)}
    for objective in OBJECTIVES:
        res = tune_config("b1", collected, [dev_query()], {"q1": {"A": 0, "B": 2, "D": 1}}, None, objective=objective)
        assert res.objective == objective


def test_the_command_line_rejects_a_non_objective():
    import eval.run_ablation as run_ablation

    with pytest.raises(SystemExit):
        run_ablation.parse_args(["--objective", "harmful@10"])


def test_tuning_refuses_test_queries_and_untunable_configs(make_providers):
    p = make_providers()
    collected = {"t1": collect("q", None, SIGNALS, providers=p)}
    qrels = {"t1": {"A": 2}}
    test_query = Query("t1", "q", None, "test", "A")
    with pytest.raises(TuningError, match="non-dev"):
        tune_config("full", collected, [test_query], qrels, None)
    with pytest.raises(TuningError, match="non-dev"):
        tune_config("full", collected, [dev_query("t1"), test_query], qrels, None)
    with pytest.raises(TuningError, match="single signal"):
        tune_config("b0", {"q1": collect("q", None, SIGNALS, providers=p)}, [dev_query()], {"q1": {"A": 2}}, None)
    with pytest.raises(TuningError, match="no dev queries"):
        tune_config("full", {}, [], {}, None)


def test_save_tuned_merges_and_is_picked_up_by_load_weights(tmp_path, write_config, monkeypatch):
    tuned = tmp_path / "weights_tuned.yaml"
    path = write_config(tmp_path / "config.yaml", {"ranking": {"use_tuned": True, "tuned_file": str(tuned)}})
    monkeypatch.setenv("LEXSHIFT_CONFIG", str(path))
    cfg = load_config()
    save_tuned({"b1": {"rel": 0.6, "cont": 0.4, "health": 0.0, "auth": 0.0}}, cfg)
    save_tuned({"full": {"rel": 0.4, "cont": 0.1, "health": 0.4, "auth": 0.1}}, cfg)
    data = yaml.safe_load(tuned.read_text(encoding="utf-8"))
    assert set(data) == {"b1", "full"} and "health" not in data["b1"]  # earlier entry kept, zero weights omitted
    assert load_weights("full", cfg)["health"] == pytest.approx(0.4)
    assert load_weights("b1", cfg)["cont"] == pytest.approx(0.4)
    assert tuned.read_text(encoding="utf-8").startswith("# Fusion weights tuned on the DEV split only")
