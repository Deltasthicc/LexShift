"""The pipeline diagram is produced by code, so it can be regenerated and does not drift from the architecture."""

from __future__ import annotations

import pytest

pytest.importorskip("matplotlib")

from eval import figures  # noqa: E402


def test_the_pipeline_diagram_is_written_as_png_and_editable_svg(tmp_path):
    assert figures.main(["--out", str(tmp_path)]) == 0
    png, svg = tmp_path / "pipeline.png", tmp_path / "pipeline.svg"
    assert png.read_bytes()[:8] == b"\x89PNG\r\n\x1a\n"
    text = svg.read_text(encoding="utf-8")
    for label in ("rank()", "search()", "continuity()", "doc_health.jsonl", "doc_statutes.jsonl", "tuned on dev queries only"):
        assert label in text, label


def test_the_diagram_carries_no_measured_number(tmp_path):
    figures.main(["--out", str(tmp_path)])
    text = (tmp_path / "pipeline.svg").read_text(encoding="utf-8")
    assert "top-100" in text  # a configured candidate depth, not a result
    for banned in ("P@5", "nDCG", "kappa", "MAP"):
        assert banned not in text
