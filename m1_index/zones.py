"""Zone extraction for Supreme Court judgments using heading and positional heuristics.

Searchable zones (common.schema.ZONES):
  - headnote
  - facts
  - arguments
  - holding
"""

from __future__ import annotations

import re


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


def find_judgment_body(text: str) -> str:
    """Return text starting after the header/metadata and judgment declaration."""
    match = re.search(r"\n\s*(?:JUDGMENT|ORDER)\s*\n", text, re.IGNORECASE)
    if match:
        return text[match.end():]
    return text


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
    r"\b(?:held|conclusion|finding|in\s+view\s+of\s+the\s+above|for\s+the\s+(?:foregoing\s+)?reasons|resultantly|we\s+hold|we\s+are\s+of\s+the\s+(?:considered\s+)?view|accordingly,\s+the\s+appeal|appeal\s+is\s+(?:allowed|dismissed))\b",
    re.IGNORECASE,
)


def split_zones(text: str) -> dict[str, str]:
    """Split judgment into headnote, facts, arguments, and holding via heuristics."""
    cleaned = clean_text(text)
    headnote = extract_headnote(cleaned)
    body = find_judgment_body(cleaned)
    paragraphs = extract_numbered_paragraphs(body)

    if not paragraphs:
        # Fallback for unnumbered text: chunk text into approximate thirds
        lines = [line.strip() for line in body.split("\n") if line.strip()]
        total_lines = len(lines)
        if total_lines == 0:
            return {"headnote": headnote, "facts": "", "arguments": "", "holding": ""}
        p1 = total_lines // 3
        p2 = (2 * total_lines) // 3
        return {
            "headnote": headnote,
            "facts": "\n".join(lines[:p1]),
            "arguments": "\n".join(lines[p1:p2]),
            "holding": "\n".join(lines[p2:]),
        }

    total_p = len(paragraphs)
    facts_p: list[str] = []
    args_p: list[str] = []
    holding_p: list[str] = []

    # State machine based on paragraph content, bounded by relative position
    current_zone = "facts"

    for idx, (p_num, p_text) in enumerate(paragraphs):
        pos_fraction = idx / total_p

        # 1. Heading check
        if RE_HOLDING_HEADING.search(p_text) and pos_fraction >= 0.40:
            current_zone = "holding"
        elif RE_ARGS_HEADING.search(p_text) and 0.10 <= pos_fraction < 0.75:
            if current_zone != "holding":
                current_zone = "arguments"
        elif RE_FACTS_HEADING.search(p_text) and pos_fraction < 0.35:
            current_zone = "facts"
        else:
            # 2. Positional defaults if no explicit heading matches
            if pos_fraction < 0.30 and current_zone not in {"arguments", "holding"}:
                current_zone = "facts"
            elif 0.30 <= pos_fraction < 0.65 and current_zone == "facts":
                current_zone = "arguments"
            elif pos_fraction >= 0.75:
                current_zone = "holding"

        if current_zone == "facts":
            facts_p.append(p_text)
        elif current_zone == "arguments":
            args_p.append(p_text)
        else:
            holding_p.append(p_text)

    # Ensure holding has final result
    holding_text = "\n\n".join(holding_p)
    result = extract_result(cleaned)
    if result and result not in holding_text:
        holding_text = (holding_text + f"\n\nResult of the case: {result}").strip()

    return {
        "headnote": headnote,
        "facts": "\n\n".join(facts_p),
        "arguments": "\n\n".join(args_p),
        "holding": holding_text,
    }