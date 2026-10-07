"""The 50-judgment hand check of the extractor (README, "Done when": precision of at least 0.9 on 50 hand-checked judgments).

    python -m m2_statute.audit_sample --n 50          # writes data/labelling/m2_precision_sheet.csv (seeded, so the same sheet every time)
    python -m m2_statute.audit_sample --score         # reads the sheet back after a person has filled `correct` and prints the precision

For each sampled judgment the sheet lists up to four statute mentions the extractor found, with the text around them and the act and section it
assigned. A person reads the context and writes `y` if the act and section are right, `n` if either is wrong, and `x` if the text is not a
reference to a section at all. Precision is y / (y + n + x) over the rows that were filled. Nothing here labels anything: the sheet is blank
until a person fills it, and a bare section left UNKNOWN counts as right only if its context really names no act.
"""

from __future__ import annotations

import argparse
import csv
import json
import random
import sys
from pathlib import Path

from m2_statute.extractor import extract_mentions
from m2_statute.mapping import REPO_ROOT, load_config

SHEET = REPO_ROOT / "data" / "labelling" / "m2_precision_sheet.csv"
COLUMNS = ("doc_id", "mention", "extracted_act", "extracted_section", "context", "correct", "note")
CONTEXT = 110  # characters of text kept on each side of the mention


def sample(n: int = 50, per_doc: int = 4, seed: int = 0, judgments: Path | None = None) -> list[dict[str, str]]:
    src = judgments or REPO_ROOT / load_config()["paths"]["judgments"]
    rng = random.Random(seed)
    docs = []
    with src.open(encoding="utf-8") as fh:
        for line in fh:
            if line.strip():
                rec = json.loads(line)
                docs.append((rec["doc_id"], rec.get("date", ""), rec.get("text") or ""))
    rows: list[dict[str, str]] = []
    for doc_id, when, text in rng.sample(docs, min(n, len(docs))):
        mentions = extract_mentions(text, when)
        for m in rng.sample(mentions, min(per_doc, len(mentions))):
            ctx = text[max(0, m.start - CONTEXT): m.end + CONTEXT].replace("\n", " ")
            rows.append({"doc_id": doc_id, "mention": text[m.start: m.end].replace("\n", " "), "extracted_act": m.act, "extracted_section": m.section,
                         "context": ctx, "correct": "", "note": ""})
    return rows


def score(sheet: Path = SHEET) -> dict[str, float | int]:
    with sheet.open(encoding="utf-8", newline="") as fh:
        rows = [r for r in csv.DictReader(fh) if r["correct"].strip().lower() in {"y", "n", "x"}]
    right = sum(r["correct"].strip().lower() == "y" for r in rows)
    return {"judged": len(rows), "right": right, "precision": (right / len(rows)) if rows else float("nan")}


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="python -m m2_statute.audit_sample", description=__doc__.split("\n\n")[0])
    ap.add_argument("--n", type=int, default=50, help="judgments to sample")
    ap.add_argument("--score", action="store_true", help="score a filled sheet instead of writing one")
    ap.add_argument("--force", action="store_true", help="overwrite an existing sheet (refused otherwise: a person may already be filling it)")
    args = ap.parse_args(argv)
    if args.score:
        if not SHEET.exists():
            print(f"{SHEET} does not exist: run `python -m m2_statute.audit_sample` first", file=sys.stderr)
            return 1
        res = score()
        print(f"{res['judged']} mentions judged, {res['right']} right: precision {res['precision']:.3f}" if res["judged"] else "no row has been filled in yet")
        return 0
    if SHEET.exists() and not args.force:
        print(f"{SHEET} exists: refusing to overwrite it (use --force)", file=sys.stderr)
        return 1
    rows = sample(args.n)
    SHEET.parent.mkdir(parents=True, exist_ok=True)
    with SHEET.open("w", encoding="utf-8", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=COLUMNS, lineterminator="\n")
        w.writeheader()
        w.writerows(rows)
    print(f"wrote {len(rows)} mentions from {args.n} judgments to {SHEET}; a person fills `correct` with y, n or x")
    return 0


if __name__ == "__main__":
    sys.exit(main())
