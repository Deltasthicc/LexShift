"""Pooling. With tests/conftest.py's SCENARIO the three systems rank the four candidates:
    b0: A B C D      b1: A B D C      full: B A C D
so at depth 2 the pool is {A, B} and at depth 3 it is {A, B, C, D}.
"""

import csv

import pytest

from common.config import load_config
from common.io import write_jsonl
from common.schema import Query
from eval import pool
from eval.pool import SHEET_COLUMNS, blind_order, build_pool, drop_judged, load_doc_context, overlap_stats
from m4_rank.rank import collect
from m4_rank.weights import SIGNALS, load_weights

CONFIGS = ("b0", "b1", "full")


def collected_for(make_providers, queries):
    p = make_providers()
    return {q.qid: collect(q.text, q.offence_date, SIGNALS, providers=p) for q in queries}


def read(path):
    with open(path, encoding="utf-8", newline="") as fh:
        return list(csv.DictReader(fh))


# ------------------------------------------------------------------- pure logic
def test_pool_is_the_union_of_every_systems_top_depth_with_ranks(make_providers):
    q = Query("q1", "murder", None, "dev", "A")
    weights = {n: load_weights(n) for n in CONFIGS}
    cfg = load_config()
    two = build_pool([q], collected_for(make_providers, [q]), weights, 2, cfg)["q1"]
    assert set(two) == {"A", "B"}
    assert two["A"] == {"b0": 1, "b1": 1, "full": 2} and two["B"] == {"b0": 2, "b1": 2, "full": 1}
    three = build_pool([q], collected_for(make_providers, [q]), weights, 3, cfg)["q1"]
    assert set(three) == {"A", "B", "C", "D"}
    assert three["D"] == {"b1": 3}  # only b1 puts D in its top 3
    assert three["C"] == {"b0": 3, "full": 3}


def test_drop_judged_keeps_only_what_still_needs_a_grade():
    pooled = {"q1": {"A": {"b0": 1}, "B": {"b0": 2}}, "q2": {"A": {"b0": 1}}}
    assert drop_judged(pooled, {"q1": {"A": 2}}) == {"q1": {"B": {"b0": 2}}, "q2": {"A": {"b0": 1}}}
    assert drop_judged(pooled, {}) == pooled


def test_blind_order_is_a_deterministic_permutation_independent_of_input_order():
    ids = [f"d{i}" for i in range(12)]
    a = blind_order("q1", ids, seed=0)
    assert sorted(a) == sorted(ids)
    assert a == blind_order("q1", list(reversed(ids)), seed=0)
    assert a == blind_order("q1", ids, seed=0)
    assert a != sorted(ids) or a != blind_order("q1", ids, seed=1)  # the shuffle really moves things
    assert blind_order("q1", ids, seed=0) != blind_order("q2", ids, seed=0)


def test_overlap_stats():
    docs = {"A": {"b0": 1, "b1": 1, "full": 2}, "B": {"b0": 2}, "C": {"full": 3, "b1": 4}}
    assert overlap_stats(docs, CONFIGS) == {"union": 3, "in_all": 1, "in_one": 1}


def test_doc_context_uses_the_holding_zone_tidies_whitespace_and_truncates(tmp_path):
    path = tmp_path / "j.jsonl"
    write_jsonl(path, [
        {"doc_id": "A", "title": "State v. X", "date": "2019-03-04", "bench_size": 5,
         "zones": {"holding": "The appeal\n\n is   allowed. " + "x" * 800}, "text": "full text"},
        {"doc_id": "B", "title": "Y v. State", "date": "2001-01-01", "bench_size": None, "zones": {}, "text": "Plain text body"},
        {"doc_id": "C", "title": "not pooled", "date": "2000-01-01", "bench_size": 3, "zones": {}, "text": "t"},
    ])
    ctx = load_doc_context({"A", "B"}, path)
    assert set(ctx) == {"A", "B"}
    assert ctx["A"]["excerpt"].startswith("The appeal is allowed.") and len(ctx["A"]["excerpt"]) == 500
    assert ctx["A"]["excerpt"].endswith("...") and ctx["A"]["bench_size"] == 5
    assert ctx["B"]["excerpt"] == "Plain text body" and ctx["B"]["bench_size"] == ""
    assert load_doc_context({"A"}, tmp_path / "missing.jsonl") == {} and load_doc_context(set(), path) == {}


# ---------------------------------------------------------------------- command
def run(args):
    return pool.main(["--depth", "3", *args])


def test_pool_writes_a_blind_sheet_provenance_and_summary(eval_workspace, capsys):
    assert run(["--round", "r1"]) == 0
    folder = eval_workspace.judging / "r1"
    assert {p.name for p in folder.iterdir()} == {"sheet_template.csv", "provenance.csv", "summary.md"}
    rows = read(folder / "sheet_template.csv")
    assert len(rows) == 16 and list(rows[0]) == list(SHEET_COLUMNS)  # 4 queries x 4 pooled documents
    assert all(r["grade"] == "" and r["note"] == "" for r in rows)
    sheet_text = (folder / "sheet_template.csv").read_text(encoding="utf-8")
    assert "rank" not in sheet_text.split("\n")[0] and "score" not in sheet_text.split("\n")[0]
    assert {(r["qid"], r["doc_id"]) for r in rows} == {(q, d) for q in ("dev1", "dev2", "test1", "test2") for d in "ABCD"}
    assert {r["offence_date"] for r in rows if r["qid"] == "test2"} == {"2020-06-01"} and rows[0]["type"] in "ACD"
    prov = {(r["qid"], r["doc_id"]): r for r in read(folder / "provenance.csv")}
    assert prov[("dev1", "D")]["rank_b1"] == "3" and prov[("dev1", "D")]["rank_b0"] == "" and prov[("dev1", "D")]["n_systems"] == "1"
    summary = (folder / "summary.md").read_text(encoding="utf-8")
    assert "16 documents to judge now" in summary and "32 individual judgements" in summary
    assert "No judgments.jsonl was found" in summary and "STUB" not in summary
    assert "Next:" in capsys.readouterr().out


def test_the_sheet_order_does_not_follow_any_systems_ranking(eval_workspace):
    run(["--round", "r1"])
    by_query = {}
    for r in read(eval_workspace.judging / "r1" / "sheet_template.csv"):
        by_query.setdefault(r["qid"], []).append(r["doc_id"])
    systems = {"b0": list("ABCD"), "b1": list("ABDC"), "full": list("BACD")}
    # a blind sheet must not reproduce a system's order for every query
    assert not all(order == systems["b0"] for order in by_query.values())
    assert any(order != sorted(order) for order in by_query.values())


def test_sheet_carries_titles_and_excerpts_when_the_corpus_exists(eval_workspace):
    write_jsonl(eval_workspace.judgments_path, [
        {"doc_id": d, "title": f"Case {d}", "date": "2019-01-01", "bench_size": 3, "zones": {"holding": f"holding of {d}"}, "text": "t"}
        for d in "ABCD"])
    run(["--round", "r1"])
    rows = read(eval_workspace.judging / "r1" / "sheet_template.csv")
    a = next(r for r in rows if r["doc_id"] == "A")
    assert (a["title"], a["date"], a["bench_size"], a["excerpt"]) == ("Case A", "2019-01-01", "3", "holding of A")


def test_stub_providers_are_refused_and_stub_rounds_are_set_apart(eval_workspace, make_providers, capsys):
    eval_workspace.providers = make_providers(stubbed={"search"})
    assert run(["--round", "r1"]) == 2
    assert "Refusing to pool" in capsys.readouterr().out and not eval_workspace.judging.exists()
    assert run(["--round", "r1", "--allow-stubs"]) == 0
    assert (eval_workspace.judging / "stub_r1" / "sheet_template.csv").exists()
    assert "STUB ROUND" in (eval_workspace.judging / "stub_r1" / "summary.md").read_text(encoding="utf-8")


def test_an_existing_round_is_never_overwritten_and_force_spares_judge_files(eval_workspace, capsys):
    assert run(["--round", "r1"]) == 0
    judge = eval_workspace.judging / "r1" / "judge1.csv"
    judge.write_text("qid,doc_id,grade\ndev1,A,2\n", encoding="utf-8")
    assert run(["--round", "r1"]) == 2
    assert "already exists" in capsys.readouterr().out
    assert run(["--round", "r1", "--force"]) == 0
    assert judge.read_text(encoding="utf-8") == "qid,doc_id,grade\ndev1,A,2\n"  # a judge's work is never touched


def test_pooling_is_incremental_and_says_so_when_nothing_is_left(eval_workspace, capsys):
    eval_workspace.write_qrels([("dev1", "A", 2), ("dev1", "B", 0)])
    assert run(["--round", "r2"]) == 0
    rows = read(eval_workspace.judging / "r2" / "sheet_template.csv")
    assert len(rows) == 14 and not {("dev1", "A"), ("dev1", "B")} & {(r["qid"], r["doc_id"]) for r in rows}
    prov = {(r["qid"], r["doc_id"]): r["already_judged"] for r in read(eval_workspace.judging / "r2" / "provenance.csv")}
    assert prov[("dev1", "A")] == "True" and prov[("dev1", "C")] == "False"
    # now everything is judged
    eval_workspace.write_qrels([(q, d, 1) for q in ("dev1", "dev2", "test1", "test2") for d in "ABCD"])
    assert run(["--round", "r3"]) == 0
    assert "Nothing to judge" in capsys.readouterr().out and not (eval_workspace.judging / "r3").exists()
    assert run(["--round", "r4", "--include-judged"]) == 0 and len(read(eval_workspace.judging / "r4" / "sheet_template.csv")) == 16


def test_split_selection_and_bad_arguments(eval_workspace, capsys):
    assert run(["--round", "r1", "--split", "dev"]) == 0
    assert {r["qid"] for r in read(eval_workspace.judging / "r1" / "sheet_template.csv")} == {"dev1", "dev2"}
    assert pool.main(["--round", "r2", "--depth", "500"]) == 2 and "--depth must be" in capsys.readouterr().out
    eval_workspace.queries_path.write_text("", encoding="utf-8")
    assert run(["--round", "r5"]) == 2 and "No queries" in capsys.readouterr().out
