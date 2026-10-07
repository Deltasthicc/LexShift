"""Bar chart of the ablation table for the report. matplotlib is imported lazily so the rest of eval/ works without it."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Sequence

QUALITY = ("P@5", "R@10", "MAP", "nDCG@10")
COLOURS = {"b0": "#7f7f7f", "b1": "#1f77b4", "full": "#d95f02"}  # distinguishable for common colour-vision deficiencies


def _value(raw: Any) -> float | None:
    """A table cell as a number, or None when the metric is undefined (empty cell)."""
    return None if raw in ("", None) else float(raw)


def _bars(ax, xs: Sequence[float], values: Sequence[float | None], width: float, **kwargs) -> None:
    """Draw bars with value labels; an undefined metric gets an 'n/a' mark instead of a bar that would read as zero."""
    for x, v in zip(xs, values):
        if v is None:
            ax.text(x, 0.015, "n/a", ha="center", va="bottom", fontsize=7, rotation=90, color="#555555")
        else:
            bar = ax.bar([x], [v], width, **kwargs)
            ax.bar_label(bar, fmt="%.2f", fontsize=7, padding=2)


def bar_chart(rows: Sequence[dict[str, Any]], path: Path, title: str) -> bool:
    """Grouped bars: one group per metric, one bar per config. Returns False if matplotlib is unavailable."""
    try:
        import matplotlib

        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
    except ImportError:
        return False

    show_harm = any(_value(r.get("harmful@10")) is not None for r in rows)
    fig, axes = plt.subplots(1, 2 if show_harm else 1, figsize=(9 if show_harm else 7, 3.8),
                             gridspec_kw={"width_ratios": [4, 1]} if show_harm else None, squeeze=False)
    ax = axes[0][0]
    width = 0.8 / max(1, len(rows))
    for i, row in enumerate(rows):
        xs = [j + i * width for j in range(len(QUALITY))]
        _bars(ax, xs, [_value(row[m]) for m in QUALITY], width, color=COLOURS.get(row["config"], "#444444"))
    ax.legend(handles=[plt.Rectangle((0, 0), 1, 1, color=COLOURS.get(r["config"], "#444444")) for r in rows],
              labels=[r["config"] for r in rows], frameon=False, fontsize=8)
    ax.set_xticks([j + width * (len(rows) - 1) / 2 for j in range(len(QUALITY))], QUALITY)
    ax.set_ylim(0, 1.05)
    ax.set_ylabel("higher is better")
    ax.spines[["top", "right"]].set_visible(False)

    if show_harm:
        ax2 = axes[0][1]
        values = [_value(r.get("harmful@10")) for r in rows]
        for i, (row, v) in enumerate(zip(rows, values)):
            _bars(ax2, [i], [v], 0.6, color=COLOURS.get(row["config"], "#444444"))
        ax2.set_xticks(range(len(rows)), [r["config"] for r in rows])
        ax2.set_title("harmful@10 (lower is better)", fontsize=9)
        ax2.set_ylim(0, max(0.1, max((v for v in values if v is not None), default=0.0) * 1.3))
        ax2.spines[["top", "right"]].set_visible(False)

    fig.suptitle(f"LexShift ablation: {title}", fontsize=10)
    fig.tight_layout()
    path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(path, dpi=160)
    plt.close(fig)
    return True
