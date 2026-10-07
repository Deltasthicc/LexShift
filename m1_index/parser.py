import re
from dataclasses import dataclass
from m1_index.text_tokenizer import tokenize

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


def tokenize_query(query: str):
    """
    Break a query into:
    - quoted phrases
    - proximity operators
    - Boolean operators
    - ordinary terms
    """

    pattern = r'"[^"]+"|/\w+|\(|\)|\bAND\b|\bOR\b|\bNOT\b|[^\s()]+'

    return re.findall(pattern, query, flags=re.IGNORECASE)


def normalize_term(term: str) -> str:
    """
    Normalize a single query term using the same
    tokenizer used for the document corpus.
    """

    tokens = tokenize(term)

    if not tokens:
        return ""

    if len(tokens) != 1:
        raise ValueError(
            f"Expected one query term, got: {tokens}"
        )

    return tokens[0]


def parse_atom(tokens, position):
    """
    Parse a single term or quoted phrase.
    """

    token = tokens[position]

    # Quoted phrase
    if token.startswith('"') and token.endswith('"'):
        phrase_text = token[1:-1]

        terms = tokenize(phrase_text)

        if not terms:
            raise ValueError("Empty phrase")

        return PhraseNode(terms), position + 1

    # Parenthesized expression
    if token == "(":
        node, position = parse_or(tokens, position + 1)

        if position >= len(tokens) or tokens[position] != ")":
            raise ValueError("Missing closing parenthesis")

        return node, position + 1

    # Ordinary term
    return TermNode(normalize_term(token)), position + 1

def parse_proximity(tokens, position):
    """
    Parse:

        term /s term
        term /p term
        term /k term
        "phrase" /s term

    Proximity operators are left-associative.
    """

    node, position = parse_atom(tokens, position)

    while position < len(tokens):

        token = tokens[position].lower()

        if token not in {"/s", "/p"} and not re.fullmatch(
            r"/\d+",
            token
        ):
            break

        operator = token

        right, position = parse_atom(
            tokens,
            position + 1
        )

        node = ProximityNode(
            left=node,
            operator=operator,
            right=right,
        )

    return node, position


def parse_not(tokens, position):
    """
    NOT has higher precedence than AND/OR.
    """

    if (
        position < len(tokens)
        and tokens[position].upper() == "NOT"
    ):
        child, position = parse_not(
            tokens,
            position + 1
        )

        return NotNode(child), position

    return parse_proximity(tokens, position)


def parse_and(tokens, position):
    """
    Parse AND expressions.
    """

    node, position = parse_not(
        tokens,
        position
    )

    while (
        position < len(tokens)
        and tokens[position].upper() == "AND"
    ):

        right, position = parse_not(
            tokens,
            position + 1
        )

        node = BooleanNode(
            operator="AND",
            left=node,
            right=right,
        )

    return node, position


def parse_or(tokens, position):
    """
    Parse OR expressions.
    """

    node, position = parse_and(
        tokens,
        position
    )

    while (
        position < len(tokens)
        and tokens[position].upper() == "OR"
    ):

        right, position = parse_and(
            tokens,
            position + 1
        )

        node = BooleanNode(
            operator="OR",
            left=node,
            right=right,
        )

    return node, position


def parse_query(query: str):
    """
    Parse a complete query and return its AST.
    """

    tokens = tokenize_query(query)

    if not tokens:
        raise ValueError("Empty query")

    node, position = parse_or(
        tokens,
        0
    )

    if position != len(tokens):
        raise ValueError(
            f"Unexpected token: {tokens[position]}"
        )

    return node


def print_tree(node, indent=0):
    """
    Pretty-print the query AST for debugging/demo purposes.
    """

    prefix = "  " * indent

    if isinstance(node, TermNode):

        print(
            f"{prefix}TERM: {node.term}"
        )

    elif isinstance(node, PhraseNode):

        print(
            f"{prefix}PHRASE: {' '.join(node.terms)}"
        )

    elif isinstance(node, ProximityNode):

        print(
            f"{prefix}PROXIMITY: {node.operator}"
        )

        print_tree(
            node.left,
            indent + 1
        )

        print_tree(
            node.right,
            indent + 1
        )

    elif isinstance(node, BooleanNode):

        print(
            f"{prefix}BOOLEAN: {node.operator}"
        )

        print_tree(
            node.left,
            indent + 1
        )

        print_tree(
            node.right,
            indent + 1
        )

    elif isinstance(node, NotNode):

        print(
            f"{prefix}NOT"
        )

        print_tree(
            node.child,
            indent + 1
        )


if __name__ == "__main__":

    test_queries = [
        "ipc AND murder",
        "ipc AND NOT bns",
        '"common intention"',
        '"common intention" /s murder',
        "ipc OR bns AND murder",
    ]

    for query in test_queries:

        print()
        print("=" * 60)
        print("QUERY:", query)
        print("=" * 60)

        try:
            tree = parse_query(query)
            print_tree(tree)

        except ValueError as error:
            print("ERROR:", error)
