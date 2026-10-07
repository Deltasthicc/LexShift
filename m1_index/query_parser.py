"""Boolean, proximity, and phrase query AST parser.

Supports:
  - Boolean: AND, OR, NOT
  - Proximity: /s (same sentence), /p (same paragraph), /k (within k tokens)
  - Phrases: "common intention"

Precedence, tightest first: proximity, NOT, AND, OR (parentheses override). Every malformed query raises ValueError and nothing
else; the engine then treats the text as a bag of words.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from m1_index.tokenizer import tokenize


@dataclass
class TermNode:
    term: str


@dataclass
class PhraseNode:
    terms: list[str]


@dataclass
class ProximityNode:
    left: object
    operator: str
    right: object


@dataclass
class BooleanNode:
    operator: str
    left: object
    right: object


@dataclass
class NotNode:
    child: object


RE_QUERY_TOKEN = re.compile(
    r'"[^"]*"|/\w+|\(|\)|\bAND\b|\bOR\b|\bNOT\b|[^\s()]+',
    re.IGNORECASE,
)


def tokenize_query(query: str) -> list[str]:
    return RE_QUERY_TOKEN.findall(query)


def normalize_term(term: str) -> str:
    tokens = tokenize(term)
    if not tokens:
        # Fallback to lower stripped term to prevent dropping essential search tokens
        clean = re.sub(r"[^\w-]", "", term.lower())
        if not clean:
            raise ValueError(f"Empty or invalid query term: {term!r}")
        return clean
    return tokens[0]


def parse_atom(tokens: list[str], position: int):
    if position >= len(tokens):
        raise ValueError("Unexpected end of query while expecting a term, phrase, or '('")

    token = tokens[position]

    if token.upper() in {"AND", "OR"}:
        raise ValueError(f"Unexpected Boolean operator {token!r} at position {position}")

    if token.startswith("/") and len(token) > 1:
        raise ValueError(f"Unexpected proximity operator {token!r} at position {position}")

    # Quoted phrase
    if token.startswith('"') and token.endswith('"'):
        phrase_text = token[1:-1].strip()
        if not phrase_text:
            raise ValueError("Empty phrase")
        terms = tokenize(phrase_text)
        if not terms:
            terms = [t.lower() for t in phrase_text.split() if t]
        if not terms:
            raise ValueError(f"Phrase contains no indexable terms: {token}")
        return PhraseNode(terms), position + 1

    # Parenthesized group
    if token == "(":
        node, position = parse_or(tokens, position + 1)
        if position >= len(tokens) or tokens[position] != ")":
            raise ValueError("Missing closing parenthesis ')'")
        return node, position + 1

    if token == ")":
        raise ValueError("Unexpected closing parenthesis ')' without matching '('")

    # Ordinary term
    norm = normalize_term(token)
    return TermNode(norm), position + 1


def parse_proximity(tokens: list[str], position: int):
    node, position = parse_atom(tokens, position)

    while position < len(tokens):
        token = tokens[position].lower()
        if token not in {"/s", "/p"} and not re.fullmatch(r"/\d+", token):
            break

        operator = token
        if position + 1 >= len(tokens):
            raise ValueError(f"Proximity operator {operator!r} missing right-hand operand")

        right, position = parse_atom(tokens, position + 1)
        node = ProximityNode(left=node, operator=operator, right=right)

    return node, position


def parse_not(tokens: list[str], position: int):
    if position < len(tokens) and tokens[position].upper() == "NOT":
        if position + 1 >= len(tokens):
            raise ValueError("NOT operator missing target expression")
        child, position = parse_not(tokens, position + 1)
        return NotNode(child), position

    return parse_proximity(tokens, position)


def parse_and(tokens: list[str], position: int):
    node, position = parse_not(tokens, position)

    while position < len(tokens) and tokens[position].upper() == "AND":
        if position + 1 >= len(tokens):
            raise ValueError("AND operator missing right-hand operand")
        right, position = parse_not(tokens, position + 1)
        node = BooleanNode(operator="AND", left=node, right=right)

    return node, position


def parse_or(tokens: list[str], position: int):
    node, position = parse_and(tokens, position)

    while position < len(tokens) and tokens[position].upper() == "OR":
        if position + 1 >= len(tokens):
            raise ValueError("OR operator missing right-hand operand")
        right, position = parse_and(tokens, position + 1)
        node = BooleanNode(operator="OR", left=node, right=right)

    return node, position


def parse_query(query: str):
    """Parse complete query string and return AST root."""
    if not query or not query.strip():
        raise ValueError("Empty query")

    tokens = tokenize_query(query.strip())
    if not tokens:
        raise ValueError("Empty query")

    try:
        node, position = parse_or(tokens, 0)
    except RecursionError as exc:  # hundreds of nested parentheses or NOTs: a malformed query like any other
        raise ValueError("Query is nested too deeply") from exc
    if position != len(tokens):
        raise ValueError(f"Unexpected token {tokens[position]!r} at position {position}")

    return node