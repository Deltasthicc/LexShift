"""Pre-submission audit: the machine-checkable items of docs/SUBMISSION_CHECKLIST.md in one command.

    python -m eval.submission_check            # fast file checks; exit 1 if something is wrong (FAIL)
    python -m eval.submission_check --run      # also run pytest, both smoke tests, check_data --strict and the demo (slow)
    python -m eval.submission_check --strict   # TODO items fail as well (use it on the day you submit)
    python -m eval.submission_check --json

Levels. PASS: the item holds. TODO: not done yet, nothing is broken (for example the hand-made judgements do not exist). FAIL: a
rule is broken (a stub result file in eval/results, a key in a tracked file, a banned phrase in the page, a missing
not-legal-advice note, a tracked file over GitHub's 100 MB limit). MANUAL: a person has to do or check it (the clean-machine test, the
video, the report); the audit lists it so it is not forgotten.

The audit reads files; it never changes one, never calls the network and never makes a number. A PASS on "results present" says the
files exist, not that the results are good.
"""

from __future__ import annotations

import argparse
import csv
import json
import os
import re
import subprocess
import sys
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Callable, Iterable

ROOT = Path(__file__).resolve().parents[1]
LEVELS = ("PASS", "TODO", "MANUAL", "FAIL")

PLAN = {"dev": 10, "test": 20}  # Build Guide, M4 block
RESULT_FILES = ("ablation_test.csv", "per_query_test.csv", "ablation_test.md", "ablation_test.png")
BANNED = re.compile(r"\b(?:dead|bad)\s+law\b", re.I)
SECRETS = (
    ("Google API key", re.compile(r"AIza[0-9A-Za-z_\-]{35}")),
    ("OpenAI-style key", re.compile(r"\bsk-[A-Za-z0-9_\-]{20,}")),
    ("AWS access key id", re.compile(r"\bAKIA[0-9A-Z]{16}\b")),
    ("private key block", re.compile(r"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----")),
    ("key or token assigned a literal", re.compile(r"(?i)\b(?:api[_-]?key|secret|access[_-]?token|auth[_-]?token)\b\s*[:=]\s*['\"][A-Za-z0-9_\-]{20,}['\"]")),
)
TEXT_SUFFIXES = {".py", ".md", ".yaml", ".yml", ".txt", ".csv", ".tsv", ".json", ".js", ".html", ".css", ".cfg", ".toml", ".ini", ".env", ""}
SKIP_SCAN = ("app/web/static/vendor/", "app/web/static/fonts/")
MAX_SCAN_BYTES = 3_000_000
GITHUB_LIMIT = 100 * 1024 * 1024
WARN_SIZE = 50 * 1024 * 1024
LAPTOP_TARGET = 2 * 1024 ** 3


@dataclass
class Item:
    group: str
    level: str  # PASS | TODO | MANUAL | FAIL
    check: str
    detail: str = ""


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8", errors="replace")


def _rows(path: Path, delimiter: str) -> list[dict[str, str]]:
    with path.open(encoding="utf-8-sig", newline="") as fh:
        return [row for row in csv.DictReader(fh, delimiter=delimiter) if any((v or "").strip() for v in row.values())]


def git(root: Path, *args: str) -> str | None:
    """Output of a git command in `root`, or None when git is missing or `root` is not itself the top of a repository.

    A folder inside some other repository (a scratch folder under a checkout, say) must not be audited as if it were that repository."""
    def run(*a: str) -> str | None:
        try:
            proc = subprocess.run(["git", "-C", str(root), *a], capture_output=True, text=True, timeout=60)
        except (OSError, subprocess.SubprocessError):
            return None
        return proc.stdout if proc.returncode == 0 else None

    top = run("rev-parse", "--show-toplevel")
    if top is None or Path(top.strip()).resolve() != root.resolve():
        return None
    return run(*args)


def tracked_files(root: Path) -> list[str] | None:
    out = git(root, "ls-files", "-z")
    return None if out is None else [p for p in out.split("\0") if p]


def stub_switches(root: Path) -> dict[str, bool]:
    """The `stubs:` block of config.yaml as written (the environment override is ignored: a clean clone has none)."""
    import yaml

    cfg = yaml.safe_load(_read(root / "common" / "config.yaml")) or {}
    return {k: bool(v) for k, v in (cfg.get("stubs") or {}).items()}


# --------------------------------------------------------------------------------------------------------------- checks
def check_stubs(root: Path) -> list[Item]:
    flags = stub_switches(root)
    still = sorted(k for k, v in flags.items() if v)
    if not flags:
        return [Item("repository", "FAIL", "stub switches", "common/config.yaml has no `stubs:` block")]
    if still:
        return [Item("repository", "TODO", "every provider is real", "still stubs in config.yaml: " + ", ".join(still)
                     + " (each owner flips theirs in the commit that makes their function pass the smoke test)")]
    return [Item("repository", "PASS", "every provider is real", "no `stubs:` switch is true")]


def check_tuned_weights(root: Path) -> list[Item]:
    path = root / "common" / "weights_tuned.yaml"
    if path.is_file():
        return [Item("repository", "PASS", "tuned weights committed", "common/weights_tuned.yaml exists (tuned on dev; see the ablation output)")]
    return [Item("repository", "TODO", "tuned weights committed", "common/weights_tuned.yaml does not exist: run `python -m eval.run_ablation --tune`")]


def check_eval_inputs(root: Path) -> list[Item]:
    out: list[Item] = []
    qpath, rpath, gpath = root / "eval" / "queries.jsonl", root / "eval" / "qrels.tsv", root / "eval" / "gold_overrulings.csv"

    queries: list[dict] = []
    if qpath.is_file():
        for n, line in enumerate(_read(qpath).splitlines(), 1):
            if not line.strip():
                continue
            try:
                queries.append(json.loads(line))
            except json.JSONDecodeError:
                return [Item("evaluation inputs", "FAIL", "queries.jsonl", f"line {n} is not valid JSON")]
    if not queries:
        out.append(Item("evaluation inputs", "TODO", "judged queries", "eval/queries.jsonl is empty: write them by hand (eval/JUDGING_GUIDE.md)"))
    else:
        by_split = {s: sum(1 for q in queries if q.get("split") == s) for s in PLAN}
        types = {q.get("type") for q in queries}
        gaps = [f"{by_split[s]} {s} (plan {n})" for s, n in PLAN.items() if by_split[s] != n]
        missing = [t for t in "ABCD" if t not in types]
        if gaps or missing:
            out.append(Item("evaluation inputs", "TODO", "judged queries match the plan",
                            f"{len(queries)} queries: " + "; ".join(gaps + ([f"no type {', '.join(missing)}"] if missing else []))))
        else:
            out.append(Item("evaluation inputs", "PASS", "judged queries match the plan", f"{len(queries)} queries, 10 dev and 20 test, all four types"))

    qrels = _rows(rpath, "\t") if rpath.is_file() else []
    judged = {r.get("qid") for r in qrels}
    if not qrels:
        out.append(Item("evaluation inputs", "TODO", "graded qrels", "eval/qrels.tsv has no rows: pool, judge with two judges, then `python -m eval.make_qrels`"))
    else:
        uncovered = sorted({q.get("qid") for q in queries} - judged - {None})
        if uncovered:
            out.append(Item("evaluation inputs", "TODO", "every query is judged", f"{len(qrels)} judgements, none for {', '.join(uncovered[:8])}" + (" ..." if len(uncovered) > 8 else "")))
        else:
            out.append(Item("evaluation inputs", "PASS", "graded qrels", f"{len(qrels)} judgements over {len(judged)} queries"))

    gold = _rows(gpath, ",") if gpath.is_file() else []
    out.append(Item("evaluation inputs", "PASS" if gold else "TODO", "gold overruling list",
                    f"{len(gold)} hand-verified rows" if gold else "eval/gold_overrulings.csv is empty, so harmful@10 is n/a"))

    agreements = sorted((root / "eval" / "judging").glob("*/agreement.md")) if (root / "eval" / "judging").is_dir() else []
    out.append(Item("evaluation inputs", "PASS" if agreements else "TODO", "judge agreement reported",
                    ", ".join(str(p.relative_to(root)).replace("\\", "/") for p in agreements) if agreements
                    else "no eval/judging/<round>/agreement.md yet (written by `python -m eval.make_qrels`)"))
    return out


def check_results(root: Path) -> list[Item]:
    results = root / "eval" / "results"
    present = [n for n in RESULT_FILES if (results / n).is_file()]
    stub_files = sorted(p.name for p in results.glob("stub_*")) if results.is_dir() else []
    tracked = tracked_files(root) or []
    stub_tracked = [p for p in tracked if p.startswith("eval/results/stub_") or p.startswith("eval/judging/stub_")]
    out: list[Item] = []
    if stub_tracked:
        out.append(Item("results", "FAIL", "no stub results committed", "tracked: " + ", ".join(stub_tracked[:5])))
    elif stub_files:
        out.append(Item("results", "TODO", "no stub results in eval/results", "on disk (git-ignored, but delete them before packaging): " + ", ".join(stub_files[:5])))
    else:
        out.append(Item("results", "PASS", "no stub results", "eval/results holds no stub_* file"))
    if len(present) == len(RESULT_FILES):
        out.append(Item("results", "PASS", "final results present", "table, per-query CSV, chart and Markdown for the test split"))
    else:
        out.append(Item("results", "TODO", "final results present", "missing in eval/results: " + ", ".join(sorted(set(RESULT_FILES) - set(present)))
                        + " (`python -m eval.run_ablation --split test` once the real modules and the qrels exist)"))
    return out


def check_wording(root: Path) -> list[Item]:
    """The page and the generated results never use the banned phrases; the not-legal-advice note is shown."""
    scanned: list[Path] = []
    web = root / "app" / "web"
    if web.is_dir():
        scanned += [p for p in web.rglob("*") if p.is_file() and p.suffix in {".html", ".js", ".css"} and "vendor" not in p.parts]
    results = root / "eval" / "results"
    if results.is_dir():
        scanned += [p for p in results.glob("*.md")]
    hits = [f"{p.relative_to(root).as_posix()}:{n}" for p in scanned for n, line in enumerate(_read(p).splitlines(), 1) if BANNED.search(line)]
    out = [Item("wording", "FAIL" if hits else "PASS", "no banned phrase in the page or the results",
                ("found at " + ", ".join(hits[:6])) if hits else f"{len(scanned)} files scanned")]
    for rel in ("app/web/index.html", "app/cli.py"):
        path = root / rel
        ok = path.is_file() and re.search(r"not\s+legal\s+advice", _read(path), re.I) is not None
        out.append(Item("wording", "PASS" if ok else "FAIL", f"not-legal-advice note in {rel}", "" if ok else "the note is missing"))
    return out


def check_secrets_and_size(root: Path) -> list[Item]:
    files = tracked_files(root)
    if files is None:
        return [Item("repository", "MANUAL", "secrets and size", "not a git repository here: run `git ls-files` yourself and look")]
    hits: list[str] = []
    total = 0
    largest: tuple[int, str] = (0, "")
    for rel in files:
        path = root / rel
        try:
            size = path.stat().st_size
        except OSError:
            continue
        total += size
        largest = max(largest, (size, rel))
        if rel.startswith(SKIP_SCAN) or size > MAX_SCAN_BYTES or path.suffix.lower() not in TEXT_SUFFIXES:
            continue
        for n, line in enumerate(_read(path).splitlines(), 1):
            for label, pattern in SECRETS:
                if pattern.search(line):
                    hits.append(f"{rel}:{n} ({label})")
    out = [Item("repository", "FAIL" if hits else "PASS", "no secrets in tracked files",
                ("found: " + ", ".join(hits[:6]) + " (values not shown)") if hits else f"{len(files)} tracked files scanned")]
    if ".env" in {Path(f).name for f in files}:
        out.append(Item("repository", "FAIL", "no .env committed", "a .env file is tracked"))
    raw = [f for f in files if f.startswith("data/raw/") and not f.endswith(".gitkeep")]
    out.append(Item("repository", "FAIL" if raw else "PASS", "raw data is not committed", ("tracked: " + ", ".join(raw[:4])) if raw else "data/raw is ignored"))
    mb = total / 1024 ** 2
    if largest[0] > GITHUB_LIMIT:
        out.append(Item("repository", "FAIL", "tracked files fit GitHub", f"{largest[1]} is {largest[0] / 1024 ** 2:.0f} MB, over the 100 MB limit"))
    elif largest[0] > WARN_SIZE:
        out.append(Item("repository", "TODO", "tracked files fit GitHub", f"{largest[1]} is {largest[0] / 1024 ** 2:.0f} MB (the limit is 100 MB); consider moving it out"))
    else:
        out.append(Item("repository", "PASS", "tracked files fit GitHub", f"largest is {largest[1]} at {largest[0] / 1024:.0f} KB"))
    out.append(Item("repository", "PASS" if total < LAPTOP_TARGET else "FAIL", "repository size", f"{mb:.1f} MB tracked (target under 2 GB; the built index is outside git)"))
    return out


def check_git(root: Path) -> list[Item]:
    status = git(root, "status", "--porcelain")
    if status is None:
        return [Item("repository", "MANUAL", "working tree clean", "not a git repository here")]
    branch = (git(root, "rev-parse", "--abbrev-ref", "HEAD") or "").strip()
    if status.strip():
        n = len(status.strip().splitlines())
        return [Item("repository", "TODO", "working tree clean", f"{n} uncommitted change(s) on {branch}: commit them before submitting")]
    return [Item("repository", "PASS", "working tree clean", f"nothing uncommitted on {branch}")]


def check_docs(root: Path) -> list[Item]:
    out: list[Item] = []
    readme = _read(root / "README.md") if (root / "README.md").is_file() else ""
    for label, needle in (("dataset credited (CC-BY-4.0)", "CC-BY-4.0"), ("status table", "## Status"), ("quick start", "pip install -r requirements.txt"),
                          ("how to reproduce the evaluation", "eval.run_ablation")):
        out.append(Item("documents", "PASS" if needle in readme else "FAIL", f"README: {label}", "" if needle in readme else f"`{needle}` not found"))
    log = root / "AI_USE_LOG.md"
    if log.is_file():
        rows = [ln for ln in _read(log).splitlines() if ln.startswith("| 20")]
        pending = [ln for ln in rows if re.match(r"\s*(?:pending|tbd|todo)\b", ln.rstrip().rstrip("|").rsplit("|", 1)[-1], re.I)]
        if pending:
            out.append(Item("documents", "TODO", "AI-use log: every entry reviewed", f"{len(pending)} of {len(rows)} entries say the human review is pending"))
        else:
            out.append(Item("documents", "PASS", "AI-use log: every entry reviewed", f"{len(rows)} entries, none pending"))
    else:
        out.append(Item("documents", "FAIL", "AI-use log", "AI_USE_LOG.md is missing"))
    return out


MANUAL_ITEMS = (
    ("clean-machine test", "clone into a new folder, new virtual environment, follow the README quick start with nothing else installed"),
    ("demo video", "5 to 8 minutes, unlisted, plays in a private window; shows one limitation; every member explains their own part (docs/VIDEO_SCRIPT.md)"),
    ("report PDF", "8 pages or fewer; every number from a generated file; the dataset credited; the AI-use declaration (docs/REPORT_SKELETON.md)"),
    ("ethics", "robots.txt obeyed if anything was fetched from a website; nothing copied from other projects; built inside the 36-hour window"),
    ("every member's part", "each owner explains their own component in the video and has read the code that carries their name"),
)

CHECKS: tuple[Callable[[Path], list[Item]], ...] = (
    check_stubs, check_tuned_weights, check_eval_inputs, check_results, check_wording, check_secrets_and_size, check_git, check_docs,
)


def audit(root: Path = ROOT) -> list[Item]:
    items: list[Item] = []
    for fn in CHECKS:
        items += fn(root)
    items += [Item("by hand", "MANUAL", name, detail) for name, detail in MANUAL_ITEMS]
    return items


# -------------------------------------------------------------------------------------------------- slow checks (--run)
def _run(cmd: list[str], root: Path, env_extra: dict[str, str] | None = None, timeout: int = 1800) -> tuple[int, str]:
    env = {**os.environ, **(env_extra or {}), "PYTHONIOENCODING": "utf-8"}
    proc = subprocess.run(cmd, cwd=root, env=env, capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=timeout)
    return proc.returncode, (proc.stdout or "") + (proc.stderr or "")


def run_checks(root: Path = ROOT) -> list[Item]:
    py = sys.executable
    out: list[Item] = []
    code, text = _run([py, "-m", "pytest", "-q"], root)
    tail = text.strip().splitlines()[-1] if text.strip() else ""
    out.append(Item("gate", "PASS" if code == 0 else "FAIL", "python -m pytest", tail))
    code, text = _run([py, "eval/smoke.py"], root)
    out.append(Item("gate", "PASS" if code == 0 else "FAIL", "python eval/smoke.py", (text.strip().splitlines() or [""])[-1]))
    code, text = _run([py, "eval/smoke.py"], root, {"LEXSHIFT_STUBS": "none"})
    out.append(Item("gate", "PASS" if code == 0 else "TODO", "LEXSHIFT_STUBS=none python eval/smoke.py (every provider real)",
                    (text.strip().splitlines() or [""])[-1][:240]))
    code, text = _run([py, "-m", "eval.check_data", "--strict"], root)
    out.append(Item("gate", "PASS" if code == 0 else "TODO", "python -m eval.check_data --strict", (text.strip().splitlines() or [""])[-1][:240]))
    code, text = _run([py, "-m", "app.cli", "BNS 103 murder", "--offence-date", "2025-01-10"], root)
    banner = "STUB MODE" in text
    banned = BANNED.search(text) is not None
    level = "FAIL" if banned else ("TODO" if banner or code != 0 else "PASS")
    out.append(Item("gate", level, "the demo shows no STUB MODE banner and no banned phrase",
                    "banned phrase in the output" if banned else ("the STUB MODE banner is shown" if banner else ("the demo failed: " + text.strip()[:160] if code != 0 else "clean"))))
    return out


# ------------------------------------------------------------------------------------------------------------- output
def render(items: Iterable[Item]) -> str:
    items = list(items)
    by_group: dict[str, list[Item]] = {}
    for it in items:
        by_group.setdefault(it.group, []).append(it)
    lines = ["LexShift submission audit"]
    for group, members in by_group.items():
        lines += ["", group]
        lines += [f"  [{it.level:<6}] {it.check}" + (f": {it.detail}" if it.detail else "") for it in members]
    counts = {lv: sum(1 for i in items if i.level == lv) for lv in LEVELS}
    lines += ["", "  ".join(f"{counts[lv]} {lv}" for lv in LEVELS)]
    if counts["FAIL"]:
        lines.append("A FAIL is a broken rule: fix it before anything else.")
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--run", action="store_true", help="also run pytest, both smoke tests, check_data --strict and the demo (slow)")
    ap.add_argument("--strict", action="store_true", help="TODO items fail too")
    ap.add_argument("--json", action="store_true", help="machine-readable output")
    ap.add_argument("--root", type=Path, default=ROOT, help="repository to audit (default: this one)")
    args = ap.parse_args(argv)
    items = audit(args.root)
    if args.run:
        items += run_checks(args.root)
    if args.json:
        print(json.dumps([asdict(i) for i in items], indent=2))
    else:
        print(render(items))
    failed = any(i.level == "FAIL" for i in items) or (args.strict and any(i.level == "TODO" for i in items))
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
