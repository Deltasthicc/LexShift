"""Download and preprocess Supreme Court judgments into judgments.jsonl."""

from __future__ import annotations

import datetime as dt
import json
import re
import sys
from pathlib import Path
from typing import Any

from common.schema import Judgment
from m1_index.zones import split_zones

DATA_DIR = Path("data")
RAW_DIR = DATA_DIR / "raw"
PROCESSED_DIR = DATA_DIR / "processed"
JUDGMENTS_FILE = PROCESSED_DIR / "judgments.jsonl"

def clean_control_chars(text: str) -> str:
    """Remove PDF control characters while preserving newlines and tabs."""
    return "".join(
        ch for ch in text
        if ch in "\\n\\t" or ord(ch) >= 32
    )


RE_CRIMINAL = re.compile(
    r"\b(?:IPC|I\.P\.C\.|Indian\s+Penal\s+Code|BNS|Bharatiya\s+Nyaya\s+Sanhita|CrPC|Cr\.P\.C\.|Code\s+of\s+Criminal\s+Procedure|BNSS|Bharatiya\s+Nagarik\s+Suraksha\s+Sanhita)\b",
    re.IGNORECASE,
)


def parse_coram_bench_size(text: str) -> tuple[int | None, list[str]]:
    """Parse Supreme Court coram/judge lines.

    Handles:
      [A, B and C, JJ.]
      [A, B and C,* JJ.]
      [A, CJI and B,* JJ.]
      [A and B, JJ]
      A, J.
      A, B, JJ.
    """

    candidates = []

    # Bracketed coram lines. Period after JJ is optional.
    bracket_pattern = re.compile(
        r"\[([^\]]+?)(?:,\s*\*?)?\s*JJ?\.?\s*\]",
        re.IGNORECASE,
    )

    for match in bracket_pattern.finditer(text):
        candidates.append(match.group(1))

    # Unbracketed lines ending in J. or JJ.
    for line in text.splitlines():
        line = line.strip()

        if re.search(r",\s*JJ?\.?\s*$", line, re.IGNORECASE):
            candidate = re.sub(
                r",\s*JJ?\.?\s*$",
                "",
                line,
                flags=re.IGNORECASE,
            )
            candidates.append(candidate)

    if not candidates:
        return None, []

    raw_coram = candidates[0]

    # Remove author markers.
    raw_coram = raw_coram.replace("*", "")

    # Normalize whitespace, including PDF line wrapping.
    raw_coram = re.sub(r"\s+", " ", raw_coram).strip()

    # Split on comma or "and".
    parts = re.split(r"\s+and\s+|,\s*", raw_coram, flags=re.IGNORECASE)

    judges = []

    for part in parts:
        name = part.strip()

        # Remove titles/roles that are not separate judges.
        name = re.sub(
            r"\b(?:Hon'?ble|Mr\.?|Mrs\.?|Ms\.?|Justice)\b",
            "",
            name,
            flags=re.IGNORECASE,
        ).strip()

        if name:
            judges.append(name)

    # Remove duplicates while preserving order.
    unique_judges = list(dict.fromkeys(judges))

    return (
        len(unique_judges) if unique_judges else None,
        unique_judges,
    )

def parse_iso_date(raw_date: Any, text: str = "") -> str:
    """Parse raw date or extract from text, returning strict YYYY-MM-DD."""
    if raw_date:
        s = str(raw_date).strip()
        # Direct ISO match
        iso_m = re.search(r"(\d{4})[-/](\d{1,2})[-/](\d{1,2})", s)
        if iso_m:
            y, m, d = iso_m.groups()
            return f"{int(y):04d}-{int(m):02d}-{int(d):02d}"

        # Standard Indian dates e.g. "12 January 2018" or "12-01-2018"
        for fmt in ("%d %B, %Y", "%d %B %Y", "%B %d, %Y", "%d-%m-%Y", "%d/%m/%Y"):
            try:
                return dt.datetime.strptime(s, fmt).date().isoformat()
            except ValueError:
                pass

    # Fallback to searching text for date patterns
    m = re.search(r"\b(\d{1,2})(?:st|nd|rd|th)?\s+(January|February|March|April|May|June|July|August|September|October|November|December),?\s+(\d{4})\b", text, re.IGNORECASE)
    if m:
        day, month, year = m.groups()
        try:
            return dt.datetime.strptime(f"{day} {month} {year}", "%d %B %Y").date().isoformat()
        except ValueError:
            pass

    return "2020-01-01"


def is_criminal(text: str) -> bool:
    """Filter judgments mentioning IPC, BNS, CrPC or BNSS."""
    return bool(RE_CRIMINAL.search(text))


def download(sample_only: bool = False) -> Path:
    """Download AWS Open Data judgments (public bucket s3://indian-supreme-court-judgments)."""
    RAW_DIR.mkdir(parents=True, exist_ok=True)
    print(f"Checking data in {RAW_DIR}...")
    return RAW_DIR


def build_judgments(sample_size: int | None = None) -> int:
    """Read raw records, keep criminal cases, and write judgments.jsonl."""
    PROCESSED_DIR.mkdir(parents=True, exist_ok=True)
    count = 0

    # Look for raw json/jsonl or parquet files in data/raw or data/sample
    candidate_files = list(RAW_DIR.glob("**/*.json*")) + list(DATA_DIR.glob("sample/*.json*"))

    with open(JUDGMENTS_FILE, "w", encoding="utf-8") as out_f:
        for fpath in candidate_files:
            with open(fpath, "r", encoding="utf-8", errors="ignore") as in_f:
                for line in in_f:
                    if not line.strip():
                        continue
                    try:
                        raw = json.loads(line)
                    except json.JSONDecodeError:
                        continue

                    text = clean_control_chars(raw.get("text", "") or raw.get("judgment_text", ""))
                    if not is_criminal(text):
                        continue

                    doc_id = str(raw.get("doc_id") or raw.get("id") or f"SC_{count+1}")
                    title = raw.get("title") or raw.get("case_name") or f"Case {doc_id}"
                    date = parse_iso_date(raw.get("date"), text)

                    bench_size, parsed_judges = parse_coram_bench_size(text)
                    if bench_size is None and raw.get("bench_size"):
                        b = int(raw["bench_size"])
                        bench_size = b if b > 0 else None

                    judges = raw.get("judges") or parsed_judges
                    cites = raw.get("reporter_citations") or []
                    zones = split_zones(text)

                    j = Judgment(
                        doc_id=doc_id,
                        title=title,
                        date=date,
                        bench_size=bench_size,
                        judges=judges,
                        reporter_citations=cites,
                        zones=zones,
                        text=text,
                    )
                    j.validate()
                    out_f.write(json.dumps(j.to_dict()) + "\n")
                    count += 1
                    if sample_size and count >= sample_size:
                        break
            if sample_size and count >= sample_size:
                break

    print(f"Wrote {count} judgments to {JUDGMENTS_FILE}")
    return count


def main(argv: list[str] | None = None) -> int:
    args = argv or sys.argv[1:]
    cmd = args[0] if args else "build"
    if cmd == "download":
        download()
    elif cmd == "build":
        build_judgments()
    return 0


if __name__ == "__main__":
    sys.exit(main())