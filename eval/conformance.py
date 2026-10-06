"""Cross-module conformance check: does each module's output honour the shared contracts, and do the modules fit together?

    python -m eval.conformance                 # every module
    python -m eval.conformance --module m2     # one module (m1, m2, m3)
    python -m eval.conformance --json          # machine-readable

It reads the real artefacts the modules wrote (judgments.jsonl, doc_statutes.jsonl, citations.jsonl, doc_health.jsonl,
statute_map.csv) and calls the real functions (search, parse_query, health, authority), whatever the `stubs:` switches say.
Every finding names the module that has to act, so the output can be sent to its owner as it is.

Levels: FAIL breaks a contract or the connection to another module; WARN is a quality or consistency problem a reviewer should
see; INFO is a fact worth knowing; PASS is a check that held. Exit code 1 if anything FAILs.

The checks use their own small readers (a coram-line reader, a section-reference reader) instead of the modules' code, so they
do not share a bug with what they test. They are heuristics: a number here is evidence to look at, not a verdict.
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from collections import Counter
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from common import contracts  # noqa: E402
from common.config import load_config, resolve_path  # noqa: E402
from common.io import read_jsonl  # noqa: E402
from common.schema import Citation, DocHealth, DocStatutes, Judgment, SchemaError  # noqa: E402

ID_PATTERN = re.compile(r"^\d{4}_\d+_\d+_\d+(?:_[A-Za-z]{2,3})?$")
CORAM = re.compile(r"\[([^\[\]]{3,300}?),\s*(?:JJ|J|CJI)\.?\s*\]")
CRIMINAL = re.compile(r"\b(?:IPC|BNS|BNSS|Cr\.?\s?P\.?\s?C\.?|Indian Penal Code)\b")
CONTROLS = re.compile(r"[\x00-\x08\x0b\x0e-\x1f\x7f]")  # form feed (\x0c) is a legitimate page break
PARAGRAPH_STYLE = re.compile(r"\b(IPC|CrPC|Cr\.\s?P\.\s?C\.|BNS|BNSS)\.\s+(\d{1,3})\.\s+[A-Z]")
LEAD_STYLE = r"(?:\bsections?\b|\bss?\.|\bu/ss?\.?)"
PLAN_MAP_ROWS = (20, 40)  # Build Guide, M2 block


@dataclass
class Finding:
    module: str
    level: str  # PASS | INFO | WARN | FAIL
    check: str
    detail: str = ""


class Report:
    def __init__(self) -> None:
        self.items: list[Finding] = []

    def add(self, module: str, level: str, check: str, detail: str = "") -> None:
        self.items.append(Finding(module, level, check, detail))

    def count(self, level: str) -> int:
        return sum(1 for f in self.items if f.level == level)


def coram_count(text: str) -> int | None:
    """Judges named on the coram line near the top of a judgment (an independent reader; mixed case and `*` allowed)."""
    m = CORAM.search(re.sub(r"\s+", " ", text[:3000]))
    if not m:
        return None
    body = re.sub(r"\bCJI\b", "", m.group(1).replace("*", ""))
    names = [n for n in re.split(r",|\band\b", body, flags=re.I) if re.search(r"[A-Za-z]{2}", n)]
    return len(names) or None


def _path(key: str, cfg: dict[str, Any]) -> Path:
    return resolve_path(key, cfg)


def _records(path: Path):
    return list(read_jsonl(path)) if path.exists() and path.stat().st_size else []


# --------------------------------------------------------------------------------------------------------- M1
def check_m1_data(rep: Report, cfg: dict[str, Any]) -> list[dict]:
    path = _path("judgments", cfg)
    recs = _records(path)
    if not recs:
        rep.add("M1", "INFO", "judgments.jsonl", f"not built yet ({path.name} is missing or empty)")
        return []
    n = len(recs)
    rep.add("M1", "INFO", "corpus size", f"{n} judgments")

    bad: Counter[str] = Counter()
    for r in recs:
        try:
            Judgment.from_dict(r)
        except SchemaError as exc:
            bad[re.sub(r"'[^']*'", "'...'", str(exc))[:90]] += 1
    valid = n - sum(bad.values())
    if valid == n:
        rep.add("M1", "PASS", "judgments.jsonl matches the Judgment contract", f"{n}/{n}")
    else:
        top = "; ".join(f"{m} (x{c})" for m, c in bad.most_common(3))
        rep.add("M1", "FAIL", "judgments.jsonl matches the Judgment contract", f"only {valid}/{n} records are valid. Top problems: {top}")

    ids = [r.get("doc_id") for r in recs]
    rep.add("M1", "PASS" if len(set(ids)) == n else "FAIL", "doc_ids are unique", f"{len(set(ids))} distinct of {n}")
    matching = sum(bool(ID_PATTERN.match(str(i))) for i in ids)
    rep.add("M1", "PASS" if matching == n else "WARN", "doc_id follows <year>_<volume>_<first>_<last>[_<lang>]",
            f"{matching}/{n}. M3's resolver relies on this shape for exact-key and page-range resolution")
    cited = sum(bool(r.get("reporter_citations")) for r in recs)
    rep.add("M1", "PASS" if cited >= 0.95 * n else "WARN", "reporter_citations filled (M3 resolves citations through them)", f"{cited}/{n}")

    both = [(r.get("bench_size"), coram_count(r.get("text", ""))) for r in recs]
    seen = [(b, c) for b, c in both if c]
    wrong = [(b, c) for b, c in seen if b != c]
    if seen:
        lvl = "PASS" if not wrong else ("FAIL" if len(wrong) / len(seen) > 0.05 else "WARN")
        rep.add("M1", lvl, "bench_size agrees with the coram line printed in the text",
                f"{len(seen) - len(wrong)}/{len(seen)} agree; M1 value vs coram line in the disagreements: "
                f"{dict(Counter(wrong).most_common(4))}")
        three_plus = [(b, c) for b, c in seen if c >= 3]
        if three_plus:
            ok = sum(b == c for b, c in three_plus)
            rep.add("M1", "FAIL" if ok < len(three_plus) else "PASS", "benches of 3 or more judges are recorded",
                    f"{ok}/{len(three_plus)} correct. M3's bench check can never validate an overruling by a larger bench without them")
    zero = sum(1 for r in recs if r.get("bench_size") in (0,))
    if zero:
        rep.add("M1", "FAIL", "bench_size is a positive int or None", f"{zero} records have bench_size 0")

    covered = sum(1 for r in recs if any((v or "").strip() for v in (r.get("zones") or {}).values()))
    share = []
    for r in recs:
        t = len(r.get("text") or "") or 1
        share.append(sum(len(v or "") for v in (r.get("zones") or {}).values()) / t)
    share.sort()
    med = share[len(share) // 2] if share else 0.0
    rep.add("M1", "PASS" if covered == n and med >= 0.6 else "WARN", "zones cover the text",
            f"{covered}/{n} judgments have some zone text; median {med:.0%} of each text lies inside a zone "
            "(text outside every zone is invisible to zone-weighted BM25)")

    dirty = sum(bool(CONTROLS.search(r.get("text", ""))) for r in recs)
    rep.add("M1", "PASS" if not dirty else "WARN", "text is free of control characters",
            f"{dirty}/{n} judgments contain backspace, bell or similar characters left by PDF extraction; they reach evidence excerpts and spreadsheets")

    crim = sum(bool(CRIMINAL.search(r.get("text", ""))) for r in recs)
    rep.add("M1", "PASS" if crim >= 0.95 * n else "WARN", "corpus is criminal-law (mentions IPC, BNS, CrPC or BNSS)", f"{crim}/{n}")

    years = Counter(m.group(1) for r in recs if (m := re.search(r"\b(1[89]\d\d|20\d\d)\b", str(r.get("date", "")))))
    if len(years) <= 1:
        rep.add("M1", "WARN", "corpus spans more than one year",
                f"all dated judgments are from {sorted(years)}. Older citations cannot resolve and no precedent in the corpus can "
                "be overruled inside it, so the treatment signal has nothing to find; the evaluation needs older cases")
    else:
        rep.add("M1", "INFO", "years covered", f"{min(years)} to {max(years)} ({len(years)} years)")

    idx_dir = _path("index_dir", cfg)
    tokenized = idx_dir / "tokenized_judgments.jsonl"
    if tokenized.exists():
        tok_ids = {r["doc_id"] for r in read_jsonl(tokenized)}
        same = tok_ids == set(ids)
        rep.add("M1", "PASS" if same else "FAIL", "the index and judgments.jsonl cover the same documents",
                f"index {len(tok_ids)}, corpus {len(set(ids))}" + ("" if same else f"; only in index {len(tok_ids - set(ids))}, only in corpus {len(set(ids) - tok_ids)}"))
    try:
        out = subprocess.run(["git", "ls-files", "-z", "--", str(idx_dir.relative_to(ROOT)), str(path.relative_to(ROOT))],
                             cwd=ROOT, capture_output=True, text=True, timeout=30).stdout
        tracked = [p for p in out.split("\0") if p]
        size = sum((ROOT / p).stat().st_size for p in tracked if (ROOT / p).exists())
        if size > 20 * 1024 * 1024:
            rep.add("M1", "WARN", "derived artefacts are committed to git",
                    f"{len(tracked)} tracked files, {size / 1e6:.0f} MB (index and tokenised copy are rebuilt from judgments.jsonl; "
                    "history keeps every version). Commit only a small sample and a build command")
    except (OSError, ValueError, subprocess.SubprocessError):
        pass
    return recs


def check_m1_api(rep: Report, recs: list[dict]) -> None:
    code = (
        "import io, json, time, contextlib\n"
        "buf = io.StringIO(); t = time.time()\n"
        "with contextlib.redirect_stdout(buf):\n"
        "    import m1_index\n"
        "print(json.dumps({'seconds': round(time.time() - t, 2), 'stdout': len(buf.getvalue())}))\n"
    )
    run = subprocess.run([sys.executable, "-c", code], cwd=ROOT, capture_output=True, text=True, timeout=300)
    if run.returncode != 0:
        why = (run.stderr.strip().splitlines() or ["?"])[-1]
        rep.add("M1", "FAIL", "import m1_index works on a clean clone", why[:200])
        return
    info = json.loads(run.stdout.strip().splitlines()[-1])
    rep.add("M1", "PASS" if info["stdout"] == 0 else "FAIL", "importing m1_index prints nothing", f"{info['stdout']} characters written to stdout")
    rep.add("M1", "PASS" if info["seconds"] <= 5 else "WARN", "importing m1_index is quick", f"{info['seconds']} s")

    import contextlib
    import io

    try:
        with contextlib.redirect_stdout(io.StringIO()):
            from m1_index import search
    except Exception as exc:  # noqa: BLE001
        rep.add("M1", "FAIL", "from m1_index import search", f"{type(exc).__name__}: {exc}"[:200])
        return
    for query in ("BNS 103", "punishment for murder under section 103 BNS", "murder AND intention", '"common intention" /s murder'):
        try:
            hits = search(query, k=10)
        except Exception as exc:  # noqa: BLE001
            rep.add("M1", "FAIL", f"search({query!r}) answers", f"{type(exc).__name__}: {str(exc)[:90]}")
            continue
        problems = contracts.check_hits(hits, 10)
        rep.add("M1", "PASS" if hits and not problems else "FAIL", f"search({query!r}) returns contract-valid hits",
                f"{len(hits)} hits" + (f"; {problems[0]}" if problems else ""))
    years = [m.group(1) for r in recs if (m := re.search(r"\b(1[89]\d\d|20\d\d)\b", str(r.get("date", ""))))]
    if years:
        year = int(Counter(years).most_common(1)[0][0])
        try:
            got = len(search("murder", k=500, filters={"year": year}))
            want = sum(1 for y in years if int(y) == year)
            rep.add("M1", "PASS" if got > 0 else "FAIL", "the year filter works on the real metadata", f"filters={{'year': {year}}} -> {got} hits ({want} judgments from that year)")
        except Exception as exc:  # noqa: BLE001
            rep.add("M1", "FAIL", "the year filter works on the real metadata", f"{type(exc).__name__}: {exc}")
    hits = search("murder", k=500)
    zero = sum(1 for h in hits if h.rel == 0)
    rep.add("M1", "PASS" if zero == 0 else "WARN", "every Boolean match gets a positive relevance",
            f"{zero} of {len(hits)} matches for 'murder' score 0 (the term lies outside every zone)")


# --------------------------------------------------------------------------------------------------------- M2
REQUIRED_FORMS: list[tuple[str, set[tuple[str, str]]]] = [
    ("IPC 302", {("IPC", "302")}),
    ("Section 103 of the BNS", {("BNS", "103")}),
    ("u/s 302/34 IPC", {("IPC", "302"), ("IPC", "34")}),
    ("Section 302 read with 34 IPC", {("IPC", "302"), ("IPC", "34")}),
    ("S. 302 I.P.C.", {("IPC", "302")}),
    ("Sections 302 and 307 of the Indian Penal Code", {("IPC", "302"), ("IPC", "307")}),
    ("Section 482 Cr.P.C.", {("CRPC", "482")}),
    ("BNS 3(5)", {("BNS", "3(5)")}),
    ("section 120-B IPC", {("IPC", "120B")}),
]


def check_m2_data(rep: Report, cfg: dict[str, Any], recs: list[dict]) -> None:
    from common.io import read_delimited

    map_path = _path("statute_map", cfg)
    rows = read_delimited(map_path) if map_path.exists() else []
    lo, hi = PLAN_MAP_ROWS
    rep.add("M2", "PASS" if len(rows) >= lo else "WARN", f"statute_map.csv has the planned {lo}-{hi} mapped sections", f"{len(rows)} rows")
    if rows:
        weights = cfg["m2_statute"]["relation_weights"]
        off = [r["relation"] for r in rows if abs(float(r["weight"]) - weights.get(r["relation"], -1)) > 1e-9]
        rep.add("M2", "PASS" if not off else "WARN", "row weights equal the configured relation weights", f"{len(off)} rows differ" if off else "all rows")
        blogs = sum(1 for r in rows if not re.search(r"mha\.gov|prsindia|egazette|gov\.in", r["source"], re.I))
        if blogs:
            rep.add("M2", "INFO", "mapping sources", f"{blogs}/{len(rows)} rows cite no official source (MHA, PRS or the gazette); the brief prefers the official comparison tables")

    path = _path("doc_statutes", cfg)
    stats = _records(path)
    if not stats:
        rep.add("M2", "INFO", "doc_statutes.jsonl", f"not built yet ({path.name} is missing or empty)")
        return
    bad = 0
    for r in stats:
        try:
            DocStatutes.from_dict(r)
        except SchemaError:
            bad += 1
    rep.add("M2", "PASS" if not bad else "FAIL", "doc_statutes.jsonl matches the DocStatutes contract", f"{len(stats) - bad}/{len(stats)} valid")
    ids = {r["doc_id"] for r in recs}
    got = {r["doc_id"] for r in stats}
    if ids:
        rep.add("M2", "PASS" if ids <= got else "FAIL", "doc_statutes.jsonl covers every judgment", f"missing {len(ids - got)} of {len(ids)}; extra {len(got - ids)}")
    withrefs = sum(bool(r["refs"]) for r in stats)
    rep.add("M2", "INFO", "judgments with at least one statute reference", f"{withrefs}/{len(stats)}")
    off = sum(1 for r in stats for x in r["refs"] if x.get("offence_id"))
    total = sum(len(r["refs"]) for r in stats)
    rep.add("M2", "PASS" if off else "WARN", "offence_id is filled", f"{off}/{total} references have one. Without it M3's point-level health cannot tell which offence an overruling concerned")
    unknown = sum(1 for r in stats for x in r["refs"] if x["act"] == "UNKNOWN")
    rep.add("M2", "INFO", "references with act UNKNOWN", f"{unknown}/{total}")

    by_doc = {r["doc_id"]: r for r in recs}
    suspect = 0
    for r in stats:
        text = re.sub(r"\s+", " ", by_doc.get(r["doc_id"], {}).get("text", ""))
        para = {(("CRPC" if a.upper().startswith("CR") else a.upper()), n) for a, n in PARAGRAPH_STYLE.findall(text)}
        for x in r["refs"]:
            if (x["act"], x["section"]) in para and not re.search(rf"{LEAD_STYLE}[^.;]{{0,45}}?\b{re.escape(x['section'])}\b", text, re.I):
                suspect += 1
    rep.add("M2", "PASS" if suspect <= 0.02 * max(1, total) else "FAIL", "references are sections, not paragraph numbers",
            f"{suspect}/{total} references are probably the paragraph number after 'IPC.' or 'CrPC.' "
            "(the number follows the act with a full stop, is itself followed by a full stop and a capital, and no 'Section' word precedes it)")


def check_m2_api(rep: Report) -> None:
    try:
        from m2_statute import parse_query
    except Exception as exc:  # noqa: BLE001
        rep.add("M2", "FAIL", "from m2_statute import parse_query", f"{type(exc).__name__}: {exc}"[:200])
        return
    failed = []
    for text, want in REQUIRED_FORMS:
        try:
            got = {(r.act, r.section) for r in parse_query(text).refs}
        except Exception as exc:  # noqa: BLE001
            got = {("error", type(exc).__name__)}
        if not want <= got:
            failed.append(f"{text!r} -> {sorted(got)} (expected {sorted(want)})")
    rep.add("M2", "PASS" if not failed else "FAIL", "parse_query reads the statute forms the Build Guide lists",
            f"{len(REQUIRED_FORMS) - len(failed)}/{len(REQUIRED_FORMS)} read. Failing: " + " | ".join(failed[:6]))
    wrong = []
    for date, act in (("2025-02-01", "BNS"), ("2020-06-01", "IPC")):
        got = {(r.act, r.section) for r in parse_query("section 103", date).refs}
        if (act, "103") not in got:
            wrong.append(f"'section 103' dated {date} -> {sorted(got)} (expected {act} 103)")
    rep.add("M2", "PASS" if not wrong else "FAIL", "a bare section number takes its code from the offence date (collision resolution)", " | ".join(wrong) or "ok")
    try:
        parse_query("murder", "31/12/2024")
        rep.add("M2", "WARN", "a malformed offence date is rejected", "accepted '31/12/2024'")
    except (ValueError, SchemaError):
        rep.add("M2", "PASS", "a malformed offence date is rejected", "")
    try:
        qs = parse_query("")
        rep.add("M2", "PASS", "an empty query does not crash", f"refs={len(qs.refs)}")
    except Exception as exc:  # noqa: BLE001
        rep.add("M2", "WARN", "an empty query does not crash", f"{type(exc).__name__}")


# --------------------------------------------------------------------------------------------------------- M3
def check_m3_data(rep: Report, cfg: dict[str, Any], recs: list[dict]) -> None:
    cpath, hpath = _path("citations", cfg), _path("doc_health", cfg)
    cits, health = _records(cpath), _records(hpath)
    if not cits and not health:
        rep.add("M3", "INFO", "citations.jsonl and doc_health.jsonl", "not built yet")
        return
    if cits:
        bad = 0
        for r in cits:
            try:
                Citation.from_dict(r)
            except SchemaError:
                bad += 1
        rep.add("M3", "PASS" if not bad else "FAIL", "citations.jsonl matches the Citation contract", f"{len(cits) - bad}/{len(cits)} valid")
        resolved = sum(1 for r in cits if r["cited_doc"])
        rep.add("M3", "INFO", "citation resolution rate", f"{resolved}/{len(cits)} mentions resolve to a corpus judgment ({resolved / len(cits):.1%})")
        labels = Counter(r["label"] for r in cits if r["confidence"] > 0)
        rep.add("M3", "INFO", "classified mentions by label", str(dict(labels)) or "none classified")
        neg = [r for r in cits if r["label"] in ("doubted", "overruled") and r["cited_doc"] and not r["is_appeal_history"]]
        unknown = sum(1 for r in neg if r["citing_bench"] is None or r["cited_bench"] is None)
        rep.add("M3", "INFO", "negative treatments and the bench check",
                f"{len(neg)} negative labels on resolved cases; {sum(r['valid_negative'] for r in neg)} pass the bench check; "
                f"{unknown} cannot be checked because a bench is unknown")
        if neg and unknown / len(neg) > 0.3:
            rep.add("M3", "WARN", "most negative treatments have an unknown bench", f"{unknown}/{len(neg)}: they never lower health")
    if health:
        bad = 0
        for r in health:
            try:
                DocHealth.from_dict(r)
            except SchemaError:
                bad += 1
        rep.add("M3", "PASS" if not bad else "FAIL", "doc_health.jsonl matches the DocHealth contract", f"{len(health) - bad}/{len(health)} valid")
        ids = {r["doc_id"] for r in recs}
        got = {r["doc_id"] for r in health}
        if ids:
            rep.add("M3", "PASS" if ids == got else "FAIL", "doc_health.jsonl covers exactly the corpus", f"missing {len(ids - got)}; extra {len(got - ids)}")
        lowered = sum(1 for r in health if r["health"] < 1.0)
        rep.add("M3", "INFO", "judgments with lowered health", f"{lowered}/{len(health)}")
        try:
            from m3_treatment import authority, health as health_fn

            probe = health[0]["doc_id"]
            problems = contracts.check_health(health_fn(probe)) + contracts.check_authority(authority(probe))
            rep.add("M3", "PASS" if not problems else "FAIL", "health() and authority() satisfy the contract on a real id", "; ".join(problems) or probe)
        except Exception as exc:  # noqa: BLE001
            rep.add("M3", "FAIL", "health() and authority() answer", f"{type(exc).__name__}: {exc}"[:200])


# ------------------------------------------------------------------------------------------------------ driver
def run(modules: set[str]) -> Report:
    cfg = load_config()
    rep = Report()
    # the corpus is read for every module; its own findings are kept only when M1 was asked for
    recs = check_m1_data(rep if "m1" in modules else Report(), cfg) if modules & {"m1", "m2", "m3"} else []
    if "m1" in modules and recs:
        check_m1_api(rep, recs)
    if "m2" in modules:
        check_m2_data(rep, cfg, recs)
        check_m2_api(rep)
    if "m3" in modules:
        check_m3_data(rep, cfg, recs)
    return rep


def render(rep: Report) -> str:
    out = []
    for module in ("M1", "M2", "M3"):
        items = [f for f in rep.items if f.module == module]
        if not items:
            continue
        out.append(f"\n== {module} ==")
        order = {"FAIL": 0, "WARN": 1, "INFO": 2, "PASS": 3}
        for f in sorted(items, key=lambda f: order[f.level]):
            out.append(f"[{f.level}] {f.check}" + (f": {f.detail}" if f.detail else ""))
    out.append(f"\n{rep.count('FAIL')} FAIL, {rep.count('WARN')} WARN, {rep.count('INFO')} INFO, {rep.count('PASS')} PASS")
    return "\n".join(out)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--module", choices=("m1", "m2", "m3", "all"), default="all")
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args(argv)
    modules = {"m1", "m2", "m3"} if args.module == "all" else {args.module}
    rep = run(modules)
    if args.json:
        print(json.dumps([asdict(f) for f in rep.items], indent=2))
    else:
        print(render(rep))
    return 1 if rep.count("FAIL") else 0


if __name__ == "__main__":
    sys.exit(main())
