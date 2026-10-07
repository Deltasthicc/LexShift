"""The compact index and the optimised engine against an independent reference, on random corpora and random queries.

The reference (RefIndex and the ref_* functions below) is the dict-of-dicts index and the left-to-right engine that M1 used before the
index was made compact, written out again here in plain Python so that nothing it does depends on the code under test except the
query parser (which has its own tests). Corpora are given as token lists, so the tokenizer is not involved either.

The other M1 test files import the generators from this module.
"""

from __future__ import annotations

import heapq
import math
import random

import pytest

pytest.importorskip("nltk")
try:
    from m1_index.index import IndexBuilder, InvertedIndex
    from m1_index.query_parser import BooleanNode, NotNode, PhraseNode, ProximityNode, TermNode, parse_query
    from m1_index.searcher import RankedSearchEngine
except (LookupError, RuntimeError, ImportError) as exc:  # NLTK stop words missing, for example
    pytest.skip(f"M1 cannot be imported here: {exc}", allow_module_level=True)

from common.schema import ZONES

ZONE_WEIGHTS = {"headnote": 3.0, "holding": 2.5, "facts": 1.0, "arguments": 0.75}
K1, B = 1.2, 0.75
# Words the tokenizer leaves unchanged (not stop words, not changed by the Porter stemmer): query text and index terms coincide.
VOCAB = "alpha beta gamma delta omega sigma kappa lambda theta zeta epsilon iota rho tau phi chi psi eta mu nu".split()


# ------------------------------------------------------------------------------------------------------ the reference
class RefIndex:
    """The former index: postings[term][doc_id] = {"positions": [...], "zones": {zone: tf}, "tf": n}."""

    def __init__(self, docs):
        self.postings: dict[str, dict[str, dict]] = {}
        self.doc_meta: dict[str, dict] = {}
        self.doc_lengths: dict[str, dict[str, int]] = {}
        for doc_id, (meta, zones) in docs.items():
            self.doc_meta[doc_id] = dict(meta)
            self.doc_lengths[doc_id] = {}
            for zone, tokens in zones.items():
                self.doc_lengths[doc_id][zone] = len(tokens)
                for pos, token in enumerate(tokens):
                    entry = self.postings.setdefault(token, {}).setdefault(doc_id, {"positions": [], "zones": {}, "tf": 0})
                    entry["positions"].append(pos)
                    entry["zones"][zone] = entry["zones"].get(zone, 0) + 1
                    entry["tf"] += 1


class RefEngine:
    def __init__(self, index: RefIndex):
        self.ix = index
        self.all_docs = set(index.doc_meta)
        self.avg = {}
        for z in ZONES:
            lens = [index.doc_lengths[d].get(z, 0) for d in index.doc_meta]
            self.avg[z] = sum(lens) / len(lens) if lens else 1.0

    def positions(self, term, doc):
        return self.ix.postings.get(term, {}).get(doc, {}).get("positions", [])

    def terms_of(self, node):
        if isinstance(node, TermNode):
            return [node.term]
        if isinstance(node, PhraseNode):
            return list(node.terms)
        if isinstance(node, (BooleanNode, ProximityNode)):
            return self.terms_of(node.left) + self.terms_of(node.right)
        if isinstance(node, NotNode):
            return self.terms_of(node.child)
        return []

    def phrase_in(self, terms, doc):
        for start in self.positions(terms[0], doc):
            if all((start + off) in set(self.positions(t, doc)) for off, t in enumerate(terms[1:], start=1)):
                return True
        return False

    def eval(self, node):
        if isinstance(node, TermNode):
            return set(self.ix.postings.get(node.term, {}))
        if isinstance(node, PhraseNode):
            if not node.terms:
                return set()
            cand = set(self.ix.postings.get(node.terms[0], {}))
            for t in node.terms[1:]:
                cand &= set(self.ix.postings.get(t, {}))
            return {d for d in cand if self.phrase_in(node.terms, d)}
        if isinstance(node, ProximityNode):
            both = self.eval(node.left) & self.eval(node.right)
            op = node.operator.lower()
            dist = int(op[1:]) if op[1:].isdigit() else 5
            lt, rt = self.terms_of(node.left), self.terms_of(node.right)
            out = set()
            for d in both:
                lp = [p for t in lt for p in self.positions(t, d)]
                rp = [p for t in rt for p in self.positions(t, d)]
                if any(abs(a - b) <= dist for a in lp for b in rp):
                    out.add(d)
            return out
        if isinstance(node, BooleanNode):
            a, b = self.eval(node.left), self.eval(node.right)
            return a & b if node.operator.upper() == "AND" else a | b
        if isinstance(node, NotNode):
            return self.all_docs - self.eval(node.child)
        raise AssertionError(node)

    def zone_bm25(self, term, doc, zone):
        tf = self.ix.postings.get(term, {}).get(doc, {}).get("zones", {}).get(zone, 0)
        if tf <= 0:
            return 0.0
        df = len(self.ix.postings[term])
        idf = math.log(1.0 + (len(self.all_docs) - df + 0.5) / (df + 0.5))
        dl = self.ix.doc_lengths[doc].get(zone, 0)
        return idf * ((tf * (K1 + 1.0)) / (tf + K1 * (1.0 - B + B * (dl / self.avg[zone]))))

    def search(self, query, k=100, filters=None):
        """[(doc_id, rel, zone_scores)] best first, equal scores by doc id."""
        if k <= 0 or not query.strip():
            return []
        ast = parse_query(query)
        cand = self.eval(ast)
        terms = list(dict.fromkeys(self.terms_of(ast)))
        for key in ("year", "bench_size"):
            if filters and key in filters:
                cand = {d for d in cand if self.ix.doc_meta[d].get(key) == filters[key]}
        scored = []
        for d in cand:
            zs = {z: sum(self.zone_bm25(t, d, z) for t in terms) for z in ZONES}
            scored.append((d, sum(ZONE_WEIGHTS[z] * zs[z] for z in ZONES), zs))
        return heapq.nsmallest(k, scored, key=lambda x: (-x[1], x[0]))


# ------------------------------------------------------------------------------------------------------ generators
def random_corpus(rng: random.Random, n_docs: int, *, single_zone: bool = False, max_len: int = 14, vocab_size: int = 10):
    """{doc_id: (meta, {zone: tokens})}: zones in a random order and of random lengths, some empty; words drawn with a skew, so a
    few are in nearly every document and a few in almost none."""
    vocab = VOCAB[:vocab_size]
    weights = [1.0 / (i + 1) ** 1.3 for i in range(len(vocab))]
    docs = {}
    for i in range(n_docs):
        names = list(ZONES)
        rng.shuffle(names)
        names = names[:1] if single_zone else names[:rng.randint(1, len(names))]
        zones = {z: rng.choices(vocab, weights, k=rng.randint(0, max_len)) for z in names}
        year = rng.choice([2019, 2020, 2021, None])
        meta = {"year": year, "bench_size": rng.choice([1, 2, 3, None]), "title": f"Case {i}", "date": None if year is None else f"{year}-05-05"}
        docs[f"doc{i:03d}"] = (meta, zones)
    return docs


def build_compact(docs) -> InvertedIndex:
    builder = IndexBuilder()
    for doc_id, (meta, zones) in docs.items():
        builder.add_tokens(doc_id, meta, zones)
    return builder.finish()


def random_query(rng: random.Random, vocab_size: int = 10, depth: int = 0) -> str:
    """A query generated from the grammar: OR of ANDs of (NOT)* (atom [/k atom]), atoms being terms, phrases or parenthesised queries."""
    vocab = VOCAB[:vocab_size]
    weights = [1.0 / (i + 1) ** 1.3 for i in range(len(vocab))]

    def term():
        return rng.choices(vocab, weights)[0]

    def atom():
        r = rng.random()
        if depth < 2 and r < 0.15:
            return "(" + random_query(rng, vocab_size, depth + 1) + ")"
        if r < 0.35:
            return '"' + " ".join(term() for _ in range(rng.randint(1, 3))) + '"'
        return term()

    def prox():
        out = atom()
        for _ in range(rng.choice([0, 0, 0, 1, 2])):
            out += f" /{rng.choice(['s', 'p', '1', '2', '3', '5', '10'])} " + atom()
        return out

    def not_term():
        return "NOT " * rng.choice([0, 0, 0, 1, 1, 2]) + prox()

    def and_chain():
        return " AND ".join(not_term() for _ in range(rng.choice([1, 1, 2, 3, 4])))

    return " OR ".join(and_chain() for _ in range(rng.choice([1, 1, 1, 2, 3])))


def random_filters(rng: random.Random):
    return rng.choice([None, None, {"year": 2020}, {"year": 2021}, {"bench_size": 2}, {"year": 2019, "bench_size": 1}, {"year": 1999}, {"bench_size": None}])


# ------------------------------------------------------------------------------------------------------ tests
SEEDS = range(12)


@pytest.mark.parametrize("seed", SEEDS)
def test_the_compact_index_holds_exactly_the_postings_of_the_reference(seed):
    rng = random.Random(1000 + seed)
    docs = random_corpus(rng, rng.randint(1, 40))
    ref, idx = RefIndex(docs), build_compact(docs)
    assert list(idx.postings_map) == sorted(ref.postings) and len(idx.postings_map) == len(ref.postings)
    assert idx.doc_meta == ref.doc_meta and idx.doc_lengths == ref.doc_lengths
    assert [list(v) for v in idx.doc_lengths.values()] == [list(v) for v in ref.doc_lengths.values()]  # zone order inside a document
    for term, by_doc in ref.postings.items():
        view = idx.postings_map[term]
        assert len(view) == idx.df(term) == len(by_doc)
        assert list(view) == list(by_doc)  # documents in the order they were added
        for doc_id, entry in by_doc.items():
            got = view[doc_id]
            assert got == entry and list(got["zones"]) == list(entry["zones"])  # same positions in the same order, same zone counts
            assert doc_id in view
        for zone in ZONES:
            assert idx.postings(term, zone) == [(d, e["positions"]) for d, e in by_doc.items() if zone in e["zones"]]
        assert idx.postings(term) == [(d, e["positions"]) for d, e in by_doc.items()]
    assert idx.stats["terms"] == len(ref.postings)
    assert idx.stats["postings"] == sum(len(p) for p in ref.postings.values())
    assert idx.stats["positions"] == sum(e["tf"] for p in ref.postings.values() for e in p.values())
    assert idx.stats["zone_tokens"] == {z: sum(lens.get(z, 0) for lens in ref.doc_lengths.values()) for z in ZONES}
    assert "no-such-term" not in idx.postings_map and idx.df("no-such-term") == 0 and idx.postings("no-such-term") == []


@pytest.mark.parametrize("seed", SEEDS)
def test_search_ranks_exactly_like_the_reference_engine_on_random_queries(seed):
    rng = random.Random(2000 + seed)
    docs = random_corpus(rng, rng.randint(2, 40))
    ref, eng = RefEngine(RefIndex(docs)), RankedSearchEngine(index=build_compact(docs))
    for _ in range(40):
        query, filters, k = random_query(rng), random_filters(rng), rng.choice([1, 3, 10, 100])
        want, got = ref.search(query, k, filters), eng.search(query, k=k, filters=filters)
        label = f"{query!r} filters={filters} k={k}"
        assert [h.doc_id for h in got] == [d for d, _, _ in want], label
        for h, (_, rel, zs) in zip(got, want):
            assert h.rel == pytest.approx(rel, abs=1e-9), label
            assert h.zone_scores == pytest.approx(zs, abs=1e-9), label


@pytest.mark.parametrize("seed", SEEDS)
def test_optimised_evaluation_matches_the_naive_one_and_the_reference(seed):
    rng = random.Random(3000 + seed)
    docs = random_corpus(rng, rng.randint(1, 50))
    ref, eng = RefEngine(RefIndex(docs)), RankedSearchEngine(index=build_compact(docs))
    for _ in range(60):
        query = random_query(rng)
        ast = parse_query(query)
        optimised, _ = eng.evaluate(ast, optimise=True)
        naive, _ = eng.evaluate(ast, optimise=False)
        assert optimised == naive == ref.eval(ast), query
        sub = {d for d in docs if rng.random() < 0.5}  # a restriction is the same as intersecting afterwards
        assert eng.evaluate(ast, optimise=True, restrict_ids=sub)[0] == optimised & sub, query
        assert eng.evaluate(ast, optimise=False, restrict_ids=sub)[0] == optimised & sub, query


@pytest.mark.parametrize("seed", range(6))
def test_search_equals_a_brute_force_scan_of_the_tokens_on_single_zone_documents(seed):
    """With one zone per document there is no zone boundary for a phrase to straddle, so a plain scan of the token lists decides
    term, AND, OR, NOT and phrase queries by themselves (no index, no positions arrays involved)."""
    rng = random.Random(4000 + seed)
    docs = random_corpus(rng, rng.randint(2, 30), single_zone=True)
    eng = RankedSearchEngine(index=build_compact(docs))
    tokens = {d: next(iter(zones.values())) if zones else [] for d, (_, zones) in docs.items()}

    def scan(node):
        if isinstance(node, TermNode):
            return {d for d, toks in tokens.items() if node.term in toks}
        if isinstance(node, PhraseNode):
            n = len(node.terms)
            return {d for d, toks in tokens.items() if any(toks[i:i + n] == node.terms for i in range(len(toks) - n + 1))}
        if isinstance(node, BooleanNode):
            a, b = scan(node.left), scan(node.right)
            return a & b if node.operator.upper() == "AND" else a | b
        if isinstance(node, NotNode):
            return set(tokens) - scan(node.child)
        raise AssertionError(node)

    def plain(rng):
        def term():
            return rng.choice(VOCAB[:10])

        def atom():
            return '"' + " ".join(term() for _ in range(rng.randint(2, 3))) + '"' if rng.random() < 0.3 else term()

        return " OR ".join(" AND ".join(("NOT " if rng.random() < 0.3 else "") + atom() for _ in range(rng.randint(1, 3))) for _ in range(rng.randint(1, 2)))

    for _ in range(80):
        query = plain(rng)
        got = {h.doc_id for h in eng.search(query, k=10 ** 6)}
        assert got == scan(parse_query(query)), query


def test_the_generators_cover_the_grammar():
    """The random queries really contain phrases, proximity, NOT, nesting and chains (otherwise the tests above prove less)."""
    rng = random.Random(7)
    queries = [random_query(rng) for _ in range(400)]
    for needle in ('"', " /", "NOT ", "(", " AND ", " OR ", "NOT NOT "):
        assert sum(needle in q for q in queries) > 20, needle
    for q in queries:
        parse_query(q)  # every generated query is well formed
