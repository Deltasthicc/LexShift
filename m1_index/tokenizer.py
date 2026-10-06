"""Legal-aware text processing: case folding, stop words, Porter stemming; keep statute and citation tokens intact.

IR concepts: tokenisation, normalisation, case folding, stop words, stemming. Named `tokenizer` rather than
`tokenize` because a module called tokenize would shadow the standard library module of that name.

Statute and citation tokens (for example IPC_302, "u/s", "v.") must NOT be stemmed or split.
"""

from __future__ import annotations

from common.skeleton import not_implemented


def tokenize(text: str) -> list[str]:
    """Text -> index terms, in order (positions matter: the index is positional)."""
    not_implemented("M1", "tokenizer.tokenize()")


def normalize_term(token: str) -> str:
    """Case-fold and stem one token, leaving statute/citation tokens unstemmed."""
    not_implemented("M1", "tokenizer.normalize_term()")
