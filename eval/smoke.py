#!/usr/bin/env python
"""Smoke test: the merge gate for main (Guide 4.4: "Merge to main only after python eval/smoke.py passes").

It checks, with the providers selected in common/config.yaml (or LEXSHIFT_STUBS):
  1. which functions are real and which are fixed-value stubs;
  2. for every REAL provider, that its data file exists and its records satisfy the schema (first 200 records);
  3. that search / parse_query / continuity / health / authority honour the contracts in common/contracts.py;
  4. that rank() returns well-formed, sorted, deterministic results for b0, b1 and full (skipped, and said so,
     until M4 has implemented rank()).

A pass in stub mode proves the interfaces line up. It proves nothing about retrieval quality, and says so.

Usage:  python eval/smoke.py [--strict] [--k 10] [--queries 3]
Exit code 0 = no failure. --strict also fails on skipped checks.
"""

from __future__ import annotations

import argparse
import sys
import traceback
from itertools import islice
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from common import contracts  # noqa: E402
from common.config import load_config, resolve_path  # noqa: E402
from common.io import read_delimited, read_jsonl  # noqa: E402
from common.providers import Providers, load_providers  # noqa: E402
from m4_rank.rank import ArtefactError, load_checked  # noqa: E402
from common.schema import (  # noqa: E402
    DocHealth,
    DocStatutes,
    Judgment,
    Query,
    SchemaError,
    StatuteMapRow,
)

BUILTIN_QUERIES: list[tuple[str, str | None]] = [
    ("murder common intention", None),
    ("BNS 103", "2025-01-10"),
    ("Section 302 IPC", "2020-05-01"),
]
SCHEMA_SAMPLE = 200
CONTRACT_DOCS_PER_QUERY = 20


class Report:
    def __init__(self) -> None:
        self.failures = 0
        self.skips = 0

    def passed(self, msg: str) -> None:
        print(f"[PASS] {msg}")

    def failed(self, msg: str, problems: list[str] | None = None) -> None:
        self.failures += 1
        print(f"[FAIL] {msg}")
        for p in (problems or [])[:8]:
            print(f"         - {p}")
        if problems and len(problems) > 8:
            print(f"         ... and {len(problems) - 8} more")

    def check(self, label: str, problems: list[str], ok_label: str | None = None) -> None:
        """Pass `ok_label` (default `label`) when there are no problems, otherwise fail `label` with them."""
        if problems:
            self.failed(label, problems)
        else:
            self.passed(ok_label or label)

    def skipped(self, msg: str) -> None:
        self.skips += 1
        print(f"[SKIP] {msg}")

    def note(self, msg: str) -> None:
        print(f"[INFO] {msg}")


def smoke_queries(cfg: dict, n: int) -> list[tuple[str, str | None]]:
    """Dev queries if the team has written any (never test queries), else built-in interface exercisers."""
    path = resolve_path("queries", cfg)
    dev: list[tuple[str, str | None]] = []
    if path.exists() and path.stat().st_size > 0:
        for rec in read_jsonl(path):
            q = Query.from_dict(rec)
            if q.split == "dev":
                dev.append((q.text, q.offence_date))
    return (dev or BUILTIN_QUERIES)[:n]


def check_data_files(cfg: dict, providers: Providers, rep: Report) -> None:
    jobs: list[tuple[str, str, object]] = []
    if "search" not in providers.stubbed:
        jobs.append(("judgments", "judgments.jsonl", Judgment))
    if "statute" not in providers.stubbed:
        jobs.append(("doc_statutes", "doc_statutes.jsonl", DocStatutes))
    if not {"health", "authority"} <= providers.stubbed:
        jobs.append(("doc_health", "doc_health.jsonl", DocHealth))
    if not jobs:
        rep.skipped("data files: every provider is a stub, nothing to read")
        return
    for key, label, cls in jobs:
        path = resolve_path(key, cfg)
        if not path.exists():
            rep.failed(f"{label}: missing at {path}")
            continue
        problems, count = [], 0
        try:
            for rec in islice(read_jsonl(path), SCHEMA_SAMPLE):
                count += 1
                try:
                    cls.from_dict(rec)  # type: ignore[attr-defined]
                except SchemaError as exc:
                    problems.append(f"record {count}: {exc}")
        except ValueError as exc:
            problems.append(str(exc))
        if count == 0 and not problems:
            problems.append("file is empty")
        rep.check(f"{label}: first {count} records", problems, f"{label}: first {count} records match the schema")
    if "statute" not in providers.stubbed:
        path = resolve_path("statute_map", cfg)
        if not path.exists():
            rep.failed(f"statute_map.csv: missing at {path}")
        else:
            problems = []
            rows = read_delimited(path)
            for i, row in enumerate(rows, start=1):
                try:
                    StatuteMapRow.from_dict({**row, "weight": float(row["weight"])})
                except (SchemaError, ValueError, KeyError) as exc:
                    problems.append(f"row {i}: {exc}")
            if not rows:
                problems.append("no rows")
            rep.check("statute_map.csv", problems, f"statute_map.csv: {len(rows)} rows match the schema")


def check_providers(providers: Providers, queries: list[tuple[str, str | None]], rep: Report) -> dict[str, set[str]]:
    """Contract checks for the five functions. Returns query -> candidate ids for the rank() cross-check."""
    candidates: dict[str, set[str]] = {}
    k = 100
    problems: dict[str, list[str]] = {"search": [], "parse_query": [], "continuity": [], "health": [], "authority": []}
    for text, date in queries:
        try:
            hits = providers.search(text, k=k)
        except Exception as exc:  # noqa: BLE001 - report any provider failure as a contract failure
            problems["search"].append(f"{text!r}: {type(exc).__name__}: {exc}")
            continue
        problems["search"] += [f"{text!r}: {p}" for p in contracts.check_hits(hits, k)]
        candidates[text] = {h.doc_id for h in hits}
        try:
            qs = providers.parse_query(text, date)
        except Exception as exc:  # noqa: BLE001
            problems["parse_query"].append(f"{text!r}: {type(exc).__name__}: {exc}")
            continue
        problems["parse_query"] += contracts.check_query_statutes(qs)
        for h in hits[:CONTRACT_DOCS_PER_QUERY]:
            for name, call, check in (
                ("continuity", lambda: providers.continuity(qs, h.doc_id), contracts.check_continuity),
                ("health", lambda: providers.health(h.doc_id, qs.offence_ids or None), contracts.check_health),
                ("authority", lambda: providers.authority(h.doc_id), contracts.check_authority),
            ):
                try:
                    problems[name] += [f"{h.doc_id}: {p}" for p in check(call())]
                except Exception as exc:  # noqa: BLE001
                    problems[name].append(f"{h.doc_id}: {type(exc).__name__}: {exc}")
    for name, probs in problems.items():
        # keep reports short: de-duplicate and cap
        rep.check(f"{name}() contract ({len(queries)} queries)", list(dict.fromkeys(probs)))
    return candidates


def check_rank(providers: Providers, queries: list[tuple[str, str | None]], candidates: dict[str, set[str]], k: int, rep: Report) -> None:
    try:
        from m4_rank import rank
    except Exception as exc:  # noqa: BLE001
        rep.failed(f"rank(): import failed: {type(exc).__name__}: {exc}")
        return
    configs = ("b0", "b1", "full")
    problems: list[str] = []
    try:
        for text, date in queries:
            for cfg_name in configs:
                first = rank(text, date, k=k, config=cfg_name)
                again = rank(text, date, k=k, config=cfg_name)
                problems += [f"{text!r}/{cfg_name}: {p}" for p in contracts.check_results(first, k, candidates.get(text))]
                if [(r.doc_id, r.final) for r in first] != [(r.doc_id, r.final) for r in again]:
                    problems.append(f"{text!r}/{cfg_name}: rank() is not deterministic")
    except NotImplementedError as exc:
        rep.skipped(f"rank(): {exc}")
        return
    except Exception as exc:  # noqa: BLE001
        rep.failed("rank() raised", [f"{type(exc).__name__}: {exc}", traceback.format_exc(limit=3)])
        return
    rep.check(f"rank() for b0/b1/full over {len(queries)} queries (sorted, in [0,1], deterministic)", problems)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--strict", action="store_true", help="treat skipped checks as failures")
    ap.add_argument("--k", type=int, default=10, help="k for rank() (default 10)")
    ap.add_argument("--queries", type=int, default=3, help="how many queries to exercise (default 3)")
    args = ap.parse_args(argv)

    rep = Report()
    cfg = load_config()
    try:
        providers = load_checked(load_providers, cfg)
    except ArtefactError as exc:
        rep.failed("providers could not be loaded", [str(exc)])
        print(f"\n{rep.failures} failed, {rep.skips} skipped")
        return 1
    rep.note(f"providers: {providers.describe()}")
    if providers.stubbed:
        rep.note("STUB MODE for: " + ", ".join(sorted(providers.stubbed)) + ". A pass proves the interfaces line up, not that retrieval works.")

    check_data_files(cfg, providers, rep)
    queries = smoke_queries(cfg, args.queries)
    candidates = check_providers(providers, queries, rep)
    check_rank(providers, queries, candidates, args.k, rep)

    print(f"\n{rep.failures} failed, {rep.skips} skipped")
    if rep.failures or (args.strict and rep.skips):
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
