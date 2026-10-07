"""The progress watcher: its parsers and its scoring are pure functions, checked on hand-made facts; the git steps are checked on a throw-away repository."""

from __future__ import annotations

import shutil
import subprocess

import pytest

from eval import progress_watch as pw


# ------------------------------------------------------------------------------------------------------------------ parsers
def test_parse_pytest_reads_the_summary_and_the_failing_files():
    text = ("....F...\n=== short test summary info ===\nFAILED tests/test_a.py::test_x - AssertionError\n"
            "FAILED m2_statute/tests/test_b.py::test_y\nERROR tests/test_c.py::test_z\n2 failed, 561 passed, 1 xfailed in 57.5s\n")
    r = pw.parse_pytest(text)
    assert (r["failed"], r["passed"], r["xfailed"]) == (2, 561, 1)
    assert r["failing_files"] == ["m2_statute/tests/test_b.py", "tests/test_a.py", "tests/test_c.py"]
    assert pw.parse_pytest("nothing useful")["passed"] == 0


def test_parse_smoke_reads_each_line_and_the_final_counts():
    text = "[INFO] providers: search=real, statute=STUB\n[PASS] search() contract (3 queries)\n[FAIL] statute_map.csv\n\n1 failed, 2 skipped\n"
    r = pw.parse_smoke(text)
    assert r["failed"] == 1 and r["skipped"] == 2
    assert ("PASS", "search() contract (3 queries)") in r["lines"] and ("FAIL", "statute_map.csv") in r["lines"]
    assert pw.parse_smoke("crash")["failed"] is None


def test_find_fraction_and_level_of_read_a_conformance_finding():
    findings = [{"module": "M1", "level": "FAIL", "check": "benches of 3 or more judges are recorded", "detail": "27/35 correct. M3 needs them"},
                {"module": "M2", "level": "PASS", "check": "parse_query reads the statute forms the Build Guide lists", "detail": "9/9 read"}]
    assert pw.find_fraction(findings, "benches of 3 or more judges are recorded") == (27, 35)
    assert pw.find_fraction(findings, "nothing like this") is None
    assert pw.level_of(findings, "parse_query reads") == "PASS" and pw.level_of(findings, "absent") is None


def test_json_from_skips_warnings_that_come_first():
    assert pw.json_from("warning [x]\n[\n  {\"a\": 1}\n]\n") == [{"a": 1}]
    assert pw.json_from("note\n{\n \"k\": 2\n}\n") == {"k": 2}
    with pytest.raises(ValueError):
        pw.json_from("no json here")


def test_doctrine_pairs_need_both_ends_in_the_corpus():
    assert pw.pairs_present(["State v. Koushal Kumar", "Navtej Singh Johar v. Union of India", "Rama v. State"]) == ["section 377"]
    assert pw.pairs_present(["Navtej Singh Johar v. Union of India"]) == []  # the overruling end alone is not a pair
    assert pw.pairs_present(["Asian Resurfacing v. CBI", "High Court Bar Association, Allahabad v. v."]) == ["stay after six months"]


def test_bar_and_ratio_are_clamped():
    assert pw.bar(0.5, 10) == "[#####.....]" and pw.bar(2.0, 4) == "[####]" and pw.bar(-1, 4) == "[....]"
    assert pw.ratio(3, 4) == 0.75 and pw.ratio(5, 0) == 0.0 and pw.ratio(9, 3) == 1.0


# ------------------------------------------------------------------------------------------------------------------ scoring
def facts(**over):
    base = {
        "stubs": {"search": True, "statute": True, "health": True, "authority": True},
        "corpus": {"documents": 100, "first_year": 2025, "titles_cut": 0, "pairs": []},
        "feasibility": {"queries": 30, "reach": [], "none": []},
        "conformance": [], "smoke": {"failed": 0}, "smoke_real": {"lines": []}, "pytest": {"failed": 0, "errors": 0, "summary": "1 passed", "failing_files": []},
        "audit": {"PASS": 1, "TODO": 2, "FAIL": 0}, "queries": 30,
    }
    base.update(over)
    return base


def by_name(checks, fragment):
    (c,) = [c for c in checks if fragment in c.name]
    return c


def test_a_measured_pass_scores_one_and_an_unmeasured_fact_scores_zero_and_says_so():
    checks = pw.evaluate(facts())
    assert by_name(checks, "all tests pass").value == 1.0
    assert by_name(checks, "the index rebuilds").value == 0.0  # not measured
    assert by_name(checks, "forms").value == 0.0 and "not measured" in by_name(checks, "forms").detail


def test_partial_credit_follows_the_counts():
    conf = [{"module": "M1", "level": "FAIL", "check": "benches of 3 or more judges are recorded", "detail": "27/35 correct"},
            {"module": "M2", "level": "FAIL", "check": "parse_query reads the statute forms the Build Guide lists", "detail": "6/9 read. Failing: x"}]
    checks = pw.evaluate(facts(conformance=conf, corpus={"documents": 468, "first_year": 2024, "titles_cut": 259, "pairs": ["a", "b", "c"]},
                               feasibility={"queries": 30, "reach": list("abcd"), "none": list("abcdef")}, unknown_act={"unknown": 4053, "total": 7266}))
    assert by_name(checks, "benches").value == pytest.approx(27 / 35)
    assert by_name(checks, "statute forms").value == pytest.approx(6 / 9)
    assert by_name(checks, "case titles").value == pytest.approx(1 - 259 / 468)
    assert by_name(checks, "at least 10 candidate").value == pytest.approx(4 / 30)
    assert by_name(checks, "no query without").value == pytest.approx(1 - 6 / 30)
    assert by_name(checks, "both in the corpus").value == pytest.approx(3 / pw.GOLD_ROWS_NEEDED)
    assert by_name(checks, "known act").value == pytest.approx(1 - 4053 / 7266)
    assert by_name(checks, "reaches before 2024").value == 0.0


def test_switches_and_files_move_the_lanes():
    on = pw.evaluate(facts(stubs={"search": False, "statute": False, "health": False, "authority": False}, qrels_queries=30, qrels_rows=900, gold_overrulings=6, tuned=True, results=True,
                           agreement=True, gold_rows=250, llm_labels=10, f1_report=True, doc_health_rows=100))
    assert by_name(on, "stubs.search").value == 1.0 and by_name(on, "stubs.statute").value == 1.0 and by_name(on, "stubs.health").value == 1.0
    assert by_name(on, "graded qrels").value == 1.0 and by_name(on, "weights tuned").value == 1.0 and by_name(on, "test-set results").value == 1.0
    assert by_name(on, "every provider real").value == 1.0
    lanes_on, overall_on = pw.score(on)
    lanes_off, overall_off = pw.score(pw.evaluate(facts()))
    assert overall_on > overall_off and lanes_on["M3"] > lanes_off["M3"] and lanes_on["M4"] > lanes_off["M4"]


def test_a_failing_test_in_a_lane_is_charged_to_that_lane_only():
    checks = pw.evaluate(facts(pytest={"failed": 2, "errors": 0, "summary": "2 failed", "failing_files": ["m2_statute/tests/test_x.py"]}))
    m2 = [c for c in checks if c.lane == "M2" and c.name == "its tests pass"][0]
    m3 = [c for c in checks if c.lane == "M3" and c.name == "its tests pass"][0]
    assert m2.value == 0.0 and m3.value == 1.0
    assert by_name(checks, "all tests pass").value == 0.0  # the whole suite is M4's gate


def test_lane_weights_sum_to_one_and_the_overall_is_their_weighted_mean():
    assert sum(pw.LANE_WEIGHT.values()) == pytest.approx(1.0)
    lanes, overall = pw.score(pw.evaluate(facts()))
    assert overall == pytest.approx(sum(lanes[k] * w for k, w in pw.LANE_WEIGHT.items())) and 0.0 <= overall <= 1.0


def test_every_unmet_check_names_what_is_needed_or_why():
    for c in pw.evaluate(facts()):
        assert c.weight > 0 and 0.0 <= c.value <= 1.0 and c.detail != ""


# ------------------------------------------------------------------------------------------------------------------ the report
def test_the_report_lists_each_lane_with_what_is_left_and_never_names_a_person():
    rep = pw.Report(when="2026-10-07 20:00", shas={"m1-index": "abc1234", "m2-statute": "def5678", "m3-treatment": "0123456", "m4-rank": "fedcba9", "main": "1111111"},
                    new={"m1-index": ["abc1234 Update the corpus"]})
    rep.facts = facts()
    rep.checks = pw.evaluate(rep.facts)
    rep.lanes, rep.overall = pw.score(rep.checks)
    text = pw.render(rep)
    for lane in ("M1", "M2", "M3", "M4"):
        assert f"### {lane}:" in text
    assert "Overall readiness" in text and "Update the corpus" in text and "report PDF" in text
    assert "nothing new" in text  # the lanes without new commits


# ------------------------------------------------------------------------------------------------------------------ git steps
needs_git = pytest.mark.skipif(shutil.which("git") is None, reason="git is not installed")


def g(cwd, *args):
    return subprocess.run(["git", "-C", str(cwd), "-c", "user.name=t", "-c", "user.email=t@example.invalid", *args], capture_output=True, text=True, check=True)


@needs_git
def test_new_commits_lists_subjects_only_and_caps_the_list(tmp_path):
    repo = tmp_path / "r"
    repo.mkdir()
    g(repo, "init", "-q", "-b", "base")
    (repo / "a.txt").write_text("a", encoding="utf-8")
    g(repo, "add", "-A")
    g(repo, "commit", "-qm", "first")
    g(repo, "checkout", "-q", "-b", "side")
    for i in range(10):
        (repo / "a.txt").write_text(str(i), encoding="utf-8")
        g(repo, "commit", "-qam", f"change {i}")
    subjects = pw.new_commits("side", "base", cwd=repo, limit=3)
    assert len(subjects) == 4 and subjects[0].endswith("change 9") and subjects[-1] == "... and 7 more"
    assert all("t@example" not in s for s in subjects)  # no author in the output
    assert pw.is_ancestor("base", "side", cwd=repo) and not pw.is_ancestor("side", "base", cwd=repo)
    assert pw.rev("side", cwd=repo) != "" and pw.rev("nope", cwd=repo) == ""


def test_the_report_shows_our_own_lane_as_it_is_locally_with_the_unpushed_count():
    rep = pw.Report(when="t", shas={"m4-rank": "abc1234"}, unpushed=3)
    rep.facts = facts()
    rep.checks = pw.evaluate(rep.facts)
    rep.lanes, rep.overall = pw.score(rep.checks)
    assert "`abc1234` (3 local commits not pushed)" in pw.render(rep)


def test_a_check_started_while_another_runs_reports_the_last_result_and_touches_nothing(tmp_path, monkeypatch):
    monkeypatch.setattr(pw, "WATCH", tmp_path)
    (tmp_path / "last_report.json").write_text('{"shas": {"m4-rank": "abc1234"}, "facts": {}}', encoding="utf-8")
    (tmp_path / "lock").write_text("123", encoding="utf-8")
    rep = pw.check_once()
    assert rep.skipped_audit and "another check is still running" in rep.applied and rep.shas == {"m4-rank": "abc1234"}
    assert (tmp_path / "lock").exists()  # the running check's lock is left alone
