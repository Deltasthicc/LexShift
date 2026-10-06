"""The judging round trip: pool -> two judges grade -> make_qrels -> qrels.tsv (with kappa and adjudication)."""

import csv

import pytest

from common.io import read_delimited
from eval import make_qrels, pool
from eval.loaders import load_qrels
from eval.make_qrels import _parse_grade, merge_qrels, reconcile

QIDS = ("dev1", "dev2", "test1", "test2")


@pytest.fixture
def round1(eval_workspace):
    """A pooled round with the template written (16 rows: 4 queries x documents A-D)."""
    assert pool.main(["--depth", "3", "--round", "r1"]) == 0
    folder = eval_workspace.judging / "r1"
    return eval_workspace, folder


def template(folder):
    return read_delimited(folder / "sheet_template.csv")


def write_judge(folder, name, grader, *, drop=(), extra=(), bom=False, header=None):
    """Write judge<name>.csv from the template; grader(qid, doc_id) -> grade (or '' for blank)."""
    rows = [r for r in template(folder) if (r["qid"], r["doc_id"]) not in set(drop)]
    for r in rows:
        r["grade"] = grader(r["qid"], r["doc_id"])
    rows += list(extra)
    cols = header or list(template(folder)[0])
    with open(folder / f"{name}.csv", "w", encoding="utf-8-sig" if bom else "utf-8", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=cols, extrasaction="ignore")
        w.writeheader()
        w.writerows(rows)


GOOD = {"A": 0, "B": 2, "C": 1, "D": 1}  # A overruled, B good law, C and D relevant with caution


def agree(qid, doc):
    return GOOD[doc]


def test_two_agreeing_judges_produce_qrels_and_an_agreement_report(round1, capsys):
    ws, folder = round1
    write_judge(folder, "judge1", agree)
    write_judge(folder, "judge2", agree)
    assert make_qrels.main(["--round", "r1"]) == 0
    qrels = load_qrels(ws.qrels_path)
    assert set(qrels) == set(QIDS) and qrels["dev1"] == GOOD
    out = capsys.readouterr().out
    assert "16 documents graded by both judges; agreement 100.0%" in out and "Wrote 16 judgements for 4 queries" in out
    report = (folder / "agreement.md").read_text(encoding="utf-8")
    assert "Exact agreement: **100.0%**" in report and "Disagreements: 0" in report
    assert read_delimited(folder / "disagreements.csv") == []


def test_disagreements_block_qrels_until_they_are_adjudicated(round1, capsys):
    ws, folder = round1
    write_judge(folder, "judge1", agree)
    write_judge(folder, "judge2", lambda q, d: 2 if (q, d) == ("dev1", "C") else (0 if (q, d) == ("test1", "B") else agree(q, d)))
    assert make_qrels.main(["--round", "r1"]) == 2
    assert not ws.qrels_path.exists() or not load_qrels(ws.qrels_path)
    out = capsys.readouterr().out
    assert "2 disagreement(s)" in out and "2 still need" in out and "qrels.tsv was NOT written" in out
    dis = read_delimited(folder / "disagreements.csv")
    assert {(r["qid"], r["doc_id"]) for r in dis} == {("dev1", "C"), ("test1", "B")}
    assert {(r["grade_judge1"], r["grade_judge2"]) for r in dis} == {("1", "2"), ("2", "0")}
    assert dis[0]["query"] and "adjudicated" in dis[0]

    # the team discusses, types the agreed grades and a reason, and re-runs
    for r in dis:
        r["adjudicated"] = "1" if r["qid"] == "dev1" else "2"
        r["note"] = "re-read the judgment together"
    with open(folder / "disagreements.csv", "w", encoding="utf-8", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=list(dis[0]))
        w.writeheader()
        w.writerows(dis)
    assert make_qrels.main(["--round", "r1"]) == 0
    qrels = load_qrels(ws.qrels_path)
    assert qrels["dev1"]["C"] == 1 and qrels["test1"]["B"] == 2  # the adjudicated values, not either judge's own
    again = read_delimited(folder / "disagreements.csv")
    assert {r["adjudicated"] for r in again} == {"1", "2"} and {r["note"] for r in again} == {"re-read the judgment together"}


def test_a_broken_judge_file_never_wipes_typed_adjudications(round1, capsys):
    ws, folder = round1
    write_judge(folder, "judge1", agree)
    write_judge(folder, "judge2", lambda q, d: 2 if (q, d) == ("dev1", "C") else agree(q, d))
    assert make_qrels.main(["--round", "r1"]) == 2  # one disagreement, not adjudicated yet
    dis = read_delimited(folder / "disagreements.csv")
    dis[0]["adjudicated"], dis[0]["note"] = "1", "agreed after re-reading"
    with open(folder / "disagreements.csv", "w", encoding="utf-8", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=list(dis[0]))
        w.writeheader()
        w.writerows(dis)
    typed = (folder / "disagreements.csv").read_bytes()
    report = (folder / "agreement.md").read_bytes()

    # judge 1's file is later damaged (renamed column), then blanked of a row
    write_judge(folder, "judge1", agree, header=["qid", "doc_id", "score"])
    assert make_qrels.main(["--round", "r1"]) == 2
    assert "were not updated" in capsys.readouterr().out
    assert (folder / "disagreements.csv").read_bytes() == typed and (folder / "agreement.md").read_bytes() == report

    write_judge(folder, "judge1", agree)  # fixed again: the adjudication is still there and is used
    assert make_qrels.main(["--round", "r1"]) == 0
    assert load_qrels(ws.qrels_path)["dev1"]["C"] == 1


def test_short_rows_are_reported_not_crashed_on(round1, capsys):
    ws, folder = round1
    write_judge(folder, "judge2", agree)
    lines = (folder / "sheet_template.csv").read_text(encoding="utf-8").splitlines()
    header = lines[0].split(",")
    # judge 1's file has rows cut short after the doc_id column: grade and note cells are missing altogether
    cut = [",".join(line.split(",")[: header.index("doc_id") + 1]) if i % 2 else line for i, line in enumerate(lines)]
    (folder / "judge1.csv").write_text("\n".join(cut) + "\n", encoding="utf-8")
    assert make_qrels.main(["--round", "r1"]) == 2
    assert "have no grade yet" in capsys.readouterr().out


def test_round_names_cannot_escape_the_judging_folder(eval_workspace, capsys):
    for bad in ("../x", "a/b", ".."):
        assert make_qrels.main(["--round", bad]) == 2
        assert "plain folder name" in capsys.readouterr().out


def test_qrels_are_written_atomically_with_unix_line_endings(round1):
    ws, folder = round1
    write_judge(folder, "judge1", agree)
    write_judge(folder, "judge2", agree)
    assert make_qrels.main(["--round", "r1"]) == 0
    assert b"\r\n" not in ws.qrels_path.read_bytes() and ws.qrels_path.read_bytes().startswith(b"qid\tdoc_id\tgrade\n")
    assert not list(ws.dir.glob("*.tmp")) and not list(folder.glob("*.tmp"))


def test_missing_blank_added_duplicate_and_invalid_rows_are_all_rejected(round1, capsys):
    ws, folder = round1
    write_judge(folder, "judge2", agree)
    stray = {"qid": "dev1", "doc_id": "NOPE", "grade": "2"}
    dup = [r for r in template(folder) if (r["qid"], r["doc_id"]) == ("dev1", "A")][0] | {"grade": "2"}
    write_judge(folder, "judge1", lambda q, d: "" if (q, d) == ("dev1", "B") else ("3" if (q, d) == ("dev1", "C") else agree(q, d)),
                drop={("dev2", "A")}, extra=[stray, dup])
    assert make_qrels.main(["--round", "r1"]) == 2
    out = capsys.readouterr().out
    for fragment in ("template row ('dev2', 'A') is missing", "NOPE", "duplicate row", "is not one of", "have no grade yet"):
        assert fragment in out, fragment
    assert not ws.qrels_path.exists() or not load_qrels(ws.qrels_path)


def test_allow_incomplete_writes_only_the_settled_rows(round1):
    ws, folder = round1
    write_judge(folder, "judge1", lambda q, d: "" if q == "test2" else agree(q, d))
    write_judge(folder, "judge2", agree)
    assert make_qrels.main(["--round", "r1", "--allow-incomplete"]) == 0
    qrels = load_qrels(ws.qrels_path)
    assert set(qrels) == {"dev1", "dev2", "test1"}  # test2 was not graded by judge 1


def test_a_judge_file_missing_or_with_the_wrong_columns(round1, capsys):
    ws, folder = round1
    write_judge(folder, "judge1", agree)
    assert make_qrels.main(["--round", "r1"]) == 2 and "missing judge2.csv" in capsys.readouterr().out
    write_judge(folder, "judge2", agree, header=["qid", "doc_id", "score"])
    assert make_qrels.main(["--round", "r1"]) == 2 and "needs the columns" in capsys.readouterr().out


def test_spreadsheet_files_with_a_byte_order_mark_are_read(round1):
    ws, folder = round1
    write_judge(folder, "judge1", agree, bom=True)
    write_judge(folder, "judge2", agree, bom=True)
    assert make_qrels.main(["--round", "r1"]) == 0


def test_earlier_grades_survive_and_are_never_silently_changed(round1, capsys):
    ws, folder = round1
    ws.write_qrels([("dev1", "A", 0), ("old", "X", 2)])
    ws.write_queries([
        {"qid": q, "text": "t", "offence_date": None, "split": "dev" if q.startswith("dev") else "test", "type": "A"}
        for q in (*QIDS, "old")])
    write_judge(folder, "judge1", agree)
    write_judge(folder, "judge2", agree)
    assert make_qrels.main(["--round", "r1"]) == 0  # (dev1, A) agrees with the earlier 0
    qrels = load_qrels(ws.qrels_path)
    assert qrels["old"] == {"X": 2} and qrels["dev1"]["A"] == 0 and len(qrels["dev1"]) == 4

    ws.write_qrels([("dev1", "A", 2)])  # someone edited an earlier grade; this round says 0
    assert make_qrels.main(["--round", "r1"]) == 2
    assert "already graded 2" in capsys.readouterr().out


def test_warns_about_queries_without_any_relevant_document(round1, capsys):
    ws, folder = round1
    zero = lambda q, d: 0 if q == "dev2" else agree(q, d)  # noqa: E731
    write_judge(folder, "judge1", zero)
    write_judge(folder, "judge2", zero)
    assert make_qrels.main(["--round", "r1"]) == 0
    out = capsys.readouterr().out
    assert "no relevant document" in out and "dev2" in out


def test_stub_rounds_and_unknown_rounds_are_refused(eval_workspace, capsys):
    assert make_qrels.main(["--round", "stub_r1"]) == 2 and "stub round" in capsys.readouterr().out
    assert make_qrels.main(["--round", "nothing"]) == 2 and "not found" in capsys.readouterr().out


# ---------------------------------------------------------------------- units
@pytest.mark.parametrize("raw,expected", [("0", 0), ("2", 2), (" 1 ", 1), ("2.0", 2), ("", None), (None, None)])
def test_parse_grade_accepts(raw, expected):
    assert _parse_grade(raw) == expected


@pytest.mark.parametrize("raw", ["3", "-1", "1.5", "x", "two"])
def test_parse_grade_rejects(raw):
    with pytest.raises(ValueError):
        _parse_grade(raw)


def test_reconcile_and_merge():
    g1 = {("q", "a"): 2, ("q", "b"): 1, ("q", "c"): 0}
    g2 = {("q", "a"): 2, ("q", "b"): 0, ("q", "c"): 0, ("q", "only2"): 1}
    final, dis, unresolved = reconcile(g1, g2, {})
    assert final == {("q", "a"): 2, ("q", "c"): 0} and dis == [("q", "b")] and unresolved == [("q", "b")]
    final, _, unresolved = reconcile(g1, g2, {("q", "b"): (1, "n")})
    assert final[("q", "b")] == 1 and unresolved == []
    assert merge_qrels({"q": {"a": 2}}, {("q", "a"): 2, ("r", "z"): 0}) == {"q": {"a": 2}, "r": {"z": 0}}
    with pytest.raises(make_qrels.QrelsBuildError):
        merge_qrels({"q": {"a": 2}}, {("q", "a"): 1})
