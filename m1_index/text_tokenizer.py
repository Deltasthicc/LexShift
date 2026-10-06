import re

from nltk.corpus import stopwords
from nltk.stem import PorterStemmer


# =========================================================
# Resources
# =========================================================

try:
    STOPWORDS = set(stopwords.words("english"))
except LookupError as exc:
    raise RuntimeError(
        "The NLTK stopwords corpus is not installed. Run once (needs the network): python -m nltk.downloader stopwords"
    ) from exc
STEMMER = PorterStemmer()


# =========================================================
# Legal / citation token detection
# =========================================================

LEGAL_ABBREVIATIONS = {
    "ipc",
    "bns",
    "crpc",
    "bnss",
    "cpc",
    "fir",
    "scc",
    "scr",
    "insc",
    "sc",
    "jj",
}


def is_legal_token(token: str) -> bool:
    """
    Return True when a token should be preserved rather than
    Porter-stemmed.

    Examples:
        ipc
        bns
        crpc
        bnss
        120-b
        498-a
        226
        2025
        insc
        scr
    """

    token = token.lower()

    # Known legal abbreviations
    if token in LEGAL_ABBREVIATIONS:
        return True

    # Pure numbers
    if re.fullmatch(r"\d+", token):
        return True

    # Legal section formats:
    # 120-b
    # 498-a
    # 302-a
    if re.fullmatch(r"\d+[a-z]?(?:-\d+)?[a-z]?", token):
        return True

    # Citation identifiers such as:
    # 2025insc
    # 2025scc
    # 2025scr
    if re.fullmatch(r"\d{4}[a-z]+", token):
        return True

    return False


# =========================================================
# Citation normalization
# =========================================================

def normalize_citations(text: str) -> str:
    """
    Preserve useful legal citation structures before ordinary
    tokenization.

    Examples:

        [2025] 1 S.C.R. 1 : 2025 INSC 8

    becomes conceptually:

        2025 scr 1 2025 insc 8
    """

    # Remove square brackets around years
    text = re.sub(r"\[(\d{4})\]", r"\1", text)

    # Normalize common reporter abbreviations
    text = re.sub(r"\bS\.C\.R\.", "SCR", text, flags=re.I)
    text = re.sub(r"\bS\.C\.C\.", "SCC", text, flags=re.I)

    # Normalize INSC
    text = re.sub(r"\bI\.N\.S\.C\.", "INSC", text, flags=re.I)

    # Normalize "Cr. P.C." / "Cr.P.C."
    text = re.sub(r"\bCr\.\s*P\.?\s*C\.", "CrPC", text, flags=re.I)

    return text


# =========================================================
# Main tokenizer
# =========================================================

def tokenize(text: str) -> list[str]:
    """
    Legal-aware IR tokenizer.

    Pipeline:

        1. Normalize legal citations
        2. Case folding
        3. Tokenization
        4. Stopword removal
        5. Porter stemming

    Legal/statutory/citation tokens are protected from stemming.
    """

    if not text:
        return []

    # -----------------------------------------------------
    # 1. Preserve legal citation structures
    # -----------------------------------------------------

    text = normalize_citations(text)

    # -----------------------------------------------------
    # 2. Case folding
    # -----------------------------------------------------

    text = text.lower()

    # -----------------------------------------------------
    # 3. Tokenization
    # -----------------------------------------------------
    #
    # Supports:
    #
    #   ordinary words
    #   numbers
    #   120-b
    #   498-a
    #   2025insc
    #   appellant-foreign
    #
    raw_tokens = re.findall(
        r"[a-z]+(?:-[a-z0-9]+)*|\d+[a-z]*(?:-[a-z0-9]+)*",
        text,
    )

    tokens = []

    # -----------------------------------------------------
    # 4. Stopword removal
    # 5. Stemming
    # -----------------------------------------------------

    for token in raw_tokens:

        # Do not remove legal/citation tokens even if they happen
        # to resemble ordinary words.
        if is_legal_token(token):
            tokens.append(token)
            continue

        # Ordinary stopword removal
        if token in STOPWORDS:
            continue

        # Porter stemming
        tokens.append(STEMMER.stem(token))

    return tokens


# =========================================================
# Zone tokenizer
# =========================================================

def tokenize_zones(zones: dict) -> dict:
    """
    Tokenize each zone independently.

    Input:
        {
            "headnote": "...",
            "facts": "...",
            "arguments": "...",
            "holding": "..."
        }

    Output:
        {
            "headnote": [...],
            "facts": [...],
            "arguments": [...],
            "holding": [...]
        }
    """

    return {
        zone: tokenize(text)
        for zone, text in zones.items()
    }


# =========================================================
# Test
# =========================================================

if __name__ == "__main__":

    sample = """
    [2025] 1 S.C.R. 1 : 2025 INSC 8

    The appellant was charged under Sections 302 and 120-B
    of the IPC.

    The Supreme Court considered Section 482 Cr.P.C.
    and Article 226 of the Constitution.
    """

    print("Input:")
    print(sample)

    print("\nTokens:")
    print(tokenize(sample))
