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
