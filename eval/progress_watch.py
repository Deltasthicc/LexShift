"""Progress watcher: fetch every branch, integrate what is new in a separate worktree, run the whole audit, say how close we are.

    python -m eval.progress_watch                 # one check: fetch, integrate, audit, report (heavy steps are skipped when nothing changed)
    python -m eval.progress_watch --apply         # also fast-forward the real m4-rank to the integrated result when that is safe
    python -m eval.progress_watch --every 600     # keep checking every 10 minutes until stopped
    python -m eval.progress_watch --force         # run the audit even if nothing changed
    python -m eval.progress_watch --json          # machine-readable report

What one check does:

1. `git fetch --all --prune`, then compares every lane's branch with the integration branch.
2. In a separate git worktree (`.watch/wt`, branch `integration/watch`, never pushed) it merges `m4-rank` and every lane's branch that has something new. A merge that
   conflicts is aborted and reported with its files; the rest still go in. Your own working tree is never touched.
3. Rebuilds what is derived (M1's index, M2's statute file) when the corpus changed, then runs: the tests, the smoke gate twice (as committed, and with search and
   statute real), `eval.conformance`, `eval.feasibility --target 10`, M3's extract stage, and `eval.submission_check`.
4. Scores every lane from those results (never from anyone's claim) and prints what is done, what is left, and what each lane still has to do.

`--apply` fast-forwards the checked-out `m4-rank` to the integration branch only if your working tree is clean, the checked-out branch is `m4-rank`, the merge is a
fast-forward, the tests did not get worse and the score did not drop. It commits nothing of its own and pushes nothing.

The score is the weighted share of the checks below that pass (the weights are in LANES, and a number such as "27 of 35 correct" earns partial credit). It measures
readiness for the submission, not retrieval quality, and the report PDF, the video and the clean-machine test are listed but not scored: nothing in the repository
can show them. Output goes to `.watch/` (git-ignored); no name of a person is ever written.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import os
import re
import subprocess
import sys
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
WATCH = ROOT / ".watch"
WT = WATCH / "wt"
BRANCH = "integration/watch"
LANE_BRANCHES = {"M1": "m1-index", "M2": "m2-statute", "M3": "m3-treatment", "M4": "m4-rank"}
OTHER_BRANCHES = ("main",)
LANE_WEIGHT = {"M1": 0.25, "M2": 0.20, "M3": 0.25, "M4": 0.30}
TARGET_CANDIDATES = 10  # candidate judgments per query that the evaluation needs (eval.feasibility --target)
GOLD_ROWS_NEEDED = 6
GOLD_SET_ROWS = 250  # m3_treatment gold sample size in its README
BENCH_TARGET = 0.9

# The doctrine pairs named in eval/examples/query_grade_criteria.example.md: (doctrine, overruled case, overruling case). Used only to see whether both ends are
# documents of the corpus; they are not labels and are never read by the system.
DOCTRINE_PAIRS = (
    ("section 377", r"Koushal", r"Navtej"),
    ("anticipatory bail", r"Salauddin", r"Sushila\s+Aggarwal"),
    ("section 498A", r"Rajesh\s+Sharma", r"Social\s+Action\s+Forum"),
    ("adultery", r"Sowmithri|Revathi", r"Joseph\s+Shine"),
    ("privacy", r"Jabalpur", r"Puttaswamy"),
    ("electronic evidence", r"Shafhi|Tomaso|Navjot\s+Sandhu", r"Arjun\s+Panditrao|Anvar"),
    ("NDPS section 67", r"Kanhaiyalal|Karwal", r"Tofan\s+Singh"),
    ("informant and investigator", r"Mohan\s+Lal", r"Mukesh\s+Singh"),
    ("stay after six months", r"Asian\s+Resurfacing", r"High\s+Court\s+Bar\s+Association"),
    ("attempt to commit suicide", r"Rathinam", r"Gian\s+Kaur"),
)


# --------------------------------------------------------------------------------------------------------------------- results
@dataclass
class Check:
    lane: str
    name: str
    weight: float
    value: float  # 0.0 to 1.0, partial credit allowed
    detail: str = ""
    owner_note: str = ""  # what the owner has to do when value < 1

    @property
    def missing(self) -> float:
        return self.weight * (1.0 - self.value)


@dataclass
class Report:
    when: str
    shas: dict[str, str]
    new: dict[str, list[str]] = field(default_factory=dict)  # lane branch -> subjects of commits not yet in the integration branch before this check
    merged: list[str] = field(default_factory=list)
    conflicts: dict[str, list[str]] = field(default_factory=dict)
    applied: str = ""
    unpushed: int = 0
    skipped_audit: bool = False
    facts: dict[str, Any] = field(default_factory=dict)
    checks: list[Check] = field(default_factory=list)
    lanes: dict[str, float] = field(default_factory=dict)
    overall: float = 0.0
    previous: dict[str, float] = field(default_factory=dict)


# --------------------------------------------------------------------------------------------------------------------- git and processes
def git(*args: str, cwd: Path = ROOT, timeout: int = 300) -> subprocess.CompletedProcess:
    return subprocess.run(["git", "-C", str(cwd), *args], capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=timeout)


def python_exe() -> str:
    for rel in (".venv/Scripts/python.exe", ".venv/bin/python"):
        if (ROOT / rel).exists():
            return str(ROOT / rel)
    return sys.executable


def run(cmd: list[str], cwd: Path, env: dict[str, str] | None = None, timeout: int = 900) -> tuple[int, str]:
    full_env = {**os.environ, "PYTHONIOENCODING": "utf-8", **(env or {})}
    try:
        proc = subprocess.run(cmd, cwd=cwd, env=full_env, capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=timeout)
    except subprocess.TimeoutExpired:
        return 124, f"timed out after {timeout} s"
    return proc.returncode, (proc.stdout or "") + (proc.stderr or "")


def is_ancestor(ancestor: str, descendant: str, cwd: Path = ROOT) -> bool:
    return git("merge-base", "--is-ancestor", ancestor, descendant, cwd=cwd).returncode == 0


def rev(ref: str, cwd: Path = ROOT) -> str:
    out = git("rev-parse", "--short", ref, cwd=cwd)
    return out.stdout.strip() if out.returncode == 0 else ""


# --------------------------------------------------------------------------------------------------------------------- integration
def fetch() -> None:
    git("fetch", "--all", "--prune", timeout=180)


def new_commits(ref: str, base: str, cwd: Path = ROOT, limit: int = 8) -> list[str]:
    """Subjects of the commits in `ref` that `base` does not have (no author: the report names lanes, never people)."""
    out = git("log", "--format=%h %s", f"{base}..{ref}", cwd=cwd)
    lines = [ln[:110] for ln in out.stdout.splitlines() if ln.strip()] if out.returncode == 0 else []
    return lines[:limit] + ([f"... and {len(lines) - limit} more"] if len(lines) > limit else [])


def ensure_worktree() -> str:
    """Create the integration worktree from the local m4-rank on first use; later runs reuse it."""
    WATCH.mkdir(exist_ok=True)
    if (WT / ".git").exists():
        return ""
    git("worktree", "prune")
    out = git("worktree", "add", "-B", BRANCH, str(WT), "m4-rank")
    return "" if out.returncode == 0 else out.stderr.strip()[:300]


def merge_into_worktree(ref: str) -> tuple[bool, list[str]]:
    out = git("merge", "--no-edit", ref, cwd=WT)
    if out.returncode == 0:
        return True, []
    files = git("diff", "--name-only", "--diff-filter=U", cwd=WT).stdout.split()
    git("merge", "--abort", cwd=WT)
    return False, files or [(out.stderr or out.stdout).strip()[:160]]


def integrate() -> tuple[list[str], dict[str, list[str]], str]:
    err = ensure_worktree()
    if err:
        return [], {"worktree": [err]}, ""
    merged: list[str] = []
    conflicts: dict[str, list[str]] = {}
    refs = [("m4-rank", "m4-rank")] + [(b, f"origin/{b}") for b in [*LANE_BRANCHES.values(), *OTHER_BRANCHES] if b != "m4-rank"]
    for name, ref in refs:
        if not rev(ref):
            continue
        if is_ancestor(ref, "HEAD", cwd=WT):
            continue
        ok, files = merge_into_worktree(ref)
        if ok:
            merged.append(name)
        else:
            conflicts[name] = files
    refresh_vendored()
    return merged, conflicts, rev("HEAD", cwd=WT)


def refresh_vendored() -> None:
    """A worktree made before .gitattributes marked the vendored files byte-exact holds line-ending-converted copies of them: rewrite those from HEAD."""
    import shutil

    for rel in ("app/web/static/vendor", "app/web/static/fonts"):
        shutil.rmtree(WT / rel, ignore_errors=True)  # git does not rewrite a file whose normalised content already matches, so remove first
    git("checkout", "HEAD", "--", "app/web/static/vendor", "app/web/static/fonts", cwd=WT)


def apply_to_m4_rank(report: Report, previous: dict[str, Any]) -> str:
    """Fast-forward the real m4-rank to the integration branch when that cannot hurt. Returns a sentence saying what happened."""
    head = git("rev-parse", "--abbrev-ref", "HEAD").stdout.strip()
    if head != "m4-rank":
        return f"not applied: the checked-out branch is {head or 'unknown'}, not m4-rank"
    if git("status", "--porcelain").stdout.strip():
        return "not applied: your working tree has uncommitted changes (commit or stash them first)"
    if not report.merged or rev(BRANCH) == rev("m4-rank") or is_ancestor(BRANCH, "m4-rank"):
        return "nothing to apply: the integration branch has nothing that m4-rank lacks"
    if not is_ancestor("m4-rank", BRANCH):
        return "not applied: m4-rank has moved since the integration branch was made (it will be merged in at the next check)"
    old_failed = previous.get("facts", {}).get("pytest", {}).get("failed", 0)
    new_failed = report.facts.get("pytest", {}).get("failed", 0)
    if new_failed > old_failed:
        return f"not applied: the tests got worse ({old_failed} failing before, {new_failed} now)"
    if previous.get("overall") is not None and report.overall + 1e-9 < previous["overall"]:
        return f"not applied: the score dropped ({previous['overall']:.1%} to {report.overall:.1%})"
    out = git("merge", "--ff-only", BRANCH)
    return "applied: m4-rank fast-forwarded to " + rev("HEAD") if out.returncode == 0 else "not applied: " + (out.stderr or out.stdout).strip()[:160]


# --------------------------------------------------------------------------------------------------------------------- parsers (pure)
def parse_pytest(text: str) -> dict[str, Any]:
    counts = {"passed": 0, "failed": 0, "xfailed": 0, "skipped": 0, "errors": 0}
    summary = ""
    for line in text.splitlines()[::-1]:
        if re.search(r"\b\d+ (passed|failed|error|errors|xfailed|skipped)\b", line):
            summary = line.strip()
            break
    for n, word in re.findall(r"(\d+) (passed|failed|xfailed|skipped|errors?)", summary):
        counts["errors" if word.startswith("error") else word] = int(n)
    failing = sorted(set(re.findall(r"^(?:FAILED|ERROR) (\S+?)(?:::| - |\s|$)", text, flags=re.M)))
    return {**counts, "summary": summary, "failing_files": failing}


def parse_smoke(text: str) -> dict[str, Any]:
    rows = re.findall(r"^\[(PASS|FAIL|SKIP|INFO)\]\s+(.*)$", text, flags=re.M)
    final = re.search(r"(\d+) failed, (\d+) skipped", text)
    return {"failed": int(final.group(1)) if final else None, "skipped": int(final.group(2)) if final else None,
            "lines": [(lvl, msg.strip()[:140]) for lvl, msg in rows], "stub_line": next((m for lvl, m in rows if lvl == "INFO" and "providers" in m), "")}


def find_fraction(findings: list[dict[str, str]], fragment: str, pattern: str = r"(\d+)\s*/\s*(\d+)") -> tuple[int, int] | None:
    for f in findings:
        if fragment in f.get("check", "") or fragment in f.get("detail", ""):
            m = re.search(pattern, f.get("check", "") + " " + f.get("detail", ""))
            if m:
                return int(m.group(1)), int(m.group(2))
    return None


def json_from(text: str) -> Any:
    """The JSON document in a command's output (other lines, such as warnings, may come first): it starts at a line holding only [ or {."""
    m = re.search(r"^[\[{]\s*$", text, flags=re.M)
    if not m:
        raise ValueError("no JSON in the output")
    return json.loads(text[m.start():])


def level_of(findings: list[dict[str, str]], fragment: str) -> str | None:
    for f in findings:
        if fragment in f.get("check", ""):
            return f.get("level")
    return None


def pairs_present(titles: list[str]) -> list[str]:
    """Doctrines for which both the overruled and the overruling judgment are documents of the corpus (matched on titles)."""
    found = []
    for doctrine, old, new in DOCTRINE_PAIRS:
        if any(re.search(old, t, re.I) for t in titles) and any(re.search(new, t, re.I) for t in titles):
            found.append(doctrine)
    return found


def bar(share: float, width: int = 20) -> str:
    share = max(0.0, min(1.0, share))
    filled = int(round(share * width))
    return "[" + "#" * filled + "." * (width - filled) + "]"


def ratio(a: float, b: float) -> float:
    return 0.0 if b <= 0 else max(0.0, min(1.0, a / b))


# --------------------------------------------------------------------------------------------------------------------- scoring (pure)
def evaluate(facts: dict[str, Any]) -> list[Check]:
    """Turn measured facts into checks. A fact that was not measured scores 0 and says so, so a broken audit can never look like progress."""
    f = facts
    c: list[Check] = []

    def add(lane: str, name: str, weight: float, value: float, detail: str, note: str = "") -> None:
        c.append(Check(lane, name, weight, max(0.0, min(1.0, value)), detail, note))

    stubs = f.get("stubs", {})
    corpus = f.get("corpus", {})
    feas = f.get("feasibility", {})
    conf = f.get("conformance", [])
    smoke_real = f.get("smoke_real", {})

    def smoke_ok(prefix: str) -> bool:
        return any(m.startswith(prefix) and lvl == "PASS" for lvl, m in smoke_real.get("lines", []))

    n_docs = corpus.get("documents", 0)
    n_queries = feas.get("queries", 30) or 30
    reach = len(feas.get("reach", [])) if feas else 0
    none = len(feas.get("none", [])) if feas else n_queries

    # ----------------------------------------------------------------------------------------------- M1
    add("M1", "judgments.jsonl matches the Judgment contract", 1, 1.0 if level_of(conf, "judgments.jsonl matches the Judgment contract") == "PASS" else 0.0, "from eval.conformance")
    add("M1", "search() passes the contract with the real module", 2, 1.0 if smoke_ok("search() contract") else 0.0, "smoke gate with search real",
        "make search() pass `LEXSHIFT_STUBS=health,authority python eval/smoke.py`")
    add("M1", "the index rebuilds from the repository", 1, 1.0 if f.get("index_build_rc") == 0 else 0.0, "python -m m1_index.index build")
    benches = find_fraction(conf, "benches of 3 or more judges are recorded")
    add("M1", "benches of 3 or more judges are recorded right", 1, ratio(*benches) if benches else 0.0, f"{benches[0]}/{benches[1]} right" if benches else "not measured",
        "fix bench_size from the coram line (an M3 bench check depends on it)")
    titles_bad = corpus.get("titles_cut", 0)
    add("M1", "case titles are whole", 1, 1.0 - ratio(titles_bad, n_docs) if n_docs else 0.0, f"{titles_bad} of {n_docs} titles end in 'v. v.'",
        "the title extractor drops the respondent when `v.` is on a line of its own")
    add("M1", f"queries with at least {TARGET_CANDIDATES} candidate judgments", 3, ratio(reach, n_queries) if feas else 0.0, f"{reach} of {n_queries}",
        "grow the corpus: older judgments plus the judgments the 30 queries' words find (eval.feasibility --target 10)")
    add("M1", "no query without any matching judgment", 1, 1.0 - ratio(none, n_queries) if feas else 0.0, f"{none} queries have none")
    first_year = corpus.get("first_year")
    add("M1", "the corpus reaches before 2024 (IPC-era precedents)", 1, 1.0 if first_year and first_year < 2024 else 0.0, f"earliest year {first_year}",
        "add 2010 to 2023 judgments, including the cases the doctrine queries name")
    pairs = corpus.get("pairs", [])
    add("M1", f"overruled and overruling judgments both in the corpus (target {GOLD_ROWS_NEEDED} doctrines)", 2, ratio(len(pairs), GOLD_ROWS_NEEDED), f"{len(pairs)} of {len(DOCTRINE_PAIRS)}: {', '.join(pairs) or 'none'}",
        "add both judgments of each doctrine query (eval/examples/query_grade_criteria.example.md)")
    add("M1", "stubs.search is switched off", 1, 0.0 if stubs.get("search", True) else 1.0, f"search: {stubs.get('search')}", "flip it in the commit that makes search() pass smoke")
    add("M1", "tests of its own", 1, 1.0 if f.get("m1_tests") else 0.0, "tests/test_m1*.py or m1_index/tests", "add tests for the parser, the index and search()")
    add("M1", "lnc.ltc is implemented", 1, 1.0 if f.get("lnc_ltc") else 0.0, "m1_index/scoring.py", "implement lnc.ltc or take it off the list")

    # ----------------------------------------------------------------------------------------------- M2
    add("M2", "statute_map.csv matches the contract", 1, 0.0 if level_of(conf, "statute_map.csv matches the contract") == "FAIL" else (1.0 if f.get("map_rows", 0) else 0.0), f"{f.get('map_rows', 0)} rows")
    forms = find_fraction(conf, "parse_query reads the statute forms")
    add("M2", "parse_query reads the Build Guide's statute forms", 2, ratio(*forms) if forms else (1.0 if level_of(conf, "parse_query reads the statute forms") == "PASS" else 0.0),
        f"{forms[0]}/{forms[1]} read" if forms else "all read" if level_of(conf, "parse_query reads the statute forms") == "PASS" else "not measured", "read the failing forms listed by eval.conformance --module m2")
    add("M2", "a bare section number takes its code from the offence date", 2, 1.0 if level_of(conf, "a bare section number takes its code from the offence date") == "PASS" else 0.0,
        "section 103 dated 2020 and 2025", "give the section the resolved act, not UNKNOWN")
    unk = f.get("unknown_act", {})
    add("M2", "references with a known act", 1, 1.0 - ratio(unk.get("unknown", 0), unk.get("total", 0)) if unk.get("total") else 0.0, f"{unk.get('unknown', 0)} of {unk.get('total', 0)} references have act UNKNOWN")
    add("M2", "continuity() passes the contract with the real module", 1, 1.0 if smoke_ok("continuity() contract") else 0.0, "smoke gate with statute real")
    add("M2", "20 or more mapped sections, from official sources", 1, 0.5 * ratio(f.get("map_rows", 0), 20) + 0.5 * ratio(f.get("map_official", 0), max(1, f.get("map_rows", 0))),
        f"{f.get('map_rows', 0)} rows, {f.get('map_official', 0)} cite an official source", "cite MHA or PRS tables in the source column")
    add("M2", "the statute file builds", 1, 1.0 if f.get("statute_build_rc") == 0 else 0.0, "python -m m2_statute.extractor build")
    add("M2", "its tests pass", 1, 0.0 if any("m2_statute" in p or "statute" in p for p in f.get("pytest", {}).get("failing_files", [])) else 1.0 if f.get("pytest") else 0.0, "pytest")
    add("M2", "stubs.statute is switched off", 1, 0.0 if stubs.get("statute", True) else 1.0, f"statute: {stubs.get('statute')}", "flip it in the commit that makes continuity() pass smoke")

    # ----------------------------------------------------------------------------------------------- M3
    add("M3", "its tests pass", 1, 0.0 if any("m3" in p for p in f.get("pytest", {}).get("failing_files", [])) else 1.0 if f.get("pytest") else 0.0, "pytest")
    m3 = f.get("m3_extract", {})
    add("M3", "extract and resolve run on the corpus", 1, 1.0 if m3.get("rc") == 0 else 0.0, f"{m3.get('mentions', 0)} mentions, {m3.get('resolved', 0)} resolved ({m3.get('resolved_pct', 0)}%)")
    add("M3", "appeal-history tags are plausible (at most 5% of mentions)", 1, 1.0 if m3.get("appeal_pct", 100) <= 5 else 0.0, f"{m3.get('appeal', 0)} tagged ({m3.get('appeal_pct', 0)}%)",
        "check the own-title test on the records whose title is cut (M1) and on the 2024 formatting")
    add("M3", f"hand-labelled gold set ({GOLD_SET_ROWS} windows)", 2, ratio(f.get("gold_rows", 0), GOLD_SET_ROWS), f"{f.get('gold_rows', 0)} rows in data/treatment_gold.csv", "label the sheets (m3_treatment/LABELLING_GUIDE.md) with two labellers")
    add("M3", "Gemini labels exist", 1, 1.0 if f.get("llm_labels", 0) > 0 else 0.0, f"{f.get('llm_labels', 0)} cached labels", "run `python -m m3_treatment.pipeline label-llm`")
    add("M3", "classifier F1 table exists", 1, 1.0 if f.get("f1_report") else 0.0, "m3_treatment/reports/classifier_f1.md", "run `python -m m3_treatment.pipeline evaluate` against the gold set")
    add("M3", "citations.jsonl and doc_health.jsonl cover the corpus", 2, ratio(f.get("doc_health_rows", 0), n_docs) if n_docs else 0.0, f"{f.get('doc_health_rows', 0)} of {n_docs} judgments",
        "build and commit them (`data/processed` is ignored: force-add or ship the label cache and a build step in CI)")
    add("M3", "health() and authority() pass the contract with real data", 1, 1.0 if smoke_ok("health() contract") and smoke_ok("authority() contract") and f.get("doc_health_rows", 0) else 0.0, "smoke gate with everything real")
    add("M3", "stubs.health and stubs.authority are switched off", 1, 0.0 if stubs.get("health", True) or stubs.get("authority", True) else 1.0, f"health: {stubs.get('health')}, authority: {stubs.get('authority')}")

    # ----------------------------------------------------------------------------------------------- M4
    py = f.get("pytest", {})
    add("M4", "all tests pass", 3, 1.0 if py and py.get("failed", 1) == 0 and py.get("errors", 1) == 0 else 0.0, py.get("summary", "not measured"))
    add("M4", "the merge gate passes (smoke as committed)", 1, 1.0 if f.get("smoke", {}).get("failed") == 0 else 0.0, f"{f.get('smoke', {}).get('failed')} failed")
    add("M4", "30 judged queries, 10 dev and 20 test", 1, 1.0 if f.get("queries") == 30 else ratio(f.get("queries", 0), 30), f"{f.get('queries', 0)} queries")
    add("M4", "graded qrels cover every query", 3, ratio(f.get("qrels_queries", 0), 30), f"{f.get('qrels_rows', 0)} grades over {f.get('qrels_queries', 0)} queries",
        "pool (needs all four modules real), grade with two judges, then make_qrels")
    add("M4", "judge agreement reported", 1, 1.0 if f.get("agreement") else 0.0, "eval/judging/<round>/agreement.md")
    add("M4", f"gold overruling list ({GOLD_ROWS_NEEDED} or more rows)", 2, ratio(f.get("gold_overrulings", 0), GOLD_ROWS_NEEDED), f"{f.get('gold_overrulings', 0)} rows", "write it by hand, each row verified in the judgments")
    add("M4", "weights tuned on dev", 1, 1.0 if f.get("tuned") else 0.0, "common/weights_tuned.yaml")
    add("M4", "test-set results (table, per-query CSV, chart)", 2, 1.0 if f.get("results") else 0.0, "eval/results/ablation_test.*")
    add("M4", "every provider real (pooling and evaluation need it)", 1, sum(0 if stubs.get(k, True) else 1 for k in ("search", "statute", "health", "authority")) / 4, f"{sum(0 if stubs.get(k, True) else 1 for k in ('search', 'statute', 'health', 'authority'))} of 4 switched off")
    audit = f.get("audit", {})
    add("M4", "the submission audit has no FAIL", 1, 1.0 if audit and audit.get("FAIL", 1) == 0 else 0.0, f"{audit.get('PASS', 0)} pass, {audit.get('TODO', 0)} to do, {audit.get('FAIL', 0)} fail")
    return c


def score(checks: list[Check]) -> tuple[dict[str, float], float]:
    lanes: dict[str, float] = {}
    for lane in LANE_WEIGHT:
        mine = [k for k in checks if k.lane == lane]
        total = sum(k.weight for k in mine)
        lanes[lane] = sum(k.weight * k.value for k in mine) / total if total else 0.0
    overall = sum(lanes[lane] * w for lane, w in LANE_WEIGHT.items())
    return lanes, overall


# --------------------------------------------------------------------------------------------------------------------- facts (I/O)
def read_csv_rows(path: Path) -> list[dict[str, str]]:
    if not path.is_file():
        return []
    with path.open(encoding="utf-8-sig", newline="") as fh:
        return [r for r in csv.DictReader(fh) if any((v or "").strip() for v in r.values())]


def count_lines(path: Path) -> int:
    if not path.is_file():
        return 0
    with path.open(encoding="utf-8", errors="replace") as fh:
        return sum(1 for ln in fh if ln.strip())


def corpus_facts(path: Path) -> dict[str, Any]:
    docs = []
    if path.is_file():
        for line in path.open(encoding="utf-8"):
            if line.strip():
                try:
                    docs.append(json.loads(line))
                except json.JSONDecodeError:
                    pass
    years = sorted(int(d["date"][:4]) for d in docs if str(d.get("date", ""))[:4].isdigit())
    titles = [str(d.get("title") or "") for d in docs]
    return {"documents": len(docs), "first_year": years[0] if years else None, "last_year": years[-1] if years else None,
            "years": {str(y): years.count(y) for y in sorted(set(years))}, "titles_cut": sum(1 for t in titles if re.search(r"\bv\.\s+v\.\s*$", t)),
            "pairs": pairs_present(titles)}


def collect(wt: Path, py: str, state: dict[str, Any], force_build: bool) -> dict[str, Any]:
    facts: dict[str, Any] = {}
    import yaml

    cfg = yaml.safe_load((wt / "common" / "config.yaml").read_text(encoding="utf-8"))
    facts["stubs"] = {k: bool(v) for k, v in (cfg.get("stubs") or {}).items()}
    judgments = wt / "data" / "processed" / "judgments.jsonl"
    if not judgments.is_file() and (wt / "data" / "corpus" / "judgments.jsonl.xz").is_file():
        run([py, "-m", "m1_index.ingest", "unpack"], wt, timeout=600)  # a fresh checkout holds the corpus packed, as a clone does
    facts["corpus"] = corpus_facts(judgments)
    digest = hashlib.sha1(judgments.read_bytes()).hexdigest() if judgments.is_file() else ""
    rebuild = force_build or state.get("built_for") != digest or not (wt / "data" / "processed" / "index" / "index.pkl.gz").exists()
    if rebuild:
        facts["index_build_rc"], _ = run([py, "-m", "m1_index.index", "build"], wt, timeout=600)
        facts["statute_build_rc"], _ = run([py, "-m", "m2_statute.extractor", "build"], wt, timeout=600)
        state["built_for"] = digest if facts["index_build_rc"] == 0 else ""
        state["index_rc"], state["statute_rc"] = facts["index_build_rc"], facts["statute_build_rc"]
    else:
        facts["index_build_rc"], facts["statute_build_rc"] = state.get("index_rc", 0), state.get("statute_rc", 0)

    rc, out = run([py, "-m", "pytest", "-p", "no:cacheprovider"], wt, timeout=1500)
    facts["pytest"] = parse_pytest(out)
    facts["smoke"] = parse_smoke(run([py, "eval/smoke.py"], wt, timeout=600)[1])
    facts["smoke_real"] = parse_smoke(run([py, "eval/smoke.py"], wt, {"LEXSHIFT_STUBS": "health,authority"}, timeout=600)[1])
    rc, out = run([py, "-m", "eval.conformance", "--json"], wt, timeout=900)
    try:
        facts["conformance"] = [x for x in json_from(out) if isinstance(x, dict)]
    except ValueError:
        facts["conformance"] = []
    rc, out = run([py, "-m", "eval.feasibility", "--json", "--target", str(TARGET_CANDIDATES)], wt, {"LEXSHIFT_STUBS": "statute,health,authority"}, timeout=900)
    try:
        data = json_from(out)
        t = data.get("target", {})
        facts["feasibility"] = {"queries": len(data["rows"]), "reach": t.get("reach", []), "below": t.get("below", []), "none": t.get("none", []),
                                "size_for_median": t.get("size_for_median"), "size_for_share": t.get("size_for_share"),
                                "verdicts": {v: sum(1 for r in data["rows"] if r["verdict"] == v) for v in ("ok", "thin", "empty")}}
    except ValueError:
        facts["feasibility"] = {}
    rc, out = run([py, "-m", "eval.submission_check", "--json"], wt, timeout=300)
    try:
        items = json_from(out)
        facts["audit"] = {lvl: sum(1 for i in items if i["level"] == lvl) for lvl in ("PASS", "TODO", "MANUAL", "FAIL")}
        facts["audit_todo"] = [i["check"] for i in items if i["level"] == "TODO"][:12]
    except ValueError:
        facts["audit"] = {}

    facts["m3_extract"] = m3_extract(wt, py, state, digest)
    facts.update(file_facts(wt))
    return facts


def m3_extract(wt: Path, py: str, state: dict[str, Any], digest: str) -> dict[str, Any]:
    """M3's extract and resolve stage on the corpus, writing into .watch (never into the worktree's tracked report files)."""
    import yaml

    key = f"{digest}:{rev('HEAD', cwd=wt)}"
    if state.get("m3_key") == key and state.get("m3"):
        return state["m3"]
    out_dir = WATCH / "m3"
    out_dir.mkdir(parents=True, exist_ok=True)
    cfg = yaml.safe_load((wt / "common" / "config.yaml").read_text(encoding="utf-8"))
    cfg["m3_treatment"]["mentions"] = str(out_dir / "m3_mentions.jsonl")
    cfg["m3_treatment"]["reports_dir"] = str(out_dir / "reports")
    cfg_path = out_dir / "config.yaml"
    cfg_path.write_text(yaml.safe_dump(cfg, sort_keys=False), encoding="utf-8")
    rc, out = run([py, "-m", "m3_treatment.pipeline", "extract"], wt, {"LEXSHIFT_CONFIG": str(cfg_path)}, timeout=900)
    res = {"rc": rc}

    def grab(label: str) -> int:
        m = re.search(rf"\|\s*{re.escape(label)}[^|]*\|\s*([\d,]+)\s*\|", out)
        return int(m.group(1).replace(",", "")) if m else 0

    mentions, resolved, appeal = grab("Mentions (all kinds)"), grab("Resolved to a corpus judgment"), grab("Tagged appeal history")
    res.update({"mentions": mentions, "resolved": resolved, "appeal": appeal, "edges": grab("Distinct citing"),
                "resolved_pct": round(100 * resolved / mentions, 1) if mentions else 0, "appeal_pct": round(100 * appeal / mentions, 1) if mentions else 100})
    state["m3_key"], state["m3"] = key, res
    return res


def file_facts(wt: Path) -> dict[str, Any]:
    f: dict[str, Any] = {}
    f["queries"] = count_lines(wt / "eval" / "queries.jsonl")
    qrels = read_csv_rows_tsv(wt / "eval" / "qrels.tsv")
    f["qrels_rows"], f["qrels_queries"] = len(qrels), len({r.get("qid") for r in qrels})
    f["gold_overrulings"] = len(read_csv_rows(wt / "eval" / "gold_overrulings.csv"))
    f["agreement"] = bool(list((wt / "eval" / "judging").glob("*/agreement.md"))) if (wt / "eval" / "judging").is_dir() else False
    f["tuned"] = (wt / "common" / "weights_tuned.yaml").is_file()
    f["results"] = all((wt / "eval" / "results" / n).is_file() for n in ("ablation_test.csv", "per_query_test.csv", "ablation_test.md", "ablation_test.png"))
    rows = read_csv_rows(wt / "data" / "statute_map.csv")
    f["map_rows"] = len(rows)
    f["map_official"] = sum(1 for r in rows if re.search(r"mha\.gov|prsindia|egazette|gov\.in", r.get("source", ""), re.I))
    unk = tot = 0
    ds = wt / "data" / "processed" / "doc_statutes.jsonl"
    if ds.is_file():
        for line in ds.open(encoding="utf-8"):
            if line.strip():
                for ref in json.loads(line).get("refs", []):
                    tot += 1
                    unk += ref.get("act") == "UNKNOWN"
    f["unknown_act"] = {"unknown": unk, "total": tot}
    f["gold_rows"] = len(read_csv_rows(wt / "data" / "treatment_gold.csv"))
    f["llm_labels"] = max(count_lines(wt / "data" / "llm_labels" / "m3_llm_labels.jsonl"), count_lines(wt / "data" / "cache" / "m3_llm_labels.jsonl"))
    f["f1_report"] = (wt / "m3_treatment" / "reports" / "classifier_f1.md").is_file()
    f["doc_health_rows"] = count_lines(wt / "data" / "processed" / "doc_health.jsonl")
    f["m1_tests"] = bool(list((wt / "tests").glob("test_m1*.py")) or list((wt / "m1_index").glob("tests/*.py")))
    scoring = wt / "m1_index" / "scoring.py"
    body = scoring.read_text(encoding="utf-8").split("def lnc_ltc_scores")[-1].split("\ndef ")[0] if scoring.is_file() and "def lnc_ltc_scores" in scoring.read_text(encoding="utf-8") else "not_implemented("
    f["lnc_ltc"] = "not_implemented(" not in body
    return f


def read_csv_rows_tsv(path: Path) -> list[dict[str, str]]:
    if not path.is_file():
        return []
    with path.open(encoding="utf-8-sig", newline="") as fh:
        return [r for r in csv.DictReader(fh, delimiter="\t") if any((v or "").strip() for v in r.values())]


# --------------------------------------------------------------------------------------------------------------------- report
def render(rep: Report) -> str:
    out = [f"# LexShift progress check, {rep.when}", ""]
    out.append("## Branches")
    out.append("| Branch | Now | New since the integration branch had it |")
    out.append("|---|---|---|")
    for lane, branch in {**LANE_BRANCHES, "main": "main"}.items():
        subjects = rep.new.get(branch, [])
        local = f" ({rep.unpushed} local commits not pushed)" if branch == "m4-rank" and rep.unpushed else ""
        out.append(f"| {lane if lane != 'main' else 'main'} (`{branch}`) | `{rep.shas.get(branch, '?')}`{local} | " + (("<br>".join(subjects)) if subjects else "nothing new") + " |")
    if rep.merged:
        out.append("")
        out.append("Integrated into the audit branch: " + ", ".join(rep.merged) + ".")
    for b, files in rep.conflicts.items():
        out.append(f"**Conflict, not merged:** `{b}` ({', '.join(files[:6])}). Someone has to resolve it by hand.")
    if rep.applied:
        out.append("")
        out.append("m4-rank: " + rep.applied + ".")
    f = rep.facts
    if rep.skipped_audit:
        out += ["", "Nothing changed since the last audit, so the numbers below are the last measured ones."]
    out += ["", "## Progress", "", f"**Overall readiness: {rep.overall:.0%}**  {bar(rep.overall, 30)}" + (f"  ({rep.overall - rep.previous.get('overall', rep.overall):+.1%} since the last check)" if rep.previous.get("overall") is not None else ""), ""]
    out.append("| Lane | Ready | |")
    out.append("|---|---|---|")
    for lane, share in rep.lanes.items():
        delta = f" ({share - rep.previous['lanes'][lane]:+.0%})" if rep.previous.get("lanes") and lane in rep.previous["lanes"] and abs(share - rep.previous["lanes"][lane]) > 1e-9 else ""
        out.append(f"| {lane} | {share:.0%}{delta} | `{bar(share)}` |")
    py, sm, sr = f.get("pytest", {}), f.get("smoke", {}), f.get("smoke_real", {})
    feas, audit, corpus = f.get("feasibility", {}), f.get("audit", {}), f.get("corpus", {})
    out += ["", "## Gates", "",
            f"* Tests: {py.get('summary') or 'not measured'}" + (f" (failing: {', '.join(py['failing_files'][:5])})" if py.get("failing_files") else ""),
            f"* Smoke as committed: {sm.get('failed')} failed; with search and statute real: {sr.get('failed')} failed",
            f"* Corpus: {corpus.get('documents', 0)} judgments, years {', '.join(f'{y}: {n}' for y, n in corpus.get('years', {}).items()) or 'none'}",
            f"* Queries with at least {TARGET_CANDIDATES} candidate judgments: {len(feas.get('reach', []))} of {feas.get('queries', 0)}; none at all: {len(feas.get('none', []))}"
            + (f"; by random sampling the median query would need about {round(feas['size_for_median'], -2):,.0f} judgments" if feas.get("size_for_median") else ""),
            f"* Submission audit: {audit.get('PASS', 0)} pass, {audit.get('TODO', 0)} to do, {audit.get('MANUAL', 0)} by hand, {audit.get('FAIL', 0)} FAIL"]
    out += ["", "## What each lane still has to do", ""]
    for lane in LANE_WEIGHT:
        mine = sorted((k for k in rep.checks if k.lane == lane and k.value < 1.0), key=lambda k: -k.missing)
        done = sum(1 for k in rep.checks if k.lane == lane and k.value >= 1.0)
        total = sum(1 for k in rep.checks if k.lane == lane)
        out.append(f"### {lane}: {rep.lanes.get(lane, 0):.0%}, {done} of {total} checks met")
        if not mine:
            out.append("* nothing left that the repository can check")
        for k in mine[:6]:
            note = f" Needed: {k.owner_note}." if k.owner_note else ""
            out.append(f"* **{k.name}** ({k.value:.0%}): {k.detail}.{note}")
        if len(mine) > 6:
            out.append(f"* ... and {len(mine) - 6} smaller items")
        out.append("")
    out.append("Not scored, by hand: the report PDF, the demo video, the clean-machine test, the review of every AI-log entry, and the choice of corpus additions.")
    out.append("")
    out.append("The score is the weighted share of checks that pass (partial credit for counts). It measures readiness for the submission, not retrieval quality; nothing here is a retrieval result.")
    return "\n".join(out)


# --------------------------------------------------------------------------------------------------------------------- one check
def load_json(path: Path) -> dict[str, Any]:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def check_once(apply: bool = False, force: bool = False, no_integrate: bool = False) -> Report:
    """One check, under a lock: a second check started while one is running (the scheduled one and a manual one) reports the last result instead of touching the worktree."""
    WATCH.mkdir(exist_ok=True)
    lock = WATCH / "lock"
    if lock.exists() and time.time() - lock.stat().st_mtime < 1800:
        last = load_json(WATCH / "last_report.json")
        rep = Report(when=time.strftime("%Y-%m-%d %H:%M"), shas=last.get("shas", {}), skipped_audit=True, facts=last.get("facts", {}),
                     applied="skipped: another check is still running, so these are the last measured numbers")
        rep.checks = evaluate(rep.facts)
        rep.lanes, rep.overall = score(rep.checks)
        return rep
    lock.write_text(str(os.getpid()), encoding="utf-8")
    try:
        return _check_once(apply, force, no_integrate)
    finally:
        lock.unlink(missing_ok=True)


def _check_once(apply: bool, force: bool, no_integrate: bool) -> Report:
    state = load_json(WATCH / "state.json")
    previous = load_json(WATCH / "last_report.json")
    fetch()
    before = {b: rev(f"origin/{b}") or rev(b) for b in [*LANE_BRANCHES.values(), "main"]}
    before["m4-rank"] = rev("m4-rank")  # our own lane is shown as it is here, which may be ahead of what was pushed
    shas = dict(before)
    ahead = git("rev-list", "--count", "origin/m4-rank..m4-rank")
    unpushed = int(ahead.stdout.strip() or 0) if ahead.returncode == 0 else 0
    new: dict[str, list[str]] = {}
    base = BRANCH if rev(BRANCH) else "m4-rank"
    for b in [*LANE_BRANCHES.values(), "main"]:
        ref = b if b == "m4-rank" else f"origin/{b}"
        subjects = new_commits(ref, base) if rev(ref) else []
        if subjects:
            new[b] = subjects
    rep = Report(when=time.strftime("%Y-%m-%d %H:%M"), shas=shas, new=new, unpushed=unpushed)

    if no_integrate:
        rep.facts, rep.checks = previous.get("facts", {}), []
        return rep
    rep.merged, rep.conflicts, head = integrate()
    key = f"{head}:{rev('m4-rank')}"
    if not force and previous.get("key") == key and previous.get("facts"):
        rep.skipped_audit, rep.facts = True, previous["facts"]
    else:
        rep.facts = collect(WT, python_exe(), state, force_build=False)
        state["last_key"] = key
    rep.checks = evaluate(rep.facts)
    rep.lanes, rep.overall = score(rep.checks)
    rep.previous = {"overall": previous.get("overall"), "lanes": previous.get("lanes", {}), "facts": previous.get("facts", {})} if previous else {}
    if apply:
        rep.applied = apply_to_m4_rank(rep, rep.previous)
    (WATCH / "state.json").write_text(json.dumps(state, indent=1), encoding="utf-8")
    saved = {"when": rep.when, "key": key, "overall": rep.overall, "lanes": rep.lanes, "facts": rep.facts, "shas": rep.shas}
    (WATCH / "last_report.json").write_text(json.dumps(saved, indent=1, default=str), encoding="utf-8")
    with (WATCH / "history.jsonl").open("a", encoding="utf-8") as fh:
        fh.write(json.dumps({"when": rep.when, "overall": round(rep.overall, 4), "lanes": {k: round(v, 4) for k, v in rep.lanes.items()}, "shas": rep.shas}) + "\n")
    (WATCH / "latest.md").write_text(render(rep), encoding="utf-8")
    return rep


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--apply", action="store_true", help="fast-forward the real m4-rank to the integration branch when that is safe")
    ap.add_argument("--force", action="store_true", help="run the audit even if nothing changed")
    ap.add_argument("--every", type=int, default=0, metavar="SECONDS", help="repeat until stopped")
    ap.add_argument("--json", action="store_true", help="print the report as JSON")
    ap.add_argument("--no-integrate", action="store_true", help="only fetch and list what is new (no worktree, no audit)")
    args = ap.parse_args(argv)
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(errors="replace")
    while True:
        rep = check_once(apply=args.apply, force=args.force, no_integrate=args.no_integrate)
        if args.json:
            print(json.dumps({**asdict(rep), "checks": [asdict(c) for c in rep.checks]}, indent=1, default=str))
        else:
            print(render(rep) if not args.no_integrate else chr(10).join(f"{b} {rep.shas.get(b, '?')}: " + ("; ".join(rep.new[b]) if rep.new.get(b) else "nothing new") for b in rep.shas))
        sys.stdout.flush()
        if not args.every:
            return 0
        time.sleep(args.every)


if __name__ == "__main__":
    sys.exit(main())
