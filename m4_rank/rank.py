"""rank(): take the top candidates from search(), add the other signals, normalise, fuse, explain.

    final(q, d) = w_r*rel + w_s*cont + w_h*health + w_a*auth     (weights tuned on DEV queries only)

IR concepts: static quality score g(d) and net score, score normalisation, ablation configs (b0 / b1 / full).

The work is split in two so evaluation and tuning never repeat provider calls: `collect()` gathers the raw signals once per
query, and `fuse_collected()` turns them into a ranking for any weight vector. `rank()` is the two together.

Provider outputs are checked against the contracts at runtime. A malformed signal raises ContractViolation instead of
silently corrupting a ranking.
"""

from __future__ import annotations

import datetime as _dt
from dataclasses import dataclass
from typing import Any, Mapping

from common import contracts
from common.config import load_config
from common.providers import Providers, load_providers
from common.schema import QueryStatutes, Result
from m4_rank.fusion import SignalRow, fuse
from m4_rank.weights import SIGNALS, active_signals, load_weights


class ContractViolation(RuntimeError):
    """A provider (M1, M2 or M3 function) returned something that breaks its contract in docs/CONTRACTS.md."""


@dataclass
class Collected:
    """Raw signals for one query: everything needed to fuse under any weights without calling the providers again."""

    query: str
    offence_date: str | None
    signals: tuple[str, ...]  # signals that were collected, always including "rel"
    rows: list[SignalRow]
    stubbed: tuple[str, ...]  # collected signals served by fixed-value stubs


def _enforce(problems: list[str], where: str) -> None:
    if problems:
        raise ContractViolation(f"{where}: " + "; ".join(problems[:3]))


def _validate_inputs(query: str, offence_date: str | None) -> None:
    if not isinstance(query, str) or not query.strip():
        raise ValueError("query must be a non-empty string")
    if offence_date is not None:
        try:
            _dt.date.fromisoformat(offence_date)
        except (TypeError, ValueError) as exc:
            raise ValueError(f"offence_date must be an ISO date YYYY-MM-DD, got {offence_date!r}") from exc


def collect(
    query: str,
    offence_date: str | None = None,
    signals: tuple[str, ...] = SIGNALS,
    *,
    providers: Providers | None = None,
    candidates: int | None = None,
    cfg: dict[str, Any] | None = None,
) -> Collected:
    """Top-`candidates` hits from search(), plus the requested signals for each, all unmodified."""
    _validate_inputs(query, offence_date)
    cfg = cfg or load_config()
    providers = providers or load_providers(cfg)
    n = candidates or int(cfg["ranking"]["candidates"])
    wanted = tuple(s for s in SIGNALS if s == "rel" or s in signals)

    hits = providers.search(query, k=n)
    _enforce(contracts.check_hits(hits, n), "search()")
    rows = [SignalRow(doc_id=h.doc_id, raw={"rel": float(h.rel)}) for h in hits]

    qs: QueryStatutes | None = None
    if "cont" in wanted or "health" in wanted:
        qs = providers.parse_query(query, offence_date)
        _enforce(contracts.check_query_statutes(qs), "parse_query()")
    for row in rows:
        if "cont" in wanted:
            out = providers.continuity(qs, row.doc_id)
            _enforce(contracts.check_continuity(out), f"continuity({row.doc_id})")
            row.raw["cont"], row.cont_why = float(out[0]), out[1]
        if "health" in wanted:
            out = providers.health(row.doc_id, (qs.offence_ids or None) if qs else None)
            _enforce(contracts.check_health(out), f"health({row.doc_id})")
            row.raw["health"], row.evidence = float(out[0]), list(out[1])
        if "auth" in wanted:
            value = providers.authority(row.doc_id)
            _enforce(contracts.check_authority(value), f"authority({row.doc_id})")
            row.raw["auth"] = float(value)

    return Collected(query, offence_date, wanted, rows, tuple(providers.stubbed_signals(wanted)))


def fuse_collected(
    collected: Collected, weights: Mapping[str, float], k: int, cfg: dict[str, Any] | None = None
) -> list[Result]:
    """Rank already-collected signals under `weights`. Flags the signals that were stubbed and carry weight."""
    cfg = cfg or load_config()
    r = cfg["ranking"]
    flagged = [s for s in collected.stubbed if s in active_signals(weights)]
    return fuse(collected.rows, weights, r["normalize"], k, int(r["max_evidence"]), stubbed=flagged)


def rank(
    query: str,
    offence_date: str | None = None,
    k: int = 10,
    config: str = "full",
    *,
    providers: Providers | None = None,
) -> list[Result]:
    """Top-`k` results with per-signal breakdown and explanation. `config` is one of b0, b1, full (b2 = full).

    Only the providers a config needs are called: `b0` never touches the statute or treatment modules.
    """
    cfg = load_config()
    weights = load_weights(config, cfg)
    collected = collect(query, offence_date, active_signals(weights), providers=providers, cfg=cfg)
    return fuse_collected(collected, weights, k, cfg)
