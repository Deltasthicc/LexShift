"""Executable form of the function contracts in Guide 4.3: each checker returns a list of problems (empty = OK).

Used by `python eval/smoke.py` (the gate before merging to main) and by the unit tests, so a module owner can
prove their real function honours exactly the shape M4 integrates against.
"""

from __future__ import annotations

import math
from typing import Any

from common.schema import ACTS, ZONES, Evidence, Hit, QueryStatutes, Result, TREATMENT_LABELS


def _is_number(x: Any) -> bool:
    return isinstance(x, (int, float)) and not isinstance(x, bool) and math.isfinite(x)


def _unit(x: Any) -> bool:
    return _is_number(x) and 0.0 <= x <= 1.0


def check_hits(hits: Any, k: int) -> list[str]:
    """search(query, k) -> list[Hit]: <= k hits, unique ids, finite non-negative rel, sorted by rel descending."""
    if not isinstance(hits, list):
        return [f"search() must return a list, got {type(hits).__name__}"]
    problems: list[str] = []
    if len(hits) > k:
        problems.append(f"search() returned {len(hits)} hits for k={k}")
    seen: set[str] = set()
    for i, h in enumerate(hits):
        if not isinstance(h, Hit):
            problems.append(f"hit[{i}] is {type(h).__name__}, expected common.schema.Hit")
            continue
        if not h.doc_id:
            problems.append(f"hit[{i}] has an empty doc_id")
        if h.doc_id in seen:
            problems.append(f"duplicate doc_id {h.doc_id!r}")
        seen.add(h.doc_id)
        if not _is_number(h.rel) or h.rel < 0:
            problems.append(f"hit[{i}].rel must be a finite number >= 0, got {h.rel!r}")
        if not isinstance(h.zone_scores, dict) or set(h.zone_scores) - set(ZONES):
            problems.append(f"hit[{i}].zone_scores keys must be within {ZONES}")
    rels = [h.rel for h in hits if isinstance(h, Hit) and _is_number(h.rel)]
    if any(a < b for a, b in zip(rels, rels[1:])):
        problems.append("hits must be sorted by rel, highest first")
    return problems


def check_query_statutes(qs: Any) -> list[str]:
    if not isinstance(qs, QueryStatutes):
        return [f"parse_query() must return QueryStatutes, got {type(qs).__name__}"]
    problems: list[str] = []
    if qs.governing_act is not None and qs.governing_act not in ACTS:
        problems.append(f"governing_act must be None or one of {ACTS}, got {qs.governing_act!r}")
    return problems


def check_continuity(out: Any) -> list[str]:
    """continuity(qs, doc_id) -> (score in [0,1], explanation)."""
    if not (isinstance(out, tuple) and len(out) == 2):
        return ["continuity() must return a (score, explanation) tuple"]
    score, why = out
    problems = []
    if not _unit(score):
        problems.append(f"continuity score must be in [0, 1], got {score!r}")
    if not (isinstance(why, str) and why.strip()):
        problems.append("continuity explanation must be a non-empty string")
    return problems


def check_evidence_items(items: Any) -> list[str]:
    if not isinstance(items, list):
        return ["evidence must be a list of {citing_doc, label, sentence} dicts"]
    problems = []
    for i, item in enumerate(items):
        if not isinstance(item, dict) or not {"citing_doc", "label", "sentence"} <= set(item):
            problems.append(f"evidence[{i}] needs citing_doc, label and sentence")
        elif item["label"] not in TREATMENT_LABELS:
            problems.append(f"evidence[{i}].label {item['label']!r} not in {TREATMENT_LABELS}")
    return problems


def check_health(out: Any) -> list[str]:
    """health(doc_id, offence_ids=None) -> (score in [0,1], evidence list)."""
    if not (isinstance(out, tuple) and len(out) == 2):
        return ["health() must return a (score, evidence) tuple"]
    score, evidence = out
    problems = []
    if not _unit(score):
        problems.append(f"health score must be in [0, 1], got {score!r}")
    return problems + check_evidence_items(evidence)


def check_authority(x: Any) -> list[str]:
    return [] if _unit(x) else [f"authority() must return a number in [0, 1], got {x!r}"]


def check_results(results: Any, k: int, candidate_ids: set[str] | None = None) -> list[str]:
    """rank() -> list[Result]: <= k, final in [0,1] and non-increasing, unique ids, each Result self-consistent."""
    if not isinstance(results, list):
        return [f"rank() must return a list, got {type(results).__name__}"]
    problems: list[str] = []
    if len(results) > k:
        problems.append(f"rank() returned {len(results)} results for k={k}")
    seen: set[str] = set()
    for i, r in enumerate(results):
        if not isinstance(r, Result):
            problems.append(f"result[{i}] is {type(r).__name__}, expected common.schema.Result")
            continue
        for name in ("final", "rel", "cont", "health", "auth"):
            if not _unit(getattr(r, name)):
                problems.append(f"result[{i}].{name} must be in [0, 1], got {getattr(r, name)!r}")
        if not r.explanation.strip():
            problems.append(f"result[{i}] has an empty explanation")
        if r.doc_id in seen:
            problems.append(f"duplicate doc_id {r.doc_id!r} in results")
        seen.add(r.doc_id)
        if candidate_ids is not None and r.doc_id not in candidate_ids:
            problems.append(f"result[{i}] {r.doc_id!r} was not among the search() candidates")
        if r.contributions and abs(sum(r.contributions.values()) - r.final) > 1e-9:
            problems.append(f"result[{i}] contributions do not sum to final")
    finals = [r.final for r in results if isinstance(r, Result)]
    if any(a < b for a, b in zip(finals, finals[1:])):
        problems.append("results must be sorted by final score, highest first")
    return problems
