"""Citation windows (the citing sentence +/- 1-2 sentences) and the appeal-history filter.

Appeal history: if the cited case is the judgment under appeal (same parties, "impugned judgment", set aside), tag
is_appeal_history and exclude it. That is a reversal on appeal, not an overruling of a precedent.
IR concept: proximity windows around a term.
"""

from __future__ import annotations

import re

from m3_treatment.text import COMMON_NAME_WORDS, jaccard, party_tokens, sentence_index, sentence_spans, split_parties

DEFAULT_MAX_CHARS = 1500  # headnote citation lists can be one 3,000-character "sentence"; keep windows LLM-sized


def window_span(
    text: str,
    start: int,
    end: int,
    before: int = 1,
    after: int = 1,
    max_chars: int = DEFAULT_MAX_CHARS,
    spans: list[tuple[int, int]] | None = None,
) -> tuple[int, int]:
    """(start, end) of the citing sentence(s) plus `before` and `after` neighbours, capped at `max_chars`.

    When the cap bites, the neighbours go first; a single over-long sentence is cut to a span centred on the mention.
    """
    spans = spans if spans is not None else sentence_spans(text)
    if not spans:
        return start, end
    first, last = sentence_index(spans, start), sentence_index(spans, max(start, end - 1))
    for b, a in ((before, after), (0, 0)):
        lo, hi = spans[max(0, first - b)][0], spans[min(len(spans) - 1, last + a)][1]
        if hi - lo <= max_chars:
            return lo, hi
    mid = (start + end) // 2
    lo = max(spans[first][0], mid - max_chars // 2)
    hi = min(spans[last][1], lo + max_chars)
    return lo, hi


def citation_window(
    text: str,
    start: int,
    end: int,
    before: int = 1,
    after: int = 1,
    max_chars: int = DEFAULT_MAX_CHARS,
    spans: list[tuple[int, int]] | None = None,
) -> str:
    """The window text around the mention at text[start:end]."""
    lo, hi = window_span(text, start, end, before, after, max_chars, spans)
    return text[lo:hi].strip()


def marked_window(
    text: str,
    start: int,
    end: int,
    before: int = 1,
    after: int = 1,
    max_chars: int = DEFAULT_MAX_CHARS,
    spans: list[tuple[int, int]] | None = None,
) -> str:
    """The window with the cited mention wrapped in [[ ]], so a reader or classifier knows which case is meant."""
    lo, hi = window_span(text, start, end, before, after, max_chars, spans)
    start, end = max(lo, start), min(hi, end)
    return (text[lo:start] + "[[" + text[start:end] + "]]" + text[end:hi]).strip()


# ----------------------------------------------------------------------------------------------------------------
# Appeal history
# ----------------------------------------------------------------------------------------------------------------
# Words naming the government side say nothing about whether two cases share parties ("State of X v. A" and
# "State of X v. B" are different cases).
_GOVERNMENT = frozenset("state union india government govt central public prosecutor cbi nct".split())
_UNDER_APPEAL = re.compile(
    r"\bimpugned\s+(?:judgment|order|decision|common\s+judgment|final\s+judgment)"
    r"|\b(?:judgment|order|decision)\s+under\s+(?:appeal|challenge)"
    r"|\bappeals?\s+(?:is\s+|are\s+)?(?:directed\s+)?against\s+the\s+(?:judgment|order)",
    re.IGNORECASE,
)
_REVERSED = re.compile(r"\bset\s+aside\b|\breversed\b|\bquashed\b", re.IGNORECASE)
SAME_PARTIES_THRESHOLD = 0.6


def same_parties(citing_title: str, cited_title: str, common: frozenset[str] | set[str] = frozenset()) -> bool:
    """Same dispute: Jaccard on party-name tokens (government words removed) at or above SAME_PARTIES_THRESHOLD, AND
    at least one shared token that is distinctive (not a common name such as Ram or Singh, not in `common`).

    The second condition matters because a false "same parties" drops the edge as appeal history: "Ram Singh v. State of
    U.P." and "Ram Singh v. State of Haryana" are usually different people, and treating them as one dispute would hide
    a real overruling. `common` is the resolver's corpus stop list (title tokens frequent across the corpus).
    Order-insensitive, because appellant and respondent swap sides between the High Court and this Court.
    """
    if not cited_title or not citing_title:
        return False
    a, b = _private_tokens(citing_title), _private_tokens(cited_title)
    if not (a and b) or jaccard(a, b) < SAME_PARTIES_THRESHOLD:
        return False
    return bool((a & b) - COMMON_NAME_WORDS - set(common))


# A side that is the State ("State of Haryana", "State, rep. by Inspector of Police", "Union of India", "Govt. of NCT")
# names the prosecutor, not the dispute: two different accused both prosecuted in Haryana share it.
_GOVERNMENT_SIDE = re.compile(
    r"^\s*(?:the\s+)?(?:state|union\s+of\s+india|government|govt|central\s+bureau|c\.?b\.?i|commissioner|collector|"
    r"director|secretary|inspector|superintendent|nct|public\s+prosecutor)\b",
    re.IGNORECASE,
)


def _private_tokens(title: str) -> set[str]:
    """Party tokens of the non-government side(s) of a case name."""
    sides = [s for s in split_parties(title) if s and not _GOVERNMENT_SIDE.match(s)]
    return party_tokens(" ".join(sides), _GOVERNMENT)


def is_appeal_history(
    window: str,
    citing_title: str,
    cited_title: str,
    cited_is_sc: bool = True,
    common: frozenset[str] | set[str] = frozenset(),
) -> bool:
    """True when the cited decision is this case's own history (the judgment under appeal, review or remand).

    * Same parties as the citing judgment, sharing a distinctive name: the earlier round of the same dispute (High
      Court order, review petition).
    * A non-Supreme-Court decision cited as the impugned judgment, or described as set aside / reversed / quashed: a
      reversal on appeal, which is never an overruling of a precedent.
    A Supreme Court precedent with different parties is never appeal history, whatever words surround it.
    """
    if same_parties(citing_title, cited_title, common):
        return True
    if cited_is_sc:
        return False
    return bool(_UNDER_APPEAL.search(window) or _REVERSED.search(window))
