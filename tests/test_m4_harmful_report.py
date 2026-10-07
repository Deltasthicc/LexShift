"""harmful@10 without grades: the arithmetic and the rank table, on a hand-made run."""

from eval.harmful_report import harmful_share, rank_rows, render

RUNS = {
    "q1": {"b0": ["bad", "ok1", "ok2"], "b1": ["bad", "ok1", "ok2"], "full": ["ok1", "ok2", "bad"]},
    "q2": {"b0": ["ok1", "ok2", "ok3"], "b1": ["ok1", "ok2", "ok3"], "full": ["ok1", "ok2", "ok3"]},
}
GOLD = {"bad"}


def test_harmful_share_is_the_fraction_of_the_top_k_on_the_gold_list():
    assert harmful_share(["bad", "x", "y", "z"], GOLD, 4) == 0.25
    assert harmful_share(["x"], GOLD, 10) == 0.0
    assert harmful_share(["bad"] * 10, GOLD, 10) == 1.0


def test_rank_rows_list_only_gold_documents_that_reach_a_top_k_and_their_ranks():
    rows = rank_rows(RUNS, GOLD, k=3)
    assert rows == [{"qid": "q1", "doc_id": "bad", "b0": 1, "b1": 1, "full": 3}]
    assert rank_rows(RUNS, GOLD, k=2)[0]["full"] == ""  # not in Full's top 2


def test_the_report_shows_each_system_and_the_demotion():
    text = render(RUNS, GOLD, {"bad": "A Case v. State"}, {"q1": "dev", "q2": "test"}).splitlines()
    assert any(line.startswith("| B0 | 0.050 |") for line in text)  # q1 has 1 of 10 in B0's top 10, q2 none: mean 0.05
    assert any("A Case v. State (bad) | 1 | 1 | 3 |" in line for line in text)
