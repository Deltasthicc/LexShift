"""Case-citation extraction; writes data/processed/citations.jsonl together with resolver, windows and the classifier.

Formats: SCC, AIR, SCR, neutral citations (INSC), and "X v. Y" case names. Unresolved citations are kept with
cited_doc = null and counted, never silently dropped: report the resolution rate.
"""

from __future__ import annotations

import sys

from common.skeleton import not_implemented, todo_main


def extract_citations(text: str) -> list[dict]:
    """Raw citation mentions with their character spans, before resolution and classification."""
    not_implemented("M3", "citations.extract_citations()")


def main(argv: list[str] | None = None) -> int:
    return todo_main("M3", "citations build")


if __name__ == "__main__":
    sys.exit(main())
