"""Optional title/date/bench lookup so the demo can show case names, not just doc ids.

`data/processed/doc_meta.jsonl` (doc_id, title, date, bench_size) is derived from judgments.jsonl by
`python -m app.docmeta`, which streams the corpus once and drops the full text. The demo works without it and then shows
doc ids only.
"""

from __future__ import annotations

import sys
from typing import Any

from common.config import load_config, resolve_path
from common.io import read_jsonl, write_jsonl


def load_doc_meta(path=None) -> dict[str, dict[str, Any]]:
    path = path or resolve_path("doc_meta", load_config())
    if not path.exists():
        return {}
    return {rec["doc_id"]: rec for rec in read_jsonl(path)}


def build_doc_meta(src=None, dst=None) -> int:
    """Stream judgments.jsonl into doc_meta.jsonl; returns the number of records written."""
    cfg = load_config()
    src = src or resolve_path("judgments", cfg)
    dst = dst or resolve_path("doc_meta", cfg)
    if not src.exists():
        raise FileNotFoundError(f"{src} does not exist yet: M1 produces judgments.jsonl (make build-index)")
    return write_jsonl(
        dst,
        ({k: rec.get(k) for k in ("doc_id", "title", "date", "bench_size")} for rec in read_jsonl(src)),
    )


def describe(meta: dict[str, Any] | None) -> str:
    """`Title (2019-03-04, 5-judge bench)` from whatever fields are present, or an empty string."""
    if not meta:
        return ""
    extras = [meta["date"]] if meta.get("date") else []
    if meta.get("bench_size"):
        extras.append(f"{meta['bench_size']}-judge bench")
    title = meta.get("title") or ""
    return f"{title} ({', '.join(extras)})" if title and extras else title or ", ".join(extras)


def main(argv: list[str] | None = None) -> int:
    try:
        n = build_doc_meta()
    except FileNotFoundError as exc:
        print(exc)
        return 2
    print(f"wrote {n} records to {resolve_path('doc_meta', load_config())}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
