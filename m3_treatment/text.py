"""Text helpers shared by the M3 pipeline: PDF-noise cleanup, a legal-aware sentence splitter and party-name tokens.

Supreme Court Reports PDFs carry margin letters (A to H on their own line), running page headers and line breaks inside
case names ("Suresh\\nKumar Koushal"). Citation extraction and windows work on `clean_text()` output, so every
character offset in the M3 pipeline refers to the cleaned string, never to the raw `text` field.
"""

from __future__ import annotations

import re
from bisect import bisect_right

# A line that is only a margin letter (A-H), a page number or the reporter's running head ("SUPREME COURT REPORTS",
# "[2018] 13 S.C.R." with or without a page) is PDF furniture. Left in, a running head glues onto the next paragraph
# number and reads as a citation ("[2018] 11 S.C.R." + "62." -> "[2018] 11 S.C.R. 62"). Case-law lists in the
# headnote write "SCR" without dots, so they are not touched.
_NOISE_LINE = re.compile(r"^\s*(?:[A-H]|\d{1,4}|SUPREME COURT REPORTS|\[\d{4}\]\s*\d{1,2}\s+S\.C\.R\.(?:\s+\d{1,4})?)\s*$")
_HYPHEN_BREAK = re.compile(r"(\w)-\n(\w)")
_SPACES = re.compile(r"\s+")


def clean_text(text: str) -> str:
    """Drop margin letters and bare page numbers, join wrapped lines, collapse whitespace."""
    lines = [ln for ln in text.splitlines() if not _NOISE_LINE.match(ln)]
    joined = "\n".join(lines)
    # "same-\nsex" keeps its hyphen; only the line break goes.
    joined = _HYPHEN_BREAK.sub(r"\1-\2", joined)
    return _SPACES.sub(" ", joined).strip()


# ----------------------------------------------------------------------------------------------------------------
# Sentence splitting
# ----------------------------------------------------------------------------------------------------------------
# Tokens that end with a period but do not end a sentence in Indian judgments (lower-cased, without the period).
ABBREVIATIONS = frozenset(
    """
    v vs ors anr no nos s ss sec secs art arts cl cls r rr o ord cr crl cri pc c p j jj hon'ble mr mrs ms dr ltd co pvt
    i e g viz etc cf para paras pp vol supp suppl ed eds st govt dept u w r/w ibid id al sr jr smt sh shri km kum bros
    corpn corp inc assn mfg mt exh ex reg regd ch chap sch addl spl dist distt
    """.split()
)
_BOUNDARY = re.compile(r"[.?!][\"'”’)\]]*\s+(?=[\"'“‘(\[]?[A-Z0-9])")
_LAST_TOKEN = re.compile(r"([A-Za-z0-9'/]+)[.?!][\"'”’)\]]*\s+$")


def sentence_spans(text: str) -> list[tuple[int, int]]:
    """(start, end) character spans of sentences, protecting legal abbreviations, initials and citations.

    A period ends a sentence only when it is followed by whitespace and an upper-case letter, digit or opening quote,
    and the token before it is not an abbreviation ("v.", "Ors.", "S.", "Cr.P.C.") and not a single letter (initials
    such as "M. A. Antony"). A paragraph number ("96. For all these reasons") stays with its sentence.
    """
    spans: list[tuple[int, int]] = []
    start = 0
    for m in _BOUNDARY.finditer(text):
        before = text[max(start, m.start() - 40) : m.end()]
        tok = _LAST_TOKEN.search(before)
        if tok:
            word = tok.group(1).lower()
            if word in ABBREVIATIONS or len(word) == 1:
                continue
            if word.isdigit() and text[start : m.start()].strip().isdigit():
                continue
        spans.append((start, m.end()))
        start = m.end()
    if start < len(text):
        spans.append((start, len(text)))
    return [(s, e) for s, e in spans if text[s:e].strip()]


def sentence_index(spans: list[tuple[int, int]], offset: int) -> int:
    """Index of the sentence containing character `offset`."""
    starts = [s for s, _ in spans]
    return max(0, bisect_right(starts, offset) - 1)


# ----------------------------------------------------------------------------------------------------------------
# Party names
# ----------------------------------------------------------------------------------------------------------------
# Words that say nothing about WHICH case it is: connectors, honorifics, corporate suffixes and "and others".
PARTY_STOPWORDS = frozenset(
    """
    v vs versus and the of in re ors anr others another etc thr through rep represented by its m s ms mr mrs dr ltd
    pvt private limited co company sri shri smt kumari km alias @ the a an for to on at with sq ldr retd
    """.split()
)
_VERSUS = re.compile(r"\s+(?:v\.?|vs\.?|versus)\s+", re.IGNORECASE)
_WORD = re.compile(r"[a-z0-9]+")


def split_parties(title: str) -> tuple[str, str]:
    """('petitioner side', 'respondent side'); the respondent side is '' when there is no "v."/"versus"."""
    parts = _VERSUS.split(title, maxsplit=1)
    return (parts[0], parts[1]) if len(parts) == 2 else (title, "")


def party_tokens(name: str, extra_stopwords: frozenset[str] | set[str] = frozenset()) -> set[str]:
    """Informative lower-case tokens of a case name: no connectors, initials, honorifics or "and others"."""
    return {
        t
        for t in _WORD.findall(name.lower())
        if len(t) > 1 and not t.isdigit() and t not in PARTY_STOPWORDS and t not in extra_stopwords
    }


def jaccard(a: set[str], b: set[str]) -> float:
    """|A intersect B| / |A union B|; 0 when both are empty."""
    if not a and not b:
        return 0.0
    return len(a & b) / len(a | b)
