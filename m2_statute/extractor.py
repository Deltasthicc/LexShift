"""Statute-citation extractor for judgments; writes data/processed/doc_statutes.jsonl.

Must handle: "u/s 302/34 IPC", "Section 302 read with 34", "S. 302 I.P.C.", "Sections 302 and 307 of the Indian
Penal Code". "The Code" is resolved by judgment date. Bare "Section N" with no act is resolved from nearby act
mentions or recorded as act="UNKNOWN" (report its rate). Precision target: >= 0.9 on 50 hand-checked judgments.
"""

from __future__ import annotations
"""Statute-citation extractor (owner: M2). Hour 0-3 version.

Reads judgments.jsonl, finds act-qualified section mentions, writes doc_statutes.jsonl with exactly one
line per doc_id (refs may be empty). Scope is deliberately narrow: "IPC 302", "Section 302 IPC",
"Section 103 of the BNS". Not handled yet: "302/34", "r/w 34", "Sections 302 and 307", "I.P.C.",
"Indian Penal Code", subsections, and judgment-date resolution of "the Code".
"""

import json
from pathlib import Path

from common.schema import DocStatutes, SchemaError, StatuteRef
from m2_statute.mapping import REPO_ROOT, load_config
from m2_statute.query_parser import _ACT_FIRST, _SEC_FIRST


def extract_refs(text: str) -> list[StatuteRef]:
    """Act-qualified section mentions in `text`, counted per (act, section). Bare numbers are ignored."""
    counts: dict[tuple[str, str], int] = {}
    taken: list[tuple[int, int]] = []
    for pattern, act_group, sec_group in ((_ACT_FIRST, 1, 2), (_SEC_FIRST, 2, 1)):
        for m in pattern.finditer(text):
            if any(m.start() < b and a < m.end() for a, b in taken):  # overlaps an earlier match
                continue
            taken.append(m.span())
            key = (m.group(act_group).upper(), m.group(sec_group).upper())
            counts[key] = counts.get(key, 0) + 1
    return [StatuteRef(act=a, section=s, count=c) for (a, s), c in sorted(counts.items())]


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
            except (json.JSONDecodeError, KeyError) as exc:
                raise SchemaError(f"{src}, line {line_no}: {exc!r}") from exc
            if doc_id in seen:  # one output line per doc_id
                continue
            seen.add(doc_id)
            ds = DocStatutes(doc_id=doc_id, refs=extract_refs(text))
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
    print(f"docs={stats['docs']} with_refs={stats['docs_with_refs']} "
          f"empty={stats['docs_empty']} total_refs={stats['total_refs']}")