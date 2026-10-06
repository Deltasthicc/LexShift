"""Human-readable explanation of one result's score: the arithmetic and the reason behind each signal.

The wording says "treatment signals" and names the label M3 assigned. It never calls a case "bad law" or "dead law".
Plain ASCII only, so it prints on any console.
"""

from __future__ import annotations

import re
from typing import Mapping, Sequence

def _health_reason(evidence: Sequence[Mapping[str, str]]) -> str:
    if not evidence:
        return ""
    first = evidence[0]
    more = f" +{len(evidence) - 1} more" if len(evidence) > 1 else ""
    return f"{first['label']} per {first['citing_doc']}{more}"


_STUB_TAG = " [STUB signals, not real:"
_SEPARATOR = " | "


_CONTROLS = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")


def strip_controls(text: object) -> str:
    """Drop control characters. PDF extraction leaves backspaces and bells in judgment text (M1's corpus has them in every
    document); they would otherwise reach the terminal and the judges' spreadsheets."""
    return _CONTROLS.sub("", str(text))


def _clean(text: object) -> str:
    """Make module-supplied text safe to embed: one line, no control characters, never containing the piece separator."""
    return " ".join(strip_controls(text).replace("|", "/").split())


def split_explanation(explanation: str) -> list[str]:
    """The per-signal pieces of an explanation, without the trailing stub tag (for line-by-line display)."""
    return explanation.split(_STUB_TAG)[0].split(_SEPARATOR)


def build_explanation(
    raw: Mapping[str, float],
    normalised: Mapping[str, float],
    weights: Mapping[str, float],
    contributions: Mapping[str, float],
    cont_why: str,
    evidence: Sequence[Mapping[str, str]],
    stubbed: Sequence[str],
) -> str:
    """e.g. `rel 0.82 x 0.50 = 0.410 (BM25 14.20) | cont 1.00 x 0.20 = 0.200 (BNS 103 -> IPC 302 (equivalent)) | ...`"""
    parts: list[str] = []
    for s in ("rel", "cont", "health", "auth"):
        if weights.get(s, 0.0) <= 0:
            continue
        piece = f"{s} {normalised[s]:.2f} x {weights[s]:.2f} = {contributions[s]:.3f}"
        note = ""
        if s == "rel":
            note = f"BM25 {raw['rel']:.2f}"
        elif s == "cont":
            note = cont_why
        elif s == "health":
            note = _health_reason(evidence)
        elif s == "auth":
            note = f"raw {raw['auth']:.2f}"
        note = _clean(note)
        parts.append(f"{piece} ({note})" if note else piece)
    text = _SEPARATOR.join(parts)
    if stubbed:
        text += f"{_STUB_TAG} {', '.join(stubbed)}]"
    return text
