"""Shared test fixtures.

* `hermetic_config` (autouse): every test runs against a copy of common/config.yaml with `ranking.use_tuned` switched off, so
  a weights_tuned.yaml produced by a later tuning run can never change what a test expects.
* `make_providers`: builds fake cross-module providers from a small table and counts the calls made to each.
"""

from __future__ import annotations

import copy
from pathlib import Path

import pytest
import yaml

from common.config import DEFAULT_CONFIG
from common.providers import Providers
from common.schema import Hit, QueryStatutes, StatuteRef

# Four candidates chosen so every signal can change the order (hand-computed in tests/test_m4_rank.py):
#   A: most relevant but its health is low (a later bench overruled it)    B: strong on everything
#   C: statute omitted in the new code (continuity 0), very high authority  D: weakest text match
SCENARIO = {
    "A": dict(rel=10.0, cont=1.0, health=0.1, auth=0.5, why="BNS 103 -> IPC 302 (equivalent)",
              evidence=[{"citing_doc": "Z", "label": "overruled", "sentence": "placeholder sentence A"}]),
    "B": dict(rel=9.5, cont=1.0, health=1.0, auth=0.4, why="BNS 103 -> IPC 302 (equivalent)", evidence=[]),
    "C": dict(rel=7.0, cont=0.0, health=1.0, auth=0.9, why="IPC 124A omitted in BNS", evidence=[]),
    "D": dict(rel=6.0, cont=1.0, health=1.0, auth=0.1, why="BNS 103 -> IPC 302 (equivalent)", evidence=[]),
}


def _write_config(path: Path, overrides: dict | None = None) -> Path:
    with open(DEFAULT_CONFIG, "r", encoding="utf-8") as fh:
        cfg = yaml.safe_load(fh)
    cfg = copy.deepcopy(cfg)
    cfg["ranking"]["use_tuned"] = False
    for section, values in (overrides or {}).items():
        cfg.setdefault(section, {}).update(values)
    with open(path, "w", encoding="utf-8", newline="\n") as fh:
        yaml.safe_dump(cfg, fh, sort_keys=False)
    return path


@pytest.fixture(autouse=True)
def hermetic_config(tmp_path_factory, monkeypatch):
    path = _write_config(tmp_path_factory.mktemp("cfg") / "config.yaml")
    monkeypatch.setenv("LEXSHIFT_CONFIG", str(path))
    return path


@pytest.fixture
def scenario():
    """A fresh deep copy of SCENARIO that a test may mutate."""
    return copy.deepcopy(SCENARIO)


@pytest.fixture
def write_config():
    """Write a config copy with section overrides, e.g. write_config(tmp, {"paths": {...}})."""
    return _write_config


QUERY_ROWS = [
    {"qid": "dev1", "text": "murder", "offence_date": "2025-01-10", "split": "dev", "type": "A"},
    {"qid": "dev2", "text": "common intention", "offence_date": None, "split": "dev", "type": "C"},
    {"qid": "test1", "text": "BNS 103", "offence_date": "2025-01-10", "split": "test", "type": "A"},
    {"qid": "test2", "text": "section 103", "offence_date": "2020-06-01", "split": "test", "type": "D"},
]


class Workspace:
    """A throwaway project root for the eval tools: temp config, temp data files, swappable fake providers."""

    def __init__(self, root: Path, providers) -> None:
        self.dir = root
        self.providers = providers
        self.judging = root / "judging"
        self.results = root / "results"
        self.qrels_path = root / "qrels.tsv"
        self.queries_path = root / "queries.jsonl"
        self.gold_path = root / "gold.csv"
        self.judgments_path = root / "judgments.jsonl"

    def write_queries(self, rows=None) -> None:
        import json

        rows = QUERY_ROWS if rows is None else rows
        self.queries_path.write_text("".join(json.dumps(r) + "\n" for r in rows), encoding="utf-8")

    def write_qrels(self, rows) -> None:
        """rows: iterable of (qid, doc_id, grade)."""
        lines = ["qid\tdoc_id\tgrade"] + [f"{q}\t{d}\t{g}" for q, d, g in rows]
        self.qrels_path.write_text("\n".join(lines) + "\n", encoding="utf-8")

    def write_gold(self, doc_ids) -> None:
        lines = ["overruled_doc_id,overruling_doc_id,point,source,verified_by"] + [f"{d},Z,a point,a judgment,L1" for d in doc_ids]
        self.gold_path.write_text("\n".join(lines) + "\n", encoding="utf-8")


@pytest.fixture
def eval_workspace(tmp_path, write_config, monkeypatch, make_providers):
    ws = Workspace(tmp_path, make_providers())
    cfg_path = write_config(tmp_path / "config.yaml", {
        "paths": {"queries": str(ws.queries_path), "qrels": str(ws.qrels_path), "gold_overrulings": str(ws.gold_path),
                  "results_dir": str(ws.results), "judgments": str(ws.judgments_path)},
        "evaluation": {"judging_dir": str(ws.judging)},
        "ranking": {"use_tuned": False, "tuned_file": str(tmp_path / "weights_tuned.yaml")},
    })
    monkeypatch.setenv("LEXSHIFT_CONFIG", str(cfg_path))
    import eval.pool as pool
    import eval.run_ablation as run_ablation

    for module in (pool, run_ablation):
        monkeypatch.setattr(module, "load_providers", lambda cfg=None: ws.providers)
    ws.write_queries()
    return ws


@pytest.fixture
def make_providers():
    def factory(table=None, *, stubbed=(), offence_ids=None):
        table = SCENARIO if table is None else table
        calls = {"search": 0, "parse_query": 0, "continuity": 0, "health": 0, "authority": 0}
        seen = {"search_k": [], "health_offence_ids": []}

        def search(query, k=100, filters=None):
            calls["search"] += 1
            seen["search_k"].append(k)
            ordered = sorted(table.items(), key=lambda kv: (-kv[1]["rel"], kv[0]))
            return [Hit(doc_id, v["rel"]) for doc_id, v in ordered[:k]]

        def parse_query(query, offence_date=None):
            calls["parse_query"] += 1
            refs = [StatuteRef(act="IPC", section="302", offence_id=o) for o in (offence_ids or [])]
            return QueryStatutes(query=query, offence_date=offence_date, governing_act=None, refs=refs)

        def continuity(qs, doc_id):
            calls["continuity"] += 1
            return table[doc_id]["cont"], table[doc_id].get("why") or "fixture"

        def health(doc_id, offence_ids=None):
            calls["health"] += 1
            seen["health_offence_ids"].append(offence_ids)
            return table[doc_id]["health"], list(table[doc_id].get("evidence", []))

        def authority(doc_id):
            calls["authority"] += 1
            return table[doc_id]["auth"]

        providers = Providers(search, parse_query, continuity, health, authority, frozenset(stubbed))
        # Providers is frozen; the counters are test instrumentation, so attach them around the freeze.
        object.__setattr__(providers, "calls", calls)
        object.__setattr__(providers, "seen", seen)
        return providers

    return factory
