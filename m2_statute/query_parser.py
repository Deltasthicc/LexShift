"""Query statute parser and lexicon linker."""

from __future__ import annotations

import datetime as _dt
import re

from common.schema import QueryStatutes, SchemaError, StatuteRef
from m2_statute.mapping import load_config
from m2_statute.extractor import MEGA_PAT, parse_sections, normalize_act

_PROCEDURAL = {"CRPC", "BNSS"}

PROSE_LEXICON = {
    "murder": "OFF_MURDER",
    "sedition": "OFF_SEDITION",
    "adultery": "OFF_ADULTERY",
    "mob lynching": "OFF_MOB_LYNCHING",
    "rape": "OFF_RAPE",
    "conspiracy": "OFF_CRIMINAL_CONSPIRACY",
    "cheating": "OFF_CHEATING",
}


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
    notes: list[str] = []
    
    # Set default date if none provided to ensure deterministic resolution
    effective_date = offence_date or "2020-01-01"

    # 1. Standard Citation Extraction
    for m in MEGA_PAT.finditer(query):
        if m.group(1):
            sec_str, act_str = m.group(1), m.group(2)
        elif m.group(3):
            act_str, sec_str = m.group(3), m.group(4)
        else:
            sec_str, act_str = m.group(5), None

        secs = parse_sections(sec_str)
        act = normalize_act(act_str, effective_date) if act_str else ("BNS" if effective_date >= "2024-07-01" else "IPC")
        if not act_str:
            notes.append(f"bare sections {secs} resolved to {act} by offence date")

        for s in secs:
            key = (act, s)
            counts[key] = counts.get(key, 0) + 1

    refs = [StatuteRef(act=a, section=s, count=c) for (a, s), c in counts.items()]

    # 2. Prose Lexicon Extraction (Type B Queries)
    for word, off_id in PROSE_LEXICON.items():
        if re.search(rf"\b{word}\b", query, re.IGNORECASE):
            refs.append(StatuteRef(act="UNKNOWN", section="PROSE", offence_id=off_id, count=1))
            notes.append(f"Lexicon matched '{word}' to {off_id}")

    # 3. Governing Act Logic
    known_acts = {r.act for r in refs if r.act != "UNKNOWN"}
    governing: str | None = None
    if offence_date is not None:
        procedural = bool(known_acts) and known_acts <= _PROCEDURAL
        governing = _act_for_date(offence_date, procedural)
        clash = known_acts - {governing}
        if clash:
            notes.append(f"explicit act {sorted(clash)} differs from {governing} implied by offence date; explicit act is used for matching")
    elif len(known_acts) == 1:
        governing = next(iter(known_acts))

    qs = QueryStatutes(query=query, offence_date=offence_date, governing_act=governing, refs=refs, notes=notes)
    qs.validate()
    return qs