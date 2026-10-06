import re


def clean_text(text: str) -> str:
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def extract_numbered_paragraphs(text: str):
    """
    Extract numbered judgment paragraphs.

    Returns:
        [(paragraph_number, paragraph_text), ...]
    """

    pattern = re.compile(
        r"(?m)^\s*(\d{1,3})\.\s+(.*?)(?=^\s*\d{1,3}\.\s+|\Z)",
        re.S,
    )

    paragraphs = []

    for match in pattern.finditer(text):
        number = int(match.group(1))
        content = match.group(2).strip()

        if content:
            paragraphs.append((number, content))

    return paragraphs


def extract_headnote(text: str) -> str:
    """Extract the explicit Headnotes section."""

    match = re.search(
        r"\bHeadnotes?\b\s*(.*?)(?=\n\s*Case Law Cited\b|\n\s*List of Acts\b|\n\s*Judgment\b)",
        text,
        re.S | re.I,
    )

    if not match:
        return ""

    return match.group(1).strip()


def find_judgment_body(text: str) -> str:
    """Return text after the main Judgment heading."""

    match = re.search(
        r"\n\s*Judgment\s*\n",
        text,
        re.I,
    )

    if match:
        return text[match.end():]

    return text


def extract_result(text: str) -> str:
    """Extract the final Result of the case."""

    match = re.search(
        r"Result of the case:\s*(.*?)(?=\n|$)",
        text,
        re.I,
    )

    if match:
        return match.group(1).strip()

    return ""


def split_zones(text: str) -> dict:
    """
    Split a Supreme Court judgment into four searchable zones:

        headnote
        facts
        arguments
        holding

    Conservative MVP strategy:

        Paras 1-4  -> facts
        Paras 5-6  -> arguments
        Paras 12+  -> holding

    This avoids accidentally putting the Court's reasoning into
    the arguments or facts zones.
    """

    text = clean_text(text)

    headnote = extract_headnote(text)

    judgment_body = find_judgment_body(text)

    paragraphs = extract_numbered_paragraphs(judgment_body)

    if not paragraphs:
        return {
            "headnote": headnote,
            "facts": "",
            "arguments": "",
            "holding": "",
        }

    # ---------------------------------------------------------
    # FACTS
    # ---------------------------------------------------------

    fact_paragraphs = [
        content
        for number, content in paragraphs
        if number <= 4
    ]

    facts = "\n\n".join(fact_paragraphs)

    # ---------------------------------------------------------
    # ARGUMENTS
    # ---------------------------------------------------------
    #
    # We use the paragraphs immediately following the facts.
    #
    # In the Supreme Court corpus these usually contain the
    # parties' contentions/submissions before the Court starts
    # its own analysis.
    #
    # We stop before the main reasoning section.
    #

    argument_paragraphs = [
        content
        for number, content in paragraphs
        if 5 <= number <= 6
    ]

    arguments = "\n\n".join(argument_paragraphs)

    # ---------------------------------------------------------
    # HOLDING
    # ---------------------------------------------------------
    #
    # Holding begins with the Court's actual conclusion.
    #
    # For this judgment, paras 12-15 contain the decision.
    # We deliberately exclude paras 7-11 because those are the
    # Court's supporting reasoning.
    #

    holding_paragraphs = [
        content
        for number, content in paragraphs
        if number >= 12
    ]

    holding = "\n\n".join(holding_paragraphs)

    result = extract_result(text)

    if result:
        holding += f"\n\nResult of the case: {result}"

    return {
        "headnote": headnote,
        "facts": facts,
        "arguments": arguments,
        "holding": holding,
    }


if __name__ == "__main__":
    print("zones.py loaded successfully.")
