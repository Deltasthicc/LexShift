"""Statute-citation extractor for judgments; writes data/processed/doc_statutes.jsonl."""

from __future__ import annotations

import json
import re
from datetime import date
from pathlib import Path

from common.schema import DocStatutes, SchemaError, StatuteRef
from m2_statute.mapping import REPO_ROOT, load_config

# --- Regex Engine ---
_PREFIX = r"(?:Sections?|u/s|S\.|Sec\.?)"
_ACT_PART = r"(IPC|I\.P\.C\.|Indian\s+Penal\s+Code|BNS|Bharatiya\s+Nyaya\s+Sanhita|CrPC|Cr\.P\.C\.|Code\s+of\s+Criminal\s+Procedure|BNSS|Bharatiya\s+Nagarik\s+Suraksha\s+Sanhita|the\s+Code)"
_SEC_TOK = r"\d+[A-Za-z\-]*"
_SEP = r"(?:\s*(?:,|/|and|r/w|read\s+with|&)\s*)"
_SEC_LIST = rf"({_SEC_TOK}(?:{_SEP}{_SEC_TOK})*)"

# A: u/s 302 IPC (Prefix -> Sections -> Act)
_PAT_A = rf"\b{_PREFIX}\s+{_SEC_LIST}\s*(?:of\s+(?:the\s+)?)?{_ACT_PART}\b"
# B: IPC u/s 302 (Act -> Prefix -> Sections)
_PAT_B = rf"\b{_ACT_PART}\s+(?:of\s+(?:the\s+)?)?{_PREFIX}\s+{_SEC_LIST}\b"
# C: u/s 302 (Bare Section - Date Resolved)
_PAT_C = rf"\b{_PREFIX}\s+{_SEC_LIST}\b"

MEGA_PAT = re.compile(f"(?:{_PAT_A})|(?:{_PAT_B})|(?:{_PAT_C})", re.IGNORECASE)

# --- Offence Lexicon ---
OFFENCE_MAP = {
    ("IPC", "302"): "OFF_MURDER",
    ("BNS", "103"): "OFF_MURDER",
    ("IPC", "124A"): "OFF_SEDITION",
    ("BNS", "152"): "OFF_SEDITION",
    ("IPC", "497"): "OFF_ADULTERY",
    ("IPC", "307"): "OFF_ATTEMPTED_MURDER",
    ("BNS", "109"): "OFF_ATTEMPTED_MURDER",
    ("IPC", "120B"): "OFF_CRIMINAL_CONSPIRACY",
    ("BNS", "61"): "OFF_CRIMINAL_CONSPIRACY",
    ("IPC", "376"): "OFF_RAPE",
    ("BNS", "63"): "OFF_RAPE",
}


def parse_sections(sec_str: str) -> list[str]:
    """Tokenize '302/34' or '120-B' into clean string identifiers."""
    nums = re.findall(r"\d+[A-Za-z\-\(\)]*", sec_str)
    return [re.sub(r"[^A-Z0-9\(\)]", "", n.upper()) for n in nums]


def normalize_act(act_str: str, j_date: str) -> str:
    """Map Act strings to canonical IDs, resolving 'The Code' by date."""
    a = act_str.upper()
    if "BNS" in a and "BNSS" not in a: return "BNS"
    if "BNSS" in a or "NAGARIK" in a: return "BNSS"
    if "IPC" in a or "PENAL" in a: return "IPC"
    if "CRPC" in a or "CR.P.C" in a or "PROCEDURE" in a: return "CRPC"
    
    if "CODE" in a:
        try:
            is_new = date.fromisoformat(j_date) >= date.fromisoformat("2024-07-01")
            return "BNSS" if is_new else "CRPC"
        except (ValueError, TypeError):
            return "CRPC"
            
    return "UNKNOWN"


def extract_refs(text: str, j_date: str) -> list[StatuteRef]:
    """Single-pass O(N) regex extraction of statutory references."""
    counts: dict[tuple[str, str], int] = {}
    
    try:
        is_new = date.fromisoformat(j_date) >= date.fromisoformat("2024-07-01")
    except (ValueError, TypeError):
        is_new = False

    for m in MEGA_PAT.finditer(text):
        if m.group(1):
            sec_str, act_str = m.group(1), m.group(2)
        elif m.group(3):
            act_str, sec_str = m.group(3), m.group(4)
        else:
            sec_str, act_str = m.group(5), None

        secs = parse_sections(sec_str)
        act = normalize_act(act_str, j_date) if act_str else ("BNS" if is_new else "IPC")

        for s in secs:
            key = (act, s)
            counts[key] = counts.get(key, 0) + 1

    refs = []
    for (a, s), c in sorted(counts.items()):
        oid = OFFENCE_MAP.get((a, s))
        refs.append(StatuteRef(act=a, section=s, offence_id=oid, count=c))
    
    return refs


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

    return {
        "docs": len(records),
        "docs_with_refs": sum(1 for r in records if r.refs),
        "docs_empty": sum(1 for r in records if not r.refs),
        "total_refs": sum(len(r.refs) for r in records),
    }

if __name__ == "__main__":
    stats = run()
    print(f"docs={stats['docs']} with_refs={stats['docs_with_refs']} empty={stats['docs_empty']} total_refs={stats['total_refs']}")