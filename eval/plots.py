"""Bar chart of the ablation table for the report. matplotlib is imported lazily so the rest of eval/ works without it."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Sequence

QUALITY = ("P@5", "R@10", "MAP", "nDCG@10")
COLOURS = {"b0": "#7f7f7f", "b1": "#1f77b4", "full": "#d95f02"}  # distinguishable for common colour-vision deficiencies


def bar_chart(rows: Sequence[dict[str, Any]], path: Path, title: str) -> bool:
    """Grouped bars: one group per metric, one bar per config. Returns False if matplotlib is unavailable."""
    try:
        import matplotlib

        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
    except ImportError:
        return False

    show_harm = any(r.get("harmful@10") not in ("", None) for r in rows)
    fig, axes = plt.subplots(1, 2 if show_harm else 1, figsize=(9 if show_harm else 7, 3.8),
                             gridspec_kw={"width_ratios": [4, 1]} if show_harm else None, squeeze=False)
    ax = axes[0][0]
    width = 0.8 / max(1, len(rows))
    for i, row in enumerate(rows):
        values = [float(row[m]) if row[m] not in ("", None) else 0.0 for m in QUALITY]
        xs = [j + i * width for j in range(len(QUALITY))]
        bars = ax.bar(xs, values, width, label=row["config"], color=COLOURS.get(row["config"], "#444444"))
        ax.bar_label(bars, fmt="%.2f", fontsize=7, padding=2)
    ax.set_xticks([j + width * (len(rows) - 1) / 2 for j in range(len(QUALITY))], QUALITY)
    ax.set_ylim(0, 1.05)
    ax.set_ylabel("higher is better")
    ax.legend(frameon=False, fontsize=8)
    ax.spines[["top", "right"]].set_visible(False)

    if show_harm:
        ax2 = axes[0][1]
        xs = list(range(len(rows)))
        values = [float(r["harmful@10"]) if r["harmful@10"] not in ("", None) else 0.0 for r in rows]
        bars = ax2.bar(xs, values, 0.6, color=[COLOURS.get(r["config"], "#444444") for r in rows])
        ax2.bar_label(bars, fmt="%.2f", fontsize=7, padding=2)
        ax2.set_xticks(xs, [r["config"] for r in rows])
        ax2.set_title("harmful@10 (lower is better)", fontsize=9)
        ax2.set_ylim(0, max(0.1, max(values) * 1.3))
        ax2.spines[["top", "right"]].set_visible(False)

    fig.suptitle(f"LexShift ablation: {title}", fontsize=10)
    fig.tight_layout()
    path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(path, dpi=160)
    plt.close(fig)
    return True
