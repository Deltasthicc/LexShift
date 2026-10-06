"""Citation windows (the citing sentence +/- 1-2 sentences) and the appeal-history filter.

Appeal history: if the cited case is the judgment under appeal (same parties, "impugned judgment", set aside), tag
is_appeal_history and exclude it. That is a reversal on appeal, not an overruling of a precedent.
IR concept: proximity windows around a term.
"""

from __future__ import annotations

from common.skeleton import not_implemented


def citation_window(text: str, start: int, end: int, before: int = 1, after: int = 1) -> str:
    not_implemented("M3", "windows.citation_window()")


def is_appeal_history(window: str, citing_title: str, cited_title: str) -> bool:
    not_implemented("M3", "windows.is_appeal_history()")
