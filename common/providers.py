"""Resolve which implementation of each cross-module function is live: the real module or a fixed-value stub.

The switch is explicit and per group (config.yaml `stubs:`, overridable with LEXSHIFT_STUBS). There is deliberately
NO automatic fallback to a stub when a real function is missing or raises: a silent fallback would let a fake
number reach the demo or the evaluation unnoticed.

Signals (what rank() fuses) map onto provider groups:  rel -> search, cont -> statute, health -> health, auth -> authority.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Any, Callable

from common.config import STUB_GROUPS, ConfigError, load_config

SIGNAL_GROUP = {"rel": "search", "cont": "statute", "health": "health", "auth": "authority"}
ENV_VAR = "LEXSHIFT_STUBS"


@dataclass(frozen=True)
class Providers:
    """The five cross-module functions (Guide 4.3) plus which groups are served by stubs."""

    search: Callable[..., list]
    parse_query: Callable[..., Any]
    continuity: Callable[..., tuple]
    health: Callable[..., tuple]
    authority: Callable[[str], float]
    stubbed: frozenset[str]  # subset of STUB_GROUPS

    def stubbed_signals(self, signals: list[str] | tuple[str, ...] | None = None) -> list[str]:
        """Signals (rel/cont/health/auth) currently served by stubs, optionally restricted to `signals`."""
        wanted = list(signals) if signals is not None else list(SIGNAL_GROUP)
        return [s for s in wanted if SIGNAL_GROUP[s] in self.stubbed]

    def describe(self) -> str:
        parts = [f"{g}={'STUB' if g in self.stubbed else 'real'}" for g in STUB_GROUPS]
        return ", ".join(parts)


def stub_flags(cfg: dict[str, Any] | None = None) -> dict[str, bool]:
    """Group -> is-stubbed, from config.yaml, then LEXSHIFT_STUBS (all | none | comma list of groups to stub)."""
    cfg = cfg or load_config()
    flags = {g: bool(cfg["stubs"][g]) for g in STUB_GROUPS}
    override = os.environ.get(ENV_VAR)
    if override is None or not override.strip():
        return flags
    text = override.strip().lower()
    if text == "all":
        return {g: True for g in STUB_GROUPS}
    if text == "none":
        return {g: False for g in STUB_GROUPS}
    named = {part.strip() for part in text.split(",") if part.strip()}
    unknown = named - set(STUB_GROUPS)
    if unknown:
        raise ConfigError(f"{ENV_VAR}: unknown group(s) {sorted(unknown)}; use all, none or any of {STUB_GROUPS}")
    return {g: g in named for g in STUB_GROUPS}


def load_providers(cfg: dict[str, Any] | None = None, flags: dict[str, bool] | None = None) -> Providers:
    """Import only what is needed: real modules (and their heavy dependencies) load only when not stubbed."""
    flags = flags if flags is not None else stub_flags(cfg)
    import stubs  # light, always available

    if flags["search"]:
        search = stubs.search
    else:
        from m1_index import search

    if flags["statute"]:
        parse_query, continuity = stubs.parse_query, stubs.continuity
    else:
        from m2_statute import continuity, parse_query

    if flags["health"]:
        health = stubs.health
    else:
        from m3_treatment import health

    if flags["authority"]:
        authority = stubs.authority
    else:
        from m3_treatment import authority

    return Providers(
        search=search,
        parse_query=parse_query,
        continuity=continuity,
        health=health,
        authority=authority,
        stubbed=frozenset(g for g, on in flags.items() if on),
    )
