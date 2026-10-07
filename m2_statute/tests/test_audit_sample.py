"""The 50-judgment hand-check sheet: seeded, blank until a person fills it, and scored only from what was filled."""

from __future__ import annotations

import csv
import json
from pathlib import Path

from m2_statute import audit_sample
from m2_statute.extractor import extract_mentions

TEXT = ("The appellant was convicted under Section 302 of the Indian Penal Code. Section 34 was invoked as well. "
        "Section 37 of the NDPS Act does not apply. The bail application under Section 439 of the Cr.P.C. was rejected. " * 3)


def _corpus(tmp_path: Path, n: int = 6) -> Path:
    f = tmp_path / "judgments.jsonl"
    f.write_text("\n".join(json.dumps({"doc_id": f"D{i}", "date": "2019-05-01", "text": TEXT}) for i in range(n)) + "\n", encoding="utf-8")
    return f


def test_mentions_carry_their_position_and_resolved_act() -> None:
    ms = extract_mentions(TEXT, "2019-05-01")
    assert [(m.act, m.section) for m in ms[:3]] == [("IPC", "302"), ("IPC", "34"), ("CRPC", "439")]
    assert TEXT[ms[0].start: ms[0].end].startswith("Section 302")
    assert all(m.section != "37" for m in ms)  # the NDPS section is not one of the four codes


def test_the_sheet_is_seeded_and_blank(tmp_path: Path) -> None:
    f = _corpus(tmp_path)
    a = audit_sample.sample(n=4, per_doc=2, seed=0, judgments=f)
    b = audit_sample.sample(n=4, per_doc=2, seed=0, judgments=f)
    assert a == b and len(a) == 8
    assert all(r["correct"] == "" and r["extracted_act"] in {"IPC", "CRPC", "UNKNOWN"} for r in a)
    assert all(r["mention"] and r["context"] for r in a)


def test_scoring_counts_only_the_rows_a_person_filled(tmp_path: Path) -> None:
    sheet = tmp_path / "sheet.csv"
    with sheet.open("w", encoding="utf-8", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=audit_sample.COLUMNS, lineterminator="\n")
        w.writeheader()
        for correct in ("y", "y", "n", "x", ""):
            w.writerow({"doc_id": "D", "mention": "m", "extracted_act": "IPC", "extracted_section": "1", "context": "c", "correct": correct, "note": ""})
    assert audit_sample.score(sheet) == {"judged": 4, "right": 2, "precision": 0.5}
