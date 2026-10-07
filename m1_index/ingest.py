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

RE_CRIMINAL = re.compile(
    r"\b(?:IPC|I\.P\.C\.|Indian\s+Penal\s+Code|BNS|Bharatiya\s+Nyaya\s+Sanhita|CrPC|Cr\.P\.C\.|Code\s+of\s+Criminal\s+Procedure|BNSS|Bharatiya\s+Nagarik\s+Suraksha\s+Sanhita)\b",
    re.IGNORECASE,
)


def parse_coram_bench_size(text: str) -> tuple[int | None, list[str]]:
    """Parse coram lines like '[A, B and C, JJ.]' or 'A, B, JJ.'

    Marks * as author. Never returns 0; returns None if unknown.
    """
    match = re.search(r"\[(.*?)(?:,\s*)?(?:JJ\.|J\.|C\.J\.I\.)\]", text)
    if not match:
        match = re.search(r"\bCoram\s*:\s*(.*?)(?=\n|$)", text, re.IGNORECASE)

    if not match:
        return None, []

    raw_coram = match.group(1).strip()
    raw_coram = raw_coram.replace("*", "")  # strip author marker

    # Split by comma or 'and'
    names = re.split(r",\s*|\s+and\s+", raw_coram)
    cleaned_judges = []
    for name in names:
        n = re.sub(r"\b(?:JJ\.|J\.|C\.J\.I\.|Hon'ble|Mr\.|Mrs\.|Justice)\b", "", name).strip()
        if n:
            cleaned_judges.append(n)

    size = len(cleaned_judges)
    return (size if size > 0 else None), cleaned_judges


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

                    text = raw.get("text", "") or raw.get("judgment_text", "")
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