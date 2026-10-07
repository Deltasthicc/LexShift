"""M1's tokenizer: what the index and the query parser rely on. Legal tokens survive, stop words go, ordinary words are Porter-stemmed,
citations are normalised, the same text always gives the same tokens."""

from __future__ import annotations

import random

import pytest

pytest.importorskip("nltk")
try:
    from m1_index import tokenizer as T
    from m1_index.tokenizer import is_legal_token, normalize_citations, tokenize, tokenize_zones
except (LookupError, RuntimeError, ImportError) as exc:  # NLTK stop words missing, for example
    pytest.skip(f"M1 cannot be imported here: {exc}", allow_module_level=True)


@pytest.mark.parametrize("text,tokens", [
    ("Sections 302 and 120-B of the IPC", ["section", "302", "120-b", "ipc"]),  # section numbers and abbreviations are kept, "and"/"of"/"the" go
    ("498-A IPC", ["498-a", "ipc"]),
    ("Article 226 of the Constitution", ["articl", "226", "constitut"]),
    ("section 3(5) BNS", ["section", "3", "5", "bns"]),
    ("u/s 34 IPC", ["u", "34", "ipc"]),
    ("appellant-foreign", ["appellant-foreign"]),  # a hyphenated word stays one token
    ("12th 3rd 1950s", ["12th", "3rd", "1950s"]),
])
def test_legal_tokens_and_numbers_are_kept(text, tokens):
    assert tokenize(text) == tokens


@pytest.mark.parametrize("text,tokens", [
    ("[2025] 1 S.C.R. 1 : 2025 INSC 8", ["2025", "1", "scr", "1", "2025", "insc", "8"]),  # brackets dropped, reporter abbreviations normalised
    ("(2019) 5 S.C.C. 1", ["2019", "5", "scc", "1"]),
    ("Cr.P.C. section 482; Cr. P. C. 438", ["crpc", "section", "482", "crpc", "438"]),
    ("2025INSC8 x", ["2025insc", "8", "x"]),
])
def test_citations_are_normalised_before_tokenising(text, tokens):
    assert tokenize(text) == tokens


def test_normalize_citations_rewrites_reporters_and_brackets():
    assert normalize_citations("[2025] 1 S.C.R. 1 : 2025 I.N.S.C. 8 and S.C.C. Cr.P.C.") == "2025 1 SCR 1 : 2025 INSC 8 and SCC CrPC"
    assert normalize_citations("no citation here") == "no citation here"


def test_stop_words_are_removed_and_the_rest_is_stemmed():
    assert tokenize("the accused was not guilty") == ["accus", "guilti"]
    assert tokenize("MURDER Murder murdering murdered") == ["murder"] * 4  # case folding, then Porter
    assert all(w in T.STOPWORDS for w in ("the", "and", "of", "not"))
    assert tokenize("the and of a an is was") == []


def test_legal_abbreviations_are_protected_even_when_they_look_like_words():
    assert tokenize("sc jj ipc bns crpc bnss fir") == ["sc", "jj", "ipc", "bns", "crpc", "bnss", "fir"]
    for token in ("ipc", "IPC", "302", "2025", "2025insc", "12th"):
        assert is_legal_token(token)
    for token in ("murder", "a1", "x-1"):
        assert not is_legal_token(token)


@pytest.mark.parametrize("text", ["", "   ", "!!! ??? ...", "\n\t"])
def test_text_without_words_gives_no_tokens(text):
    assert tokenize(text) == []


def test_none_gives_no_tokens():
    assert tokenize(None) == []


def test_punctuation_separates_tokens_and_underscores_split_words():
    assert tokenize("hello_world, e-mail; well-known.") == ["hello", "world", "e-mail", "well-known"]
    assert tokenize("Rs. 10,000/-") == ["rs", "10", "000"]


def test_tokenize_zones_tokenizes_each_zone_alone():
    assert tokenize_zones({"headnote": "murder", "facts": ""}) == {"headnote": ["murder"], "facts": []}
    zones = {"holding": "Sections 302 and 34", "arguments": "bail granted"}
    assert tokenize_zones(zones) == {z: tokenize(t) for z, t in zones.items()}


def test_tokenize_is_deterministic_and_pure():
    rng = random.Random(5)
    words = ["Section", "302", "IPC", "murdered", "the", "120-B", "S.C.R.", "[2025]", "Cr.P.C.", "and", "bail", "granted", "1950s"]
    for _ in range(100):
        text = " ".join(rng.choice(words) for _ in range(rng.randint(0, 15)))
        assert tokenize(text) == tokenize(text)
        assert all(isinstance(t, str) and t and t == t.lower() for t in tokenize(text))


def test_every_token_is_lowercase_ascii_word_material():
    rng = random.Random(6)
    alphabet = "abcXYZ 0123456789-_.,;:()[]/'\"\t\n&%$#@!?*+=<>~é٣"
    for _ in range(300):
        text = "".join(rng.choice(alphabet) for _ in range(rng.randint(0, 40)))
        for token in tokenize(text):
            assert token and token == token.lower() and " " not in token
