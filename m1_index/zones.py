"""Zone extraction for Supreme Court judgments using heading and positional heuristics.

Searchable zones (common.schema.ZONES):
  - headnote   everything before the judgment proper: caption, catchwords, cited cases, counsel (about 5 to 15 percent of a judgment)
  - facts      the opening of the reasoning
  - arguments  the parties' contentions and the discussion
  - holding    the court's conclusions, down to the final order

Two formats occur in the corpus and both are handled:

* the reporter's format of recent volumes: a "Headnotes" section, then "Case Law Cited", "List of Acts", then a line `JUDGMENT` or `ORDER`;
* the older Supreme Court Reports format: caption, bench, catchwords, counsel, then "The Judgment of the Court was delivered by ...".

The split is a rough heuristic, not an annotation: paragraph headings move the boundaries where they exist, and positions decide where they do not.
"""

from __future__ import annotations

import re

HEADNOTE_CAP = 15_000  # a catchword block longer than this is a headnote plus the list of cited cases; the rest belongs to the body
START_WINDOW = 0.40  # the judgment proper starts in the first 40 percent of the text, or the marker is not the one we want


def clean_text(text: str) -> str:
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def extract_numbered_paragraphs(text: str) -> list[tuple[int, str]]:
    """Extract numbered judgment paragraphs [(para_num, para_text), ...]."""
    pattern = re.compile(
        r"(?m)^\s*(\d{1,3})\.\s+(.*?)(?=^\s*\d{1,3}\.\s+|\Z)",
        re.DOTALL,
    )
    paragraphs = []
    for match in pattern.finditer(text):
        number = int(match.group(1))
        content = match.group(2).strip()
        if content:
            paragraphs.append((number, content))
    return paragraphs


def extract_headnote(text: str) -> str:
    """Extract the explicit Headnotes section if present."""
    match = re.search(
        r"\bHeadnotes?\b\s*(.*?)(?=\n\s*Case Law Cited\b|\n\s*List of Acts\b|\n\s*Judgment\b|\n\s*ORDER\b)",
        text,
        re.DOTALL | re.IGNORECASE,
    )
    if match:
        return match.group(1).strip()
    return ""


# where the judgment proper begins, most reliable marker first
RE_DELIVERED = re.compile(r"(?i)(?:the\s+)?(?:judgment|order|opinion)s?\s+of\s+the\s+court\s+(?:was|were)\s+delivered\s+by[^\n]*\n?")
RE_JUDGMENT_LINE = re.compile(r"(?im)^\s*(?:JUDGMENT|ORDER|J\s*U\s*D\s*G\s*M\s*E\s*N\s*T)\s*$\n?")
RE_FIRST_PARAGRAPH = re.compile(r"(?m)^\s*1\.\s+\S")


def body_start(text: str) -> int:
    """Offset at which the judgment proper begins (0 when no marker is found in the first 40 percent)."""
    limit = int(len(text) * START_WINDOW)
    for rx in (RE_DELIVERED, RE_JUDGMENT_LINE):
        m = rx.search(text)
        if m and m.start() <= limit:
            return m.end()
    m = RE_FIRST_PARAGRAPH.search(text)
    if m and m.start() <= limit:
        return m.start()
    return 0


def find_judgment_body(text: str) -> str:
    """Return text starting after the header/metadata and judgment declaration."""
    return text[body_start(text):]


def extract_result(text: str) -> str:
    """Extract final result line if tagged."""
    match = re.search(
        r"Result of the case:\s*(.*?)(?=\n|$)",
        text,
        re.IGNORECASE,
    )
    if match:
        return match.group(1).strip()
    return ""


# Regex patterns identifying zone shifts
RE_FACTS_HEADING = re.compile(
    r"\b(?:brief\s+facts|factual\s+matrix|factual\s+background|facts\s+of\s+the\s+case|prosecution\s+case)\b",
    re.IGNORECASE,
)
RE_ARGS_HEADING = re.compile(
    r"\b(?:submissions?|contentions?|arguments?|learned\s+(?:senior\s+)?counsel\s+(?:appearing\s+for|submitted|argued)|appellant(?:'s)?\s+submission|respondent(?:'s)?\s+submission)\b",
    re.IGNORECASE,
)
RE_HOLDING_HEADING = re.compile(
    r"\b(?:held|conclusion|finding|in\s+view\s+of\s+the\s+above|for\s+the\s+(?:foregoing\s+)?reasons|resultantly|we\s+hold|we\s+are\s+of\s+the\s+(?:considered\s+)?view|accordingly|the\s+appeals?\s+(?:is|are)\s+(?:allowed|dismissed)|order\s+accordingly)\b",
    re.IGNORECASE,
)


def _blocks(body: str, size: int = 8) -> list[str]:
    """Paragraph-like blocks for a body without usable paragraph numbers: groups of `size` non-empty lines."""
    lines = [ln.strip() for ln in body.split("\n") if ln.strip()]
    return ["\n".join(lines[i:i + size]) for i in range(0, len(lines), size)]


def split_zones(text: str) -> dict[str, str]:
    """Split a judgment into headnote, facts, arguments and holding via heuristics."""
    cleaned = clean_text(text)
    start = body_start(cleaned)
    explicit = extract_headnote(cleaned[: max(start, 1)] if start else cleaned)
    headnote = explicit or cleaned[:start][:HEADNOTE_CAP]
    body = cleaned[start:]
    paragraphs = extract_numbered_paragraphs(body)
    numbered = len(paragraphs) >= 6 and paragraphs[0][0] <= 3 and paragraphs[-1][0] >= len(paragraphs) // 2
    items = [p for _, p in paragraphs] if numbered else _blocks(body)
    if not items:
        return {"headnote": headnote, "facts": "", "arguments": "", "holding": ""}

    total = len(items)
    facts: list[str] = []
    args: list[str] = []
    holding: list[str] = []
    zone = "facts"
    for idx, item in enumerate(items):
        pos = idx / total
        if RE_HOLDING_HEADING.search(item) and pos >= 0.50:
            zone = "holding"
        elif RE_ARGS_HEADING.search(item) and 0.10 <= pos < 0.70 and zone != "holding":
            zone = "arguments"
        elif RE_FACTS_HEADING.search(item) and pos < 0.35 and zone == "facts":
            zone = "facts"
        else:  # positions decide where no heading does
            if pos < 0.30 and zone not in {"arguments", "holding"}:
                zone = "facts"
            elif 0.30 <= pos < 0.60 and zone == "facts":
                zone = "arguments"
            elif pos >= 0.75:
                zone = "holding"
        (facts if zone == "facts" else args if zone == "arguments" else holding).append(item)

    holding_text = "\n\n".join(holding)
    result = extract_result(cleaned)
    if result and result not in holding_text:
        holding_text = (holding_text + f"\n\nResult of the case: {result}").strip()
    return {"headnote": headnote, "facts": "\n\n".join(facts), "arguments": "\n\n".join(args), "holding": holding_text}
