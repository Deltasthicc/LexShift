"""M1's query parser: precedence, phrases, proximity, parentheses, and the rule that a malformed query raises ValueError and nothing else.

Precedence, tightest first: proximity, NOT, AND, OR. Chains of one operator associate to the left.
"""

from __future__ import annotations

import random

import pytest

pytest.importorskip("nltk")
try:
    from m1_index.query_parser import BooleanNode, NotNode, PhraseNode, ProximityNode, TermNode, normalize_term, parse_query, tokenize_query
except (LookupError, RuntimeError, ImportError) as exc:  # NLTK stop words missing, for example
    pytest.skip(f"M1 cannot be imported here: {exc}", allow_module_level=True)


def T(term):
    return TermNode(term)


def AND(left, right):
    return BooleanNode("AND", left, right)


def OR(left, right):
    return BooleanNode("OR", left, right)


@pytest.mark.parametrize("query,tree", [
    ("a", T("a")),
    ("murder AND intention", AND(T("murder"), T("intent"))),
    ("a OR b AND c", OR(T("a"), AND(T("b"), T("c")))),                       # AND binds tighter than OR
    ("a AND b OR c AND d", OR(AND(T("a"), T("b")), AND(T("c"), T("d")))),
    ("NOT a AND b", AND(NotNode(T("a")), T("b"))),                              # NOT binds tighter than AND
    ("a AND NOT b OR c", OR(AND(T("a"), NotNode(T("b"))), T("c"))),
    ("NOT NOT a", NotNode(NotNode(T("a")))),
    ("a AND b AND c", AND(AND(T("a"), T("b")), T("c"))),                       # left associative
    ("a OR b OR c", OR(OR(T("a"), T("b")), T("c"))),
    ("(a OR b) AND c", AND(OR(T("a"), T("b")), T("c"))),                       # parentheses override
    ("a AND (b OR c)", AND(T("a"), OR(T("b"), T("c")))),
    ("(((a)))", T("a")),
    ("a /5 b AND c", AND(ProximityNode(T("a"), "/5", T("b")), T("c"))),        # proximity binds tightest
    ("NOT a /5 b", NotNode(ProximityNode(T("a"), "/5", T("b")))),
    ("a /s b /p c", ProximityNode(ProximityNode(T("a"), "/s", T("b")), "/p", T("c"))),
    ("a /S b", ProximityNode(T("a"), "/s", T("b"))),                           # operators are case-insensitive
    ("a and b", AND(T("a"), T("b"))),
    ("a Or b", OR(T("a"), T("b"))),
    ("(a OR b) /3 c", ProximityNode(OR(T("a"), T("b")), "/3", T("c"))),
])
def test_precedence_and_associativity(query, tree):
    assert parse_query(query) == tree


def test_a_quoted_phrase_is_tokenised_like_the_index_text():
    assert parse_query('"common intention"') == PhraseNode(["common", "intent"])          # Porter stem
    assert parse_query('"the benefit of doubt"') == PhraseNode(["benefit", "doubt"])      # stop words dropped, as in the indexed text
    assert parse_query('"Section 302 IPC"') == PhraseNode(["section", "302", "ipc"])
    assert parse_query('"common intention" /s murder') == ProximityNode(PhraseNode(["common", "intent"]), "/s", T("murder"))
    assert parse_query('"alpha beta" AND "gamma delta"') == AND(PhraseNode(["alpha", "beta"]), PhraseNode(["gamma", "delta"]))
    assert parse_query('"the"') == PhraseNode(["the"])  # nothing indexable survives: the lower-cased words are kept (and match nothing)


def test_terms_are_normalised_like_the_index_text():
    assert parse_query("Murdered") == T("murder")
    assert parse_query("120-B") == T("120-b")
    assert normalize_term("MURDERS") == "murder"
    assert normalize_term("the") == "the"  # a stop word alone is kept as written, it simply matches nothing


def test_the_proximity_operators():
    for op in ("/s", "/p", "/1", "/10", "/0", "/123"):
        assert parse_query(f"a {op} b") == ProximityNode(T("a"), op, T("b"))


def test_the_query_tokeniser_keeps_phrases_whole_and_splits_operators():
    assert tokenize_query('"common intention" /s murder AND (a OR b)') == ['"common intention"', "/s", "murder", "AND", "(", "a", "OR", "b", ")"]
    assert tokenize_query("android orange notice") == ["android", "orange", "notice"]  # operator words only count as whole words


MALFORMED = [
    "", "   ", "\t\n", "AND", "OR", "and", "NOT", "murder AND", "AND murder", "murder OR", "OR murder", "murder AND AND bail", "murder OR OR bail",
    "(", ")", "()", "(murder", "murder)", "((murder)", "(murder))", "NOT )", "NOT (", "a AND (b OR", "a (b)", "(a)(b)", "a b", "a b c",
    '""', '" "', '"a" "b"', "murder /s", "/5 murder", "/s", "murder /s /p intention", "murder /", "murder / intention", "/", "u/s 120-B",
    "section 302 ipc",
]


@pytest.mark.parametrize("query", MALFORMED)
def test_a_malformed_query_raises_value_error(query):
    with pytest.raises(ValueError):
        parse_query(query)


def test_none_and_non_text_are_rejected_without_a_surprising_exception():
    for value in (None, "", 0):
        with pytest.raises(ValueError):
            parse_query(value)


def test_deeply_nested_queries_are_a_value_error_not_a_recursion_error():
    for query in ("(" * 400 + "murder" + ")" * 400, "NOT " * 3000 + "murder", "(" * 5000):
        with pytest.raises(ValueError):
            parse_query(query)
    parse_query(" AND ".join(["murder"] * 5000))  # a long chain is fine: chains are parsed in a loop


def test_random_token_soup_is_either_a_tree_or_a_value_error():
    """Whatever the input, the parser raises ValueError or returns a tree: never IndexError, RecursionError, TypeError, ..."""
    rng = random.Random(11)
    pieces = ["murder", "bail", "intention", "AND", "OR", "NOT", "and", "or", "not", "(", ")", '"', '"common intention"', "/s", "/p", "/3", "/", "//",
              "120-B", "302", "the", "of", "u/s", "O'Brien", "a.b", "été", "٣", "/٣", "/²", "*", "?", "-", "_", "\x00", "‮", "\U0001f600"]
    trees = errors = 0
    for _ in range(4000):
        n = rng.randint(0, 12)
        query = rng.choice([" ", "", "  "]).join(rng.choice(pieces) for _ in range(n)) if rng.random() < 0.5 else " ".join(rng.choice(pieces) for _ in range(n))
        try:
            tree = parse_query(query)
        except ValueError:
            errors += 1
        else:
            trees += 1
            assert isinstance(tree, (TermNode, PhraseNode, ProximityNode, BooleanNode, NotNode))
    assert trees > 100 and errors > 100  # the soup is varied enough to hit both outcomes


def test_random_characters_never_break_the_parser():
    rng = random.Random(12)
    alphabet = list("abcAND OR NOT()\"/ 0123456789-'.,;:!?\t\n") + ["é", "٣", "²", "中", "\x00", "\x7f"]
    for _ in range(3000):
        query = "".join(rng.choice(alphabet) for _ in range(rng.randint(0, 30)))
        try:
            parse_query(query)
        except ValueError:
            pass


def test_parsing_is_deterministic():
    for query in ("a OR b AND NOT c /5 d", '"x y" /s (a OR b)'):
        assert parse_query(query) == parse_query(query)
