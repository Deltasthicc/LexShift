"""Statute-citation extractor for judgments; writes data/processed/doc_statutes.jsonl.

What it reads: references to sections of the four codes in the shared vocabulary (IPC, BNS, CRPC, BNSS), in the forms judgments use:
"u/s 302 IPC", "Section 302 read with 34 of the Indian Penal Code", "S. 302 I.P.C.", "Sections 302 and 307 IPC", "IPC 302", "BNS 3(5)", "the Code".

How the act of a reference is decided (IR concept: normalisation to a controlled vocabulary):

1. The act the text names. "The Code" is resolved by the judgment's date (before 1 July 2024 the CrPC, from then the BNSS).
2. A bare "Section N" has no act, so it takes one from the same judgment, never from the calendar:
   a. its code family is read off the statute map (a number that is a mapped CrPC or BNSS section is procedural, a mapped IPC or BNS section is substantive);
      the act is then the nearest explicit mention of that family in the judgment (the one before it, else the first after it);
   b. a number the map does not know takes the act of an explicit mention in the same paragraph, not more than 400 characters before it;
   c. otherwise it stays UNKNOWN. The UNKNOWN share is reported by `python -m m2_statute.extractor` and by eval.conformance.
3. A bare section followed by "of the <Name> Act" (or Rules, Constitution) belongs to another statute and is not a reference to the four codes: it is dropped, not counted as UNKNOWN.
"""

from __future__ import annotations

import json
import re
from bisect import bisect_left
from datetime import date
from functools import lru_cache
from pathlib import Path
from typing import NamedTuple

from common.schema import DocStatutes, SchemaError, StatuteRef
from m2_statute.mapping import REPO_ROOT, base_section, load_config, load_map

# --- Regex engine. The act alternatives end in a full stop for some forms (I.P.C., Cr.P.C.), so the closing test is (?!\w), not \b ---
_PREFIX = r"(?:Sections?|u/s|U/s|S\.|Sec\.?|Ss\.)"
_ACT_PART = (r"(IPC|I\.?\s?P\.?\s?C\.?|Indian\s+Penal\s+Code|Penal\s+Code|BNS|Bharatiya\s+Nyaya\s+Sanhita|CrPC|Cr\.?\s?P\.?\s?C\.?|"
             r"Code\s+of\s+Criminal\s+Procedure|BNSS|Bharatiya\s+Nagarik\s+Suraksha\s+Sanhita|the\s+Code)")
_SEC_TOK = r"\d+[A-Za-z\-]*(?:\([a-zA-Z0-9]+\))*"
_SEP = r"(?:\s*(?:,|/|and|r/w|read\s+with|&)\s*)"
_SEC_LIST = rf"({_SEC_TOK}(?:{_SEP}{_SEC_TOK})*)"

# A: u/s 302 IPC (prefix, sections, act)
_PAT_A = rf"\b{_PREFIX}\s+{_SEC_LIST}\s*(?:of\s+(?:the\s+)?)?{_ACT_PART}(?!\w)"
# B: IPC u/s 302 (act, prefix, sections)
_PAT_B = rf"\b{_ACT_PART}\s+(?:(?:of\s+(?:the\s+)?)?{_PREFIX}\s+)?{_SEC_LIST}(?!\w)"
# C: u/s 302 (a bare section: the act comes from the rest of the judgment, or, in a query, from the offence date)
_PAT_C = rf"\b{_PREFIX}\s+{_SEC_LIST}(?!\w)"

MEGA_PAT = re.compile(f"(?:{_PAT_A})|(?:{_PAT_B})|(?:{_PAT_C})", re.IGNORECASE)

_PROCEDURAL = ("CRPC", "BNSS")
_SUBSTANTIVE = ("IPC", "BNS")
_OTHER_ACT = re.compile(r"\s*(?:,\s*\d{4}\s*)?(?:of|under)\s+(?:the\s+)?(?:(?:[A-Z][\w.&'()-]*|of|and|for|in)\s+){0,8}?(?:Act|Rules|Constitution|Regulations?|Order)\b")
_NEAR = 400  # a bare section takes the act of an explicit mention this close before it (characters), when the map cannot tell its family

# Offences that are not rows of the statute map but that the judged queries are about
_EXTRA_OFFENCES = {("IPC", "497"): "OFF_ADULTERY"}


@lru_cache(maxsize=1)
def _provisions() -> tuple[dict[tuple[str, str], str], frozenset[str], frozenset[str]]:
    """From the statute map: offence id by (act, section), and the section numbers of each code family."""
    offence: dict[tuple[str, str], str] = dict(_EXTRA_OFFENCES)
    subst: set[str] = set()
    proc: set[str] = set()
    for r in load_map():
        oid = "OFF_" + re.sub(r"[^A-Z0-9]+", "_", r.note.upper()).strip("_") if r.note else None
        for act, sec in ((r.old_act, r.old_section), (r.new_act, r.new_section)):
            b = base_section(sec)
            (proc if act in _PROCEDURAL else subst).add(b)
            if oid:
                offence[(act, b)] = oid
    return offence, frozenset(subst), frozenset(proc)


def offence_id(act: str, section: str) -> str | None:
    return _provisions()[0].get((act, base_section(section)))


def family_of(section: str) -> str | None:
    """'procedural' (CrPC/BNSS), 'substantive' (IPC/BNS), 'ambiguous' (the map knows the number in both families), or None (the map does not know it)."""
    _, subst, proc = _provisions()
    b = base_section(section)
    if b in proc and b in subst:
        return "ambiguous"
    if b in proc:
        return "procedural"
    if b in subst:
        return "substantive"
    return None


def parse_sections(sec_str: str) -> list[str]:
    """Tokenize '302/34' or '120-B' or '3(5)' into clean string identifiers."""
    nums = re.findall(r"\d+[A-Za-z\-]*(?:\([A-Za-z0-9]+\))*", sec_str)
    return [re.sub(r"[^A-Z0-9()]", "", n.upper()) for n in nums]


def normalize_act(act_str: str, j_date: str) -> str:
    """Map the act as written ('I.P.C.', 'Cr. P.C.', 'Bharatiya Nyaya Sanhita') to IPC, BNS, CRPC or BNSS; 'the Code' is resolved by the judgment date."""
    a = re.sub(r"[.\s]", "", act_str.upper())
    if "BNSS" in a or "NAGARIK" in a:
        return "BNSS"
    if "BNS" in a or "NYAYA" in a:
        return "BNS"
    if "IPC" in a or "PENAL" in a:
        return "IPC"
    if "CRPC" in a or "PROCEDURE" in a:
        return "CRPC"
    if "CODE" in a:
        try:
            return "BNSS" if date.fromisoformat(j_date) >= date.fromisoformat("2024-07-01") else "CRPC"
        except (ValueError, TypeError):
            return "CRPC"
    return "UNKNOWN"


def _groups(m: re.Match[str]) -> tuple[str, str | None]:
    if m.group(1):
        return m.group(1), m.group(2)
    if m.group(3):
        return m.group(4), m.group(3)
    return m.group(5), None


class Mention(NamedTuple):
    """One section of one citation in a judgment: where it starts and ends in the text, and the act and section it was given."""

    start: int
    end: int
    act: str
    section: str


def extract_mentions(text: str, j_date: str) -> list[Mention]:
    """Every statute mention of one judgment with its act (see the module docstring for how a bare section gets one), in text order."""
    found: list[tuple[int, int, list[str], str | None]] = []  # (start, end, sections, act as normalised or None for a bare section)
    for m in MEGA_PAT.finditer(text):
        sec_str, act_str = _groups(m)
        secs = parse_sections(sec_str)
        if not secs:
            continue
        if act_str is None and _OTHER_ACT.match(text, m.end()):
            continue  # "Section 37 of the NDPS Act": another statute
        found.append((m.start(), m.end(), secs, normalize_act(act_str, j_date) if act_str else None))

    explicit = [(s, a) for s, _, _, a in found if a and a != "UNKNOWN"]
    by_family = {fam: [(s, a) for s, a in explicit if a in acts] for fam, acts in (("substantive", _SUBSTANTIVE), ("procedural", _PROCEDURAL))}
    starts = {fam: [s for s, _ in lst] for fam, lst in by_family.items()}
    all_starts = [s for s, _ in explicit]

    out: list[Mention] = []
    for start, end, secs, act in found:
        for s in secs:
            resolved = act
            if resolved is None:
                resolved = "UNKNOWN"
                fam = family_of(s)
                if fam in by_family:
                    if by_family[fam]:
                        i = bisect_left(starts[fam], start)
                        resolved = by_family[fam][i - 1][1] if i else by_family[fam][0][1]
                elif fam is None:
                    i = bisect_left(all_starts, start)
                    if i:
                        prev_start, prev_act = explicit[i - 1]
                        if start - prev_start <= _NEAR and "\n\n" not in text[prev_start:start]:
                            resolved = prev_act
            out.append(Mention(start, end, resolved, s))
    return out


def extract_refs(text: str, j_date: str) -> list[StatuteRef]:
    """Statutory references of one judgment: the mentions counted per (act, section)."""
    counts: dict[tuple[str, str], int] = {}
    for m in extract_mentions(text, j_date):
        counts[(m.act, m.section)] = counts.get((m.act, m.section), 0) + 1
    return [StatuteRef(act=a, section=s, offence_id=offence_id(a, s), count=c) for (a, s), c in sorted(counts.items())]


def run(judgments_path: Path | None = None, out_path: Path | None = None) -> dict[str, int]:
    paths = load_config()["paths"]
    src = judgments_path or REPO_ROOT / paths["judgments"]
    dst = out_path or REPO_ROOT / paths["doc_statutes"]

    if not src.exists():
        raise FileNotFoundError(f"{src} does not exist: M1 has not shipped judgments.jsonl yet")

    seen: set[str] = set()
    records: list[DocStatutes] = []

    with src.open(encoding="utf-8") as fh:
        for line_no, line in enumerate(fh, start=1):
            if not line.strip():
                continue
            try:
                rec = json.loads(line)
                doc_id = rec["doc_id"]
                text = rec.get("text") or ""
                j_date = rec.get("date", "2020-01-01")
            except (json.JSONDecodeError, KeyError) as exc:
                raise SchemaError(f"{src}, line {line_no}: {exc!r}") from exc

            if doc_id in seen:
                continue
            seen.add(doc_id)
            ds = DocStatutes(doc_id=doc_id, refs=extract_refs(text, j_date))
            for ref in ds.refs:
                ref.validate()
            records.append(ds)

    dst.parent.mkdir(parents=True, exist_ok=True)
    tmp = dst.with_suffix(".jsonl.tmp")
    with tmp.open("w", encoding="utf-8", newline="\n") as fh:
        for ds in records:
            fh.write(json.dumps(ds.to_dict(), ensure_ascii=True) + "\n")
    tmp.replace(dst)

    total = sum(r.count for ds in records for r in ds.refs)
    unknown = sum(r.count for ds in records for r in ds.refs if r.act == "UNKNOWN")
    return {
        "docs": len(records),
        "docs_with_refs": sum(1 for r in records if r.refs),
        "docs_empty": sum(1 for r in records if not r.refs),
        "total_refs": sum(len(r.refs) for r in records),
        "mentions": total,
        "unknown_mentions": unknown,
    }


if __name__ == "__main__":
    stats = run()
    print(f"docs={stats['docs']} with_refs={stats['docs_with_refs']} empty={stats['docs_empty']} total_refs={stats['total_refs']}")
    print(f"mentions={stats['mentions']} act UNKNOWN: {stats['unknown_mentions']} ({100 * stats['unknown_mentions'] / max(1, stats['mentions']):.1f}%)")
