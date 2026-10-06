"""Download the AWS Open Data judgments, extract text and metadata, keep criminal-law cases, write judgments.jsonl.

IR concept: "what is a document?". One judgment = one document; metadata becomes the parametric fields.

Data source: s3://indian-supreme-court-judgments (region ap-south-1, public, no AWS account, CC-BY-4.0). The
folder layout, parquet schema, text format (PDF or text) and size are NOT yet verified: inspect them first and
record the facts in DECISIONS.md before relying on them.
"""

from __future__ import annotations

import sys
from pathlib import Path

from common.skeleton import not_implemented, todo_main


def download(sample_only: bool = True) -> Path:
    """Fetch the metadata parquet and English judgments into data/raw/ (unsigned S3, polite, resumable)."""
    not_implemented("M1", "ingest.download()")


def extract_text(raw_path: Path) -> str:
    """PDF/text -> clean text. Watch for page headers, page numbers and line breaks inside words."""
    not_implemented("M1", "ingest.extract_text()")


def is_criminal(text: str) -> bool:
    """Keep a judgment if it mentions IPC, BNS, CrPC or BNSS (Guide section 5, M1 block)."""
    not_implemented("M1", "ingest.is_criminal()")


def build_judgments(sample_size: int | None = 200) -> int:
    """Write data/processed/judgments.jsonl (200-document sample by hour 3, full file by hour 8). Returns the count."""
    not_implemented("M1", "ingest.build_judgments()")


def main(argv: list[str] | None = None) -> int:
    return todo_main("M1", "ingest (download | build)")


if __name__ == "__main__":
    sys.exit(main())
