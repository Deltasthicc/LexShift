"""The pre-submission audit: each rule it enforces is checked on a small throw-away repository."""

from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

import pytest

from eval import submission_check as sc

needs_git = pytest.mark.skipif(shutil.which("git") is None, reason="git is not installed")


def levels(items, check_fragment):
    return [i.level for i in items if check_fragment in i.check]


def make_repo(root: Path, *, stubs: bool = False, note: bool = True, banned: bool = False) -> Path:
    (root / "common").mkdir(parents=True)
    (root / "common" / "config.yaml").write_text("stubs:\n" + "".join(f"  {g}: {str(stubs).lower()}\n" for g in ("search", "statute", "health", "authority")), encoding="utf-8")
    (root / "app" / "web").mkdir(parents=True)
    page = "<p>Treatment signals with evidence.</p>" + ("<p>This is not legal advice.</p>" if note else "") + ("<p>a bad law</p>" if banned else "")
    (root / "app" / "web" / "index.html").write_text(page, encoding="utf-8")
    (root / "app" / "cli.py").write_text('"""The output is not legal advice."""\n', encoding="utf-8")
    (root / "eval" / "results").mkdir(parents=True)
    (root / "eval" / "judging").mkdir(parents=True)
    (root / "README.md").write_text("# x\nCC-BY-4.0\n## Status\npip install -r requirements.txt\npython -m eval.run_ablation\n", encoding="utf-8")
    (root / "AI_USE_LOG.md").write_text("| Date | Tool | What | Where | Human review |\n|---|---|---|---|---|\n| 2026-10-06 | t | w | f | Read line by line |\n", encoding="utf-8")
    return root


def git_init(root: Path) -> None:
    subprocess.run(["git", "init", "-q"], cwd=root, check=True)
    subprocess.run(["git", "add", "-A"], cwd=root, check=True)


def test_a_repository_with_real_providers_and_the_note_passes_those_checks(tmp_path):
    items = sc.audit(make_repo(tmp_path))
    assert levels(items, "every provider is real") == ["PASS"]
    assert levels(items, "banned phrase") == ["PASS"]
    assert levels(items, "not-legal-advice") == ["PASS", "PASS"]
    assert not any(i.level == "FAIL" for i in items if i.group == "documents")


def test_a_stub_switch_still_true_is_a_todo_that_names_it(tmp_path):
    items = sc.audit(make_repo(tmp_path, stubs=True))
    (todo,) = [i for i in items if i.check == "every provider is real"]
    assert todo.level == "TODO" and "health" in todo.detail and "search" in todo.detail


def test_a_banned_phrase_or_a_missing_note_fails(tmp_path):
    items = sc.audit(make_repo(tmp_path, note=False, banned=True))
    assert levels(items, "banned phrase") == ["FAIL"]
    assert "FAIL" in levels(items, "not-legal-advice note in app/web/index.html")


def test_missing_evaluation_inputs_are_todo_not_fail(tmp_path):
    items = sc.audit(make_repo(tmp_path))
    for fragment in ("judged queries", "graded qrels", "gold overruling list", "judge agreement", "final results present", "tuned weights"):
        assert levels(items, fragment) == ["TODO"], fragment


def test_the_query_plan_is_counted_by_split_and_type(tmp_path):
    root = make_repo(tmp_path)
    rows = [{"qid": f"d{i}", "text": f"q{i}", "offence_date": None, "split": "dev", "type": "ABCD"[i % 4]} for i in range(10)]
    rows += [{"qid": f"t{i}", "text": f"q{i}", "offence_date": None, "split": "test", "type": "ABCD"[i % 4]} for i in range(19)]
    (root / "eval" / "queries.jsonl").write_text("\n".join(json.dumps(r) for r in rows) + "\n", encoding="utf-8")
    (item,) = [i for i in sc.audit(root) if i.check == "judged queries match the plan"]
    assert item.level == "TODO" and "19 test (plan 20)" in item.detail

    rows.append({"qid": "t19", "text": "q19", "offence_date": None, "split": "test", "type": "D"})
    (root / "eval" / "queries.jsonl").write_text("\n".join(json.dumps(r) for r in rows) + "\n", encoding="utf-8")
    (item,) = [i for i in sc.audit(root) if i.check == "judged queries match the plan"]
    assert item.level == "PASS" and "30 queries" in item.detail


def test_qrels_must_cover_every_query(tmp_path):
    root = make_repo(tmp_path)
    (root / "eval" / "queries.jsonl").write_text(json.dumps({"qid": "q1", "text": "a", "offence_date": None, "split": "dev", "type": "A"}) + "\n"
                                                 + json.dumps({"qid": "q2", "text": "b", "offence_date": None, "split": "dev", "type": "B"}) + "\n", encoding="utf-8")
    (root / "eval" / "qrels.tsv").write_text("qid\tdoc_id\tgrade\nq1\td1\t2\n", encoding="utf-8")
    (item,) = [i for i in sc.audit(root) if i.check == "every query is judged"]
    assert item.level == "TODO" and "q2" in item.detail


def test_results_present_and_agreement_found(tmp_path):
    root = make_repo(tmp_path)
    for name in sc.RESULT_FILES:
        (root / "eval" / "results" / name).write_text("x", encoding="utf-8")
    (root / "eval" / "judging" / "round1").mkdir()
    (root / "eval" / "judging" / "round1" / "agreement.md").write_text("kappa", encoding="utf-8")
    items = sc.audit(root)
    assert levels(items, "final results present") == ["PASS"]
    assert levels(items, "judge agreement") == ["PASS"]


def test_a_stub_result_left_in_eval_results_is_flagged(tmp_path):
    root = make_repo(tmp_path)
    (root / "eval" / "results" / "stub_ablation_test.csv").write_text("x", encoding="utf-8")
    assert levels(sc.audit(root), "no stub results") == ["TODO"]


@needs_git
def test_a_committed_stub_result_fails(tmp_path):
    root = make_repo(tmp_path)
    (root / "eval" / "results" / "stub_ablation_test.csv").write_text("x", encoding="utf-8")
    git_init(root)
    assert levels(sc.audit(root), "no stub results committed") == ["FAIL"]


@needs_git
def test_a_key_in_a_tracked_file_fails_and_its_value_is_not_printed(tmp_path):
    root = make_repo(tmp_path)
    key = "AIza" + "B" * 35
    (root / "notes.py").write_text(f'KEY = "{key}"\n', encoding="utf-8")
    git_init(root)
    items = sc.audit(root)
    (item,) = [i for i in items if i.check == "no secrets in tracked files"]
    assert item.level == "FAIL" and "notes.py:1" in item.detail
    assert key not in sc.render(items)


@needs_git
def test_a_clean_tracked_tree_has_no_secrets_and_raw_data_is_not_tracked(tmp_path):
    root = make_repo(tmp_path)
    git_init(root)
    items = sc.audit(root)
    assert levels(items, "no secrets") == ["PASS"]
    assert levels(items, "raw data is not committed") == ["PASS"]
    assert levels(items, "repository size") == ["PASS"]


@needs_git
def test_raw_data_that_is_tracked_fails(tmp_path):
    root = make_repo(tmp_path)
    (root / "data" / "raw").mkdir(parents=True)
    (root / "data" / "raw" / "dump.json").write_text("{}", encoding="utf-8")
    git_init(root)
    assert levels(sc.audit(root), "raw data is not committed") == ["FAIL"]


def test_without_git_the_tracked_file_checks_ask_a_person(tmp_path):
    items = sc.audit(make_repo(tmp_path))  # a plain folder, not a repository
    assert levels(items, "secrets and size") == ["MANUAL"]
    assert levels(items, "working tree clean") == ["MANUAL"]


def test_a_pending_review_in_the_ai_log_is_a_todo(tmp_path):
    root = make_repo(tmp_path)
    (root / "AI_USE_LOG.md").write_text("| Date | Tool | What | Where | Human review |\n|---|---|---|---|---|\n"
                                        "| 2026-10-06 | t | w | f | Pending: the owner reads the diff |\n| 2026-10-06 | t | w | f | Read |\n", encoding="utf-8")
    (item,) = [i for i in sc.audit(root) if i.check == "AI-use log: every entry reviewed"]
    assert item.level == "TODO" and "1 of 2" in item.detail


def test_the_readme_must_credit_the_dataset(tmp_path):
    root = make_repo(tmp_path)
    (root / "README.md").write_text("# x\n", encoding="utf-8")
    assert "FAIL" in levels(sc.audit(root), "dataset credited")


def test_the_manual_items_are_always_listed(tmp_path):
    names = [i.check for i in sc.audit(make_repo(tmp_path)) if i.level == "MANUAL" and i.group == "by hand"]
    assert {"clean-machine test", "demo video", "report PDF"} <= set(names)


def test_exit_code_follows_fail_and_strict(tmp_path, capsys):
    ok = make_repo(tmp_path / "ok")
    assert sc.main(["--root", str(ok)]) == 0  # TODO items alone do not fail
    assert sc.main(["--root", str(ok), "--strict"]) == 1
    bad = make_repo(tmp_path / "bad", banned=True)
    assert sc.main(["--root", str(bad)]) == 1
    capsys.readouterr()
    assert sc.main(["--root", str(ok), "--json"]) == 0
    data = json.loads(capsys.readouterr().out)
    assert {"group", "level", "check", "detail"} <= set(data[0])


def test_render_groups_every_check_once_and_totals_the_levels(tmp_path):
    text = sc.render(sc.audit(make_repo(tmp_path)))
    assert text.count("\nrepository\n") == 1
    assert text.splitlines()[-1].endswith("FAIL") and "PASS" in text.splitlines()[-1]


def test_this_repository_has_no_rule_broken():
    """The real repository: TODO items are expected until the hand-made data exists, but a FAIL would be a broken rule."""
    failed = [f"{i.check}: {i.detail}" for i in sc.audit(sc.ROOT) if i.level == "FAIL"]
    assert not failed, failed
