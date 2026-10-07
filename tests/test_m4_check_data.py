from pathlib import Path

from common.io import write_jsonl
from common.schema import Query
from eval import check_data
from eval.check_data import PLAN, check, render


def q(qid, split="dev", type_="A", date="2025-01-10", text=None):
    return Query(qid, text or f"query {qid}", date, split, type_)


def full_plan(**over):
    """10 dev and 20 test queries covering every type, each with a date where one matters."""
    out = []
    for i in range(10):
        out.append(q(f"dev{i}", "dev", "ABCD"[i % 4], date=None if "ABCD"[i % 4] in "BC" else "2025-01-10"))
    for i in range(20):
        out.append(q(f"test{i}", "test", "ABCD"[i % 4], date=None if "ABCD"[i % 4] in "BC" else "2025-01-10"))
    return out


def judged(queries):
    return {x.qid: {"d1": 2, "d2": 0, "d3": 1} for x in queries}


def messages(findings):
    return " || ".join(findings.errors + findings.warnings + findings.info)


def test_a_complete_well_formed_set_has_no_errors_or_warnings():
    queries = full_plan()
    qrels = judged(queries)
    f = check(queries, qrels, {"d2"}, {"d1", "d2", "d3"})
    assert f.errors == [] and f.warnings == [], messages(f)
    assert "dev: A=" in f.info[0] and "(total 10)" in f.info[0] and "(total 20)" in f.info[0]


def test_split_sizes_missing_types_and_missing_dates_are_warned():
    queries = [q("dev1", "dev", "A", date=None), q("test1", "test", "A"), q("test2", "test", "A")]
    f = check(queries, {}, set(), None)
    text = messages(f)
    assert "1 dev queries; the plan is 10" in text and "2 test queries; the plan is 20" in text
    for t in "BCD":
        assert f"no query of type {t} at all" in text
    assert "dev1 (type A) has no offence_date" in text
    assert "no judgements yet" in text and "not built" in text and "gold_overrulings.csv is empty" in text


def test_duplicate_queries_are_flagged_case_and_whitespace_insensitively():
    f = check([q("a", text="Section  103"), q("b", text="section 103")], {}, set(), None)
    assert any("b repeats the text and date of a" in w for w in f.warnings)
    assert not any("repeats" in w for w in check([q("a", text="section 103", date="2020-01-01"),
                                                  q("b", text="section 103", date="2025-01-01")], {}, set(), None).warnings)


def test_judged_queries_with_nothing_relevant_are_warned_and_nothing_good_is_noted():
    queries = [q("a"), q("b"), q("c")]
    qrels = {"a": {"d1": 0, "d2": 0}, "b": {"d1": 1}, "c": {"d1": 2}}
    f = check(queries, qrels, set(), {"d1", "d2"})
    assert any("no relevant document (grade >= 1) for a" in w for w in f.warnings)
    assert any("no grade-2 document for a, b" in i for i in f.info)


def test_type_c_queries_need_a_gold_overruled_document_for_harmful_to_mean_something():
    queries = [q("c1", type_="C", date=None), q("c2", type_="C", date=None)]
    qrels = {"c1": {"old": 0, "new": 2}, "c2": {"x": 2}}
    f = check(queries, qrels, {"old"}, {"old", "new", "x"})
    assert any("c2 (type C" in w for w in f.warnings) and not any("c1 (type C" in w for w in f.warnings)


def test_ids_missing_from_the_corpus_are_errors():
    queries = [q("a")]
    f = check(queries, {"a": {"d1": 2, "typo": 1}}, {"gold-typo"}, {"d1"})
    assert len(f.errors) == 2 and any("'typo'" in e for e in f.errors) and any("'gold-typo'" in e for e in f.errors)
    assert check(queries, {"a": {"d1": 2}}, set(), None).errors == []  # not verifiable without the corpus: a warning, not an error


def test_render_counts_and_labels():
    f = check([q("a")], {}, set(), None)
    out = render(f)
    assert "[WARNING]" in out and "[info]" in out and "0 error(s)," in out


def test_plan_matches_the_build_guide():
    assert PLAN == {"dev": 10, "test": 20}


# ------------------------------------------------------------------- command
def test_main_with_no_queries_is_a_warning_unless_strict(eval_workspace, capsys):
    eval_workspace.queries_path.write_text("", encoding="utf-8")
    assert check_data.main([]) == 0
    assert "has not been written yet" in capsys.readouterr().out
    assert check_data.main(["--strict"]) == 1


def test_main_verifies_ids_against_the_corpus(eval_workspace, capsys):
    eval_workspace.write_qrels([("dev1", "A", 2), ("dev1", "TYPO", 1)])
    write_jsonl(eval_workspace.judgments_path, [{"doc_id": "A", "title": "t", "text": "x"}])
    assert check_data.main([]) == 1
    assert "'TYPO'" in capsys.readouterr().out
    eval_workspace.write_qrels([("dev1", "A", 2)])
    assert check_data.main([]) == 0
    assert check_data.main(["--strict"]) == 1  # still plenty of warnings: 4 queries, not 30


def test_main_reports_malformed_files_as_errors(eval_workspace, capsys):
    eval_workspace.qrels_path.write_text("qid\tdoc_id\tgrade\nghost\tA\t2\n", encoding="utf-8")
    assert check_data.main([]) == 1 and "unknown qid" in capsys.readouterr().out


def test_the_shipped_example_queries_are_loadable_and_balanced():
    from collections import Counter

    from eval.loaders import load_qrels, load_queries

    root = Path(__file__).resolve().parents[1] / "eval" / "examples"
    queries = load_queries(root / "queries.example.jsonl")
    assert len(queries) == 30 and len({x.qid for x in queries}) == 30
    counts = Counter((x.split, x.type) for x in queries)
    assert sum(1 for x in queries if x.split == "dev") == 10 and sum(1 for x in queries if x.split == "test") == 20
    assert {t for s, t in counts if s == "dev"} == set("ABCD")  # every type on dev
    assert {t for s, t in counts if s == "test"} == set("ABCD")  # every type on test
    # a bare "section N" query and a BNS query always carry the offence date that decides the code
    assert all(x.offence_date for x in queries if x.type in "AD") and all(x.offence_date for x in queries if x.type == "B")
    assert all(x.offence_date is None for x in queries if x.type == "C")  # doctrine queries carry no date
    qrels = load_qrels(root / "qrels.example.tsv", known_qids={x.qid for x in queries})
    assert all(doc.startswith("EXAMPLE-") for docs in qrels.values() for doc in docs)  # format examples only, never real ids
    # no document-grade file for the real evaluation lives next to the examples
    assert not (root / "qrels.tsv").exists() and not (root / "queries.jsonl").exists()


def test_example_topics_do_not_leak_between_dev_and_test():
    from eval.loaders import load_queries

    root = Path(__file__).resolve().parents[1] / "eval" / "examples"
    queries = load_queries(root / "queries.example.jsonl")
    dev = {x.text for x in queries if x.split == "dev"}
    test = {x.text for x in queries if x.split == "test"}
    assert not dev & test  # identical text may only repeat inside one split (the dated pairs)
    texts = [x.text for x in queries]
    repeated = {t for t in texts if texts.count(t) > 1}
    for t in repeated:  # a repeated text must be a same-split pair that differs by date
        group = [x for x in queries if x.text == t]
        assert len({x.split for x in group}) == 1 and len({x.offence_date for x in group}) == len(group)
