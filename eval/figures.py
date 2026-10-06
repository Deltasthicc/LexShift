"""Figures for the report that are not results: the pipeline diagram.

    python -m eval.figures                 # writes docs/figures/pipeline.png and pipeline.svg

The diagram is drawn from the same structure as the Mermaid chart in docs/ARCHITECTURE.md (offline stage on the left, the live demo
on the right) so it can go into the PDF as an image. It shows no number: results come only from eval/run_ablation.py. matplotlib is
imported lazily, like in eval/plots.py, so the rest of eval/ works without it.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUT_DIR = ROOT / "docs" / "figures"

# Colours chosen to stay distinguishable without relying on hue alone (the kind of box is also written in the text).
KINDS = {
    "source": ("#eceff4", "#4c566a"),
    "module": ("#dbe9f6", "#1f5f99"),
    "file": ("#fdf3d8", "#8a6d1d"),
    "fuse": ("#e1f0df", "#2d6a2a"),
    "io": ("#f4e1ec", "#8a2d5f"),
}


def _box(ax, x: float, y: float, w: float, h: float, text: str, kind: str) -> tuple[float, float, float, float]:
    from matplotlib.patches import FancyBboxPatch

    fill, edge = KINDS[kind]
    ax.add_patch(FancyBboxPatch((x, y), w, h, boxstyle="round,pad=0.02,rounding_size=0.12", linewidth=1.3, facecolor=fill, edgecolor=edge))
    ax.text(x + w / 2, y + h / 2, text, ha="center", va="center", fontsize=8.2, color="#1b1f27", linespacing=1.25)
    return x, y, w, h


def _arrow(ax, a: tuple[float, float], b: tuple[float, float], dashed: bool = False, rad: float = 0.0) -> None:
    from matplotlib.patches import FancyArrowPatch

    ax.add_patch(FancyArrowPatch(a, b, arrowstyle="-|>", mutation_scale=11, linewidth=1.2, color="#3b4252",
                                 linestyle=(0, (3, 3)) if dashed else "-", connectionstyle=f"arc3,rad={rad}", shrinkA=1, shrinkB=1))


def _right(b):
    return b[0] + b[2], b[1] + b[3] / 2


def _left(b):
    return b[0], b[1] + b[3] / 2


def _top(b):
    return b[0] + b[2] / 2, b[1] + b[3]


def _bottom(b):
    return b[0] + b[2] / 2, b[1]


def pipeline(png: Path, svg: Path | None = None) -> bool:
    """Draw the pipeline. Returns False if matplotlib is unavailable."""
    try:
        import matplotlib

        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
        from matplotlib.patches import FancyBboxPatch
    except ImportError:
        return False
    plt.rcParams["svg.fonttype"] = "none"  # keep the text as text in the SVG so it can be edited and searched

    fig, ax = plt.subplots(figsize=(13, 6.2))
    ax.set_xlim(0, 26)
    ax.set_ylim(0, 12.4)
    ax.axis("off")

    for x, w, title in ((0.2, 11.6, "Offline: run once, frozen into data/processed"),
                        (12.4, 13.4, "Live demo: laptop CPU, offline, no language model")):
        ax.add_patch(FancyBboxPatch((x, 0.3), w, 11.4, boxstyle="round,pad=0.02,rounding_size=0.3", linewidth=1.0,
                                    facecolor="none", edgecolor="#9aa3b2", linestyle=(0, (5, 3))))
        ax.text(x + 0.35, 11.15, title, fontsize=9.2, fontweight="bold", color="#2e3440", va="center")

    # offline
    aws = _box(ax, 0.6, 8.2, 4.4, 1.6, "AWS Open Data\nSupreme Court judgments\n(CC-BY-4.0)", "source")
    m1 = _box(ax, 6.6, 8.2, 4.6, 1.6, "M1  ingest, zones,\ntokenise, positional index", "module")
    jf = _box(ax, 6.6, 5.7, 4.6, 1.3, "judgments.jsonl\nindex files", "file")
    m2 = _box(ax, 0.6, 3.2, 4.8, 1.8, "M2  statute extractor\ntyped IPC-BNS concordance", "module")
    m3 = _box(ax, 6.4, 3.2, 5.0, 1.8, "M3  citation windows,\ntreatment classifier, PageRank", "module")
    f2 = _box(ax, 0.6, 0.8, 4.8, 1.5, "doc_statutes.jsonl\nstatute_map.csv", "file")
    f3 = _box(ax, 6.4, 0.8, 5.0, 1.5, "citations.jsonl\ndoc_health.jsonl", "file")
    _arrow(ax, _right(aws), _left(m1))
    _arrow(ax, _bottom(m1), _top(jf))
    _arrow(ax, (jf[0] + 0.9, jf[1]), _top(m2), rad=0.15)
    _arrow(ax, (jf[0] + 2.8, jf[1]), _top(m3), rad=-0.05)
    _arrow(ax, _bottom(m2), _top(f2))
    _arrow(ax, _bottom(m3), _top(f3))

    # live: M1's candidates go to M2 and to M3 in parallel; each reads a frozen file written by the offline stage
    q = _box(ax, 12.9, 8.2, 3.3, 1.8, "query\n+ optional\noffence date", "io")
    s1 = _box(ax, 17.0, 8.2, 4.5, 1.8, "M1  search()\nBM25 top-100\nreads the index files", "module")
    s2 = _box(ax, 17.0, 5.1, 4.5, 1.8, "M2  continuity()\nreads doc_statutes.jsonl,\nstatute_map.csv", "module")
    s3 = _box(ax, 17.0, 2.0, 4.5, 1.8, "M3  health(), authority()\nreads doc_health.jsonl,\ncitations.jsonl", "module")
    rk = _box(ax, 22.3, 4.9, 3.3, 2.2, "M4  rank()\nnormalise, fuse,\nheap top-K", "fuse")
    out = _box(ax, 22.3, 1.0, 3.3, 2.2, "top-k results\nper-signal breakdown\nevidence sentences", "io")
    _arrow(ax, _right(q), _left(s1))
    _arrow(ax, _bottom(s1), _top(s2))
    _arrow(ax, (s1[0] + 0.7, s1[1]), (s3[0] + 0.7, s3[1] + s3[3]), rad=0.42)
    _arrow(ax, (s1[0] + s1[2], s1[1] + 0.5), (rk[0] + 0.6, rk[1] + rk[3]), rad=-0.25)
    _arrow(ax, _right(s2), _left(rk))
    _arrow(ax, _right(s3), (rk[0] + 0.6, rk[1]), rad=0.22)
    _arrow(ax, _bottom(rk), _top(out))

    ax.text(12.9, 5.9, "candidates from M1\nare scored by M2\nand M3 in parallel", fontsize=7.8, color="#4c566a", va="center")
    ax.text(12.9, 0.95, "final = w_r*rel + w_s*cont + w_h*health + w_a*auth\nweights tuned on dev queries only",
            fontsize=8.6, color="#2e3440", va="center", style="italic")

    fig.tight_layout()
    png.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(png, dpi=170)
    if svg is not None:
        fig.savefig(svg)
    plt.close(fig)
    return True


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--out", type=Path, default=OUT_DIR, help="output folder (default docs/figures)")
    args = ap.parse_args(argv)
    if not pipeline(args.out / "pipeline.png", args.out / "pipeline.svg"):
        print("matplotlib is not installed: pip install matplotlib")
        return 2
    print(f"wrote {args.out / 'pipeline.png'} and {args.out / 'pipeline.svg'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
