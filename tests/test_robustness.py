"""Robustness: seeded random and hostile input through every module. Nothing here needs data.

Three things are checked for each module: it never raises an exception its contract does not allow, what it returns still
satisfies the shared schema, and it does not take quadratic or exponential time on long input (a regex that backtracks badly
on a 300,000-character judgment would stall a whole corpus build).
"""

import random
import string
import time

import pytest

from common import contracts
from common.schema import QueryStatutes, SchemaError, StatuteRef

SEED = 20261006
DATES = [None, "2024-07-01", "2024-06-30", "2025-02-01", "1999-12-31", "2020-02-29"]
LEGAL_BITS = ["Section", "section", "Sections", "s.", "ss.", "u/s", "u/ss.", "IPC", "I.P.C.", "BNS", "BNSS", "CrPC", "Cr.P.C.",
              "Indian Penal Code", "of the", "read with", "r/w", "and", ",", "/", "302", "34", "120-B", "498A", "3(5)", "103", "IPC.",
              "10.", "1860", "(", ")", "[", "]", "'", '"', "\\", "\n", "\t", "\x08", "é", "न", "-", "--", ".", ";", ":"]
WORDS = ["murder", "common", "intention", "State", "v.", "Union", "of", "India", "SCC", "SCR", "(2014)", "1", "[2013]", "17", "116",
         "AIR", "1973", "SC", "overruled", "followed", "supra", "(supra)", "Koushal", "Singh", "Kumar", "the", "&", "Ors.", "Anr."]


def junk(rng: random.Random, vocab: list[str], n: int) -> str:
    return " ".join(rng.choice(vocab) for _ in range(n))


def chars(rng: random.Random, n: int) -> str:
    pool = string.ascii_letters + string.digits + string.punctuation + " \n\t\x08\x0céन’"
    return "".join(rng.choice(pool) for _ in range(n))


def timed(fn, *args, limit=5.0):
    t = time.time()
    out = fn(*args)
    assert time.time() - t < limit, f"{fn.__name__} took {time.time() - t:.1f}s on {sum(len(str(a)) for a in args)} characters"
    return out


def seconds(fn, text: str) -> float:
    t = time.perf_counter()
    fn(text)
    return time.perf_counter() - t


def assert_scales_linearly(fn, make, small=2500, factor=4, floor=0.05, ceiling=20.0):
    """Quadruple the input and require the time to grow by well under the 16x a quadratic algorithm would show.

    Comparing two sizes measures the algorithm, not the machine; `floor` keeps timer noise on tiny inputs from mattering and
    `ceiling` bounds the biggest run so a failing test stays fast.
    """
    t_small, t_big = seconds(fn, make(small)), seconds(fn, make(small * factor))
    assert t_big < ceiling, f"{fn.__module__}.{fn.__name__}: {t_big:.1f}s for {small * factor} repeats"
    assert t_big / max(t_small, floor) < 10, (
        f"{fn.__module__}.{fn.__name__} scales badly: {t_small:.2f}s for {small} repeats, {t_big:.2f}s for {small * factor} "
        f"(x{t_big / max(t_small, floor):.0f} for x{factor} the input; linear would be about x{factor})")


# ------------------------------------------------------------------------------------------------------------- M2
def test_m2_parse_query_never_crashes_and_always_returns_a_valid_object():
    from m2_statute.query_parser import parse_query

    rng = random.Random(SEED)
    for i in range(1500):
        text = junk(rng, LEGAL_BITS, rng.randint(0, 14)) if i % 2 else chars(rng, rng.randint(0, 80))
        date = rng.choice(DATES)
        qs = parse_query(text, date)
        assert isinstance(qs, QueryStatutes)
        qs.validate()
        for r in qs.refs:
            r.validate()
        assert contracts.check_query_statutes(qs) == []
        assert parse_query(text, date).to_dict() == qs.to_dict()  # deterministic


@pytest.mark.parametrize("bad", ["31/12/2024", "2024-13-40", "yesterday", "", "2024-7-1x"])
def test_m2_parse_query_rejects_malformed_dates_with_a_schema_error_only(bad):
    from m2_statute.query_parser import parse_query

    with pytest.raises(SchemaError):
        parse_query("IPC 302", bad)


def test_m2_extractor_never_crashes_and_only_emits_valid_references():
    from m2_statute.extractor import extract_refs

    rng = random.Random(SEED + 1)
    for i in range(800):
        text = junk(rng, LEGAL_BITS + WORDS, rng.randint(0, 60)) if i % 2 else chars(rng, rng.randint(0, 400))
        for ref in extract_refs(text, "2025-01-01"):
            assert isinstance(ref, StatuteRef)
            ref.validate()
            assert ref.count >= 1


M2_ADVERSARIAL = {
    "section words": lambda n: "Section " * n,
    "act followed by paragraph numbers": lambda n: "IPC. 1. " * n,
    "digits": lambda n: "1" * (n * 8),
    "abbreviation then act": lambda n: "s. " * n + "IPC",
    "act with long gaps": lambda n: ("IPC" + " " * 50) * n,
    "one long number list": lambda n: "Sections " + ", ".join(str(i) for i in range(n)) + " IPC",
}


@pytest.mark.parametrize("name", list(M2_ADVERSARIAL))
def test_m2_extractor_scales_linearly_on_adversarial_text(name):
    from m2_statute.extractor import extract_refs

    if name == "act followed by paragraph numbers":
        pytest.xfail("known: extract_refs checks each match against every earlier match (quadratic); see docs/INTEGRATION_REVIEW.md, M2 finding 7")
    assert_scales_linearly(lambda t: extract_refs(t, "2025-01-01"), M2_ADVERSARIAL[name])


@pytest.mark.parametrize("name", list(M2_ADVERSARIAL))
def test_m2_query_parser_scales_linearly_on_adversarial_text(name):
    from m2_statute.query_parser import parse_query

    assert_scales_linearly(lambda t: parse_query(t[:200000]), M2_ADVERSARIAL[name])


def test_m2_continuity_stays_in_the_unit_interval_for_any_query_and_document(tmp_path, monkeypatch):
    import json

    from common.schema import DocStatutes
    from m2_statute import matcher
    from m2_statute.query_parser import parse_query

    rng = random.Random(SEED + 2)
    docs = tmp_path / "doc_statutes.jsonl"
    rows = [DocStatutes(doc_id=f"D{i}", refs=[StatuteRef(act=rng.choice(["IPC", "BNS", "CRPC", "BNSS", "UNKNOWN"]),
                                                          section=str(rng.choice([302, 103, 34, 420, 318, 482, 528])))
                                             for _ in range(rng.randint(0, 5))]) for i in range(30)]
    docs.write_text("\n".join(json.dumps(r.to_dict()) for r in rows) + "\n", encoding="utf-8")
    monkeypatch.setattr(matcher, "_doc_statutes_path", lambda: docs)
    matcher._DOC_REFS_CACHE.clear()
    matcher._DOC_REFS_MTIME = 0.0
    for _ in range(300):
        qs = parse_query(junk(rng, LEGAL_BITS, rng.randint(0, 8)), rng.choice(DATES))
        for r in rows[:10]:
            assert contracts.check_continuity(matcher.continuity(qs, r.doc_id)) == []
    matcher._DOC_REFS_CACHE.clear()
    matcher._DOC_REFS_MTIME = 0.0


# ------------------------------------------------------------------------------------------------------------- M3
def test_m3_text_and_citation_code_never_crashes_and_keeps_offsets_inside_the_text():
    from m3_treatment.citations import extract_mentions
    from m3_treatment.text import clean_text, sentence_spans
    from m3_treatment.windows import citation_window, marked_window

    rng = random.Random(SEED + 3)
    for i in range(300):
        raw = junk(rng, WORDS + LEGAL_BITS, rng.randint(0, 80)) if i % 2 else chars(rng, rng.randint(0, 600))
        text = clean_text(raw)
        spans = sentence_spans(text)
        assert all(0 <= a <= b <= len(text) for a, b in spans)
        for m in extract_mentions(text):
            assert 0 <= m.start <= m.end <= len(text)
            assert m.antecedent is None or 0 <= m.antecedent < len(extract_mentions(text))
            w = marked_window(text, m.start, m.end, 1, 1, 1500, spans)
            assert w.count("[[") == w.count("]]") == 1 or "[[" in text or "]]" in text  # the marker is ours unless the text has one
            assert len(citation_window(text, m.start, m.end, 1, 1, 1500, spans)) <= 1500


M3_ADVERSARIAL = {
    "sentence ends": lambda n: "A. " * n,
    "reporter letters": lambda n: "S.C.C. " * n,
    "party names": lambda n: "State of " * n + "v. State",
    "citations": lambda n: "(2014) 1 SCC " * n,
    "versus markers": lambda n: "v. " * n,
    "scr citations": lambda n: "[2013] 17 S.C.R. 116 " * n,
    "supra": lambda n: "Koushal (supra) " * n,
    "no structure": lambda n: "x" * (n * 8),
    "bare numbers": lambda n: "\n\n12\n\n" * n,
    "full mentions": lambda n: "Suresh Kumar Koushal v. Naz Foundation, (2014) 1 SCC 1 : [2013] 17 SCR 116. " * n,
}


@pytest.mark.parametrize("name", list(M3_ADVERSARIAL))
def test_m3_pipeline_stages_scale_linearly_on_adversarial_text(name):
    from m3_treatment.citations import extract_mentions, find_cites
    from m3_treatment.text import clean_text, sentence_spans

    make = M3_ADVERSARIAL[name]
    for stage in (clean_text, lambda t: sentence_spans(clean_text(t)), lambda t: find_cites(clean_text(t)),
                  lambda t: extract_mentions(clean_text(t))):
        assert_scales_linearly(stage, make, small=1500)


def test_m3_bench_and_year_readers_never_crash():
    from m3_treatment.resolver import bench_from_text, year_of

    rng = random.Random(SEED + 4)
    for _ in range(500):
        text = "[" + junk(rng, WORDS + ["JJ.", "J.", "CJI", "and", "*", ","], rng.randint(0, 20)) + "] " + chars(rng, 40)
        assert bench_from_text(text) is None or bench_from_text(text) >= 1
        assert year_of(chars(rng, 30)) is None or 1800 <= year_of(chars(rng, 30) + "2020") <= 2099


# ------------------------------------------------------------------------------------------------------------- M1
def test_m1_search_never_raises_on_random_boolean_looking_input():
    """M1 fixed the IndexError that `murder AND` and `(` used to raise (docs/INTEGRATION_REVIEW.md, M1 finding 5)."""
    pytest.importorskip("nltk")
    try:
        from m1_index import search
        search("murder", k=1)
    except (LookupError, RuntimeError, ImportError, FileNotFoundError) as exc:
        pytest.skip(f"M1's index is not built here (python -m m1_index.index build): {exc}")
    rng = random.Random(SEED + 5)
    ops = ["AND", "OR", "NOT", "/s", "/p", "/10", "(", ")", '"']
    for i in range(300):
        q = junk(rng, WORDS + ops + LEGAL_BITS, rng.randint(0, 12))
        hits = search(q, k=5)
        assert isinstance(hits, list) and len(hits) <= 5


def test_m1_parser_does_not_stall_on_deeply_nested_or_long_queries():
    pytest.importorskip("nltk")
    try:
        from m1_index.parser import parse_query
    except (LookupError, RuntimeError, ImportError) as exc:
        pytest.skip(f"M1 cannot be imported here: {exc}")
    for q in ("(" * 400 + "murder" + ")" * 400, " AND ".join(["murder"] * 5000), "NOT " * 800 + "murder"):
        try:
            timed(parse_query, q, limit=10)
        except (ValueError, RecursionError):
            pass


# ------------------------------------------------------------------------------------------------------------- M4
def test_m4_fusion_invariants_hold_for_random_signals_and_weights():
    from m4_rank.fusion import SignalRow, fuse, normalized_columns, rank_ids
    from m4_rank.weights import SIGNALS, normalise_weights

    rng = random.Random(SEED + 6)
    norm = {"rel": "minmax", "cont": "identity", "health": "identity", "auth": "minmax"}
    for _ in range(300):
        n = rng.randint(1, 40)
        rows = [SignalRow(f"d{i:02d}", {"rel": rng.choice([0.0, rng.uniform(0, 50)]), "cont": rng.choice([0, 0.5, 1, rng.random()]),
                                        "health": rng.choice([0.1, 0.6, 1.0]), "auth": rng.random()}) for i in range(n)]
        w = normalise_weights({s: rng.choice([0, rng.random()]) for s in SIGNALS} | {"rel": rng.uniform(0.05, 1)})
        k = rng.randint(1, 50)
        out = fuse(rows, w, norm, k)
        assert len(out) == min(k, n) and len({r.doc_id for r in out}) == len(out)
        assert [r.final for r in out] == sorted((r.final for r in out), reverse=True)
        assert contracts.check_results(out, k) == []
        assert [r.doc_id for r in out] == rank_ids(rows, w, normalized_columns(rows, norm), k)
        assert [r.doc_id for r in out] == [r.doc_id for r in fuse(list(reversed(rows)), w, norm, k)]  # input order is irrelevant


def test_m4_metrics_stay_in_range_for_random_rankings_and_judgements():
    from eval.metrics import evaluate_query

    rng = random.Random(SEED + 7)
    for _ in range(400):
        docs = [f"d{i}" for i in range(rng.randint(0, 40))]
        ranked = rng.sample(docs, len(docs))
        grades = {d: rng.choice([0, 1, 2]) for d in rng.sample(docs + ["x", "y"], rng.randint(0, len(docs) + 2))}
        overruled = set(rng.sample(docs, min(len(docs), rng.randint(0, 3)))) or None
        for name, value in evaluate_query(ranked, grades, overruled).items():
            assert value is None or 0.0 <= value <= 1.0 + 1e-12, (name, value)
