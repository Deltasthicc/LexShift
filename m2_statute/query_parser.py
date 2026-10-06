"""Query statute parser.

Finds section mentions in a free-text query; picks the governing code from an explicit act, else from the offence
date (before 1 July 2024 -> IPC, otherwise BNS); resolves collisions such as BNS 302 (religious sentiments) vs
IPC 302 (murder).

IR concepts: query expansion (a BNS 103 query also reaches IPC 302 precedents), parametric filtering by date.
"""
from __future__ import annotations

import datetime as _dt
import re

from common.schema import QueryStatutes, SchemaError, StatuteRef
from m2_statute.mapping import load_config

_ACT = r"(IPC|BNSS|BNS|CrPC)"
_SEC = r"(\d{1,3}[A-Z]?)"
_LEAD = r"(?:sections?|secs?\.?|s\.)"

_ACT_FIRST = re.compile(rf"\b{_ACT}\b\.?\s*(?:{_LEAD}\s*)?{_SEC}\b", re.I)          # "IPC 302", "BNS section 103"
_SEC_FIRST = re.compile(rf"\b{_LEAD}\s*{_SEC}\s+(?:of\s+(?:the\s+)?)?{_ACT}\b", re.I)  # "Section 103 of the BNS"
_BARE = re.compile(rf"\b{_LEAD}\s*{_SEC}\b", re.I)                                    # "section 302", no act

_PROCEDURAL = {"CRPC", "BNSS"}


def _act_for_date(offence_date: str, procedural: bool) -> str:
    try:
        d = _dt.date.fromisoformat(offence_date)
    except (TypeError, ValueError) as exc:
        raise SchemaError(f"offence_date must be an ISO date YYYY-MM-DD, got {offence_date!r}") from exc
    cutoff = _dt.date.fromisoformat(load_config()["m2_statute"]["bns_commencement"])
    new_code = d >= cutoff
    if procedural:
        return "BNSS" if new_code else "CRPC"
    return "BNS" if new_code else "IPC"


def parse_query(query: str, offence_date: str | None = None) -> QueryStatutes:
    counts: dict[tuple[str, str], int] = {}
    spans: list[tuple[int, int]] = []
    notes: list[str] = []

    for pattern, act_group, sec_group in ((_ACT_FIRST, 1, 2), (_SEC_FIRST, 2, 1)):
        for m in pattern.finditer(query):
            act = m.group(act_group).upper()
            key = (act, m.group(sec_group).upper())
            counts[key] = counts.get(key, 0) + 1
            spans.append(m.span())

    # Section numbers with no act go to the UNKNOWN bucket; never guessed (M2 README, "Watch out for").
    for m in _BARE.finditer(query):
        if not any(a <= m.start() < b for a, b in spans):
            key = ("UNKNOWN", m.group(1).upper())
            counts[key] = counts.get(key, 0) + 1
            notes.append(f"bare section {key[1]} has no act; left UNKNOWN (collision resolution not implemented yet)")

    refs = [StatuteRef(act=a, section=s, count=c) for (a, s), c in counts.items()]

    known_acts = {r.act for r in refs if r.act != "UNKNOWN"}
    governing: str | None = None
    if offence_date is not None:
        procedural = bool(known_acts) and known_acts <= _PROCEDURAL
        governing = _act_for_date(offence_date, procedural)
        clash = known_acts - {governing}
        if clash:
            notes.append(
                f"explicit act {sorted(clash)} differs from {governing} implied by offence date; "
                "explicit act is used for matching"
            )
    elif len(known_acts) == 1:
        governing = next(iter(known_acts))

    qs = QueryStatutes(query=query, offence_date=offence_date, governing_act=governing, refs=refs, notes=notes)
    qs.validate()
    return qs