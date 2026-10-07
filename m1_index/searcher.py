"""M1 Search Engine: Boolean, proximity, zone-weighted BM25 and lnc.ltc.

`search()` parses the query, finds the matching documents (Boolean, phrase and proximity queries over the positional index, or a
bag of words when the text is not a query), scores them with zone-weighted BM25 and keeps the best k with a heap.

Query optimisation. An AND chain is evaluated smallest posting list first, each operand only over the documents that are still
candidates (a binary-search probe when that reads less than scanning the list), and the chain stops as soon as nothing is left;
`a AND NOT b` is a difference, not a complement; phrase candidates are intersected rarest term first and the positions are
compared rarest term first. The naive left-to-right evaluation is kept (`optimise=False`) as the reference the tests compare with,
and `evaluate()` returns a `WorkStats` so the saving can be counted.

Positions are numbered from 0 inside each zone and the zones of a document are appended one after another, so phrase and proximity
matching works on the merged positions of all zones (a phrase can therefore match across a zone boundary; this is the behaviour
the index has always had and it is kept).
"""

from __future__ import annotations

import math
from bisect import bisect_left
from dataclasses import dataclass
from pathlib import Path
from typing import Iterator

from common.schema import ZONES, Hit
from m1_index import scoring as scorers
from m1_index.index import INDEX_DIR, ZONE_INDEX, InvertedIndex, TermPostings
from m1_index.query_parser import (
    BooleanNode,
    NotNode,
    PhraseNode,
    ProximityNode,
    TermNode,
    parse_query,
)
from m1_index.tokenizer import tokenize

ZONE_WEIGHTS = {
    "headnote": 3.0,
    "holding": 2.5,
    "facts": 1.0,
    "arguments": 0.75,
}
K1 = 1.2
B = 0.75
SCORINGS = ("bm25", "bm25_flat", "lnc.ltc")


@dataclass
class WorkStats:
    """What an evaluation read. `postings_read` counts posting-list entries: a scan reads every entry of the list, a probe reads
    about log2(df) entries per candidate. `positional_checks` counts documents whose position lists were compared."""

    postings_read: int = 0
    positional_checks: int = 0

    @property
    def total(self) -> int:
        return self.postings_read + self.positional_checks


class RankedSearchEngine:
    """Zone-weighted BM25 search over InvertedIndex."""

    _instance = None

    def __init__(self, index_dir: Path | str | None = None, index: InvertedIndex | None = None):
        """`index_dir` defaults to the repository's data/processed/index (not the working directory); `index` hands in an index
        that is already in memory."""
        self.index = index if index is not None else InvertedIndex.load(INDEX_DIR if index_dir is None else index_dir)
        self.doc_meta = self.index.doc_meta
        self.doc_count = len(self.doc_meta)
        self.all_doc_ids = set(self.doc_meta.keys())
        self.last_work = WorkStats()  # the evaluation of the most recent search() (best effort when threads share the engine)

        # Compute average zone lengths
        self.avg_zone_length = {z: 1.0 for z in ZONES}
        for z in ZONES:
            lens = [
                self.index.doc_lengths.get(d, {}).get(z, 0)
                for d in self.all_doc_ids
            ]
            self.avg_zone_length[z] = (sum(lens) / len(lens)) if lens else 1.0

        self._zone_len = [[self.index.doc_lengths.get(d, {}).get(z, 0) for d in self.index.doc_ids] for z in ZONES]
        self._avg = [self.avg_zone_length[z] for z in ZONES]
        self._all_nums = set(range(len(self.index.doc_ids)))

    @classmethod
    def get_instance(cls) -> "RankedSearchEngine":
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance

    def _idf(self, term: str) -> float:
        df = self.index.df(term)
        if df == 0:
            return 0.0
        return math.log(1.0 + (self.doc_count - df + 0.5) / (df + 0.5))

    # --- helpers over the compact index ---

    def _ids(self, nums) -> set[str]:
        ids = self.index.doc_ids
        return {ids[n] for n in nums}

    def _get_term_positions(self, term: str, doc_id: str) -> list[int]:
        tp = self.index.term_postings(term)
        num = self.index.doc_num_of.get(doc_id)
        if tp is None or num is None:
            return []
        i = tp.find(num)
        return [] if i < 0 else tp.positions(i)

    def _candidate_postings(self, tp: TermPostings, nums: set[int]) -> Iterator[tuple[int, int]]:
        """(document number, posting index) for the postings of `tp` that lie in `nums`: probe each candidate when there are few,
        scan the list otherwise."""
        if len(nums) * max(1, tp.df.bit_length()) < tp.df:
            for n in nums:
                i = tp.find(n)
                if i >= 0:
                    yield n, i
        else:
            p_doc = self.index.p_doc
            for i in range(tp.lo, tp.hi):
                n = p_doc[i]
                if n in nums:
                    yield n, i

    # --- AST candidate resolution: the naive reference (left to right, everything read in full) ---

    def _naive(self, node: object, work: WorkStats) -> set[int]:
        if isinstance(node, TermNode):
            tp = self.index.term_postings(node.term)
            if tp is None:
                return set()
            work.postings_read += tp.df
            return set(tp.docs())

        if isinstance(node, PhraseNode):
            if not node.terms:
                return set()
            candidates: set[int] | None = None
            for t in node.terms:
                docs = self._naive(TermNode(t), work)
                candidates = docs if candidates is None else candidates & docs
            out = set()
            for d in candidates or ():
                work.positional_checks += 1
                if self._phrase_naive(node.terms, d):
                    out.add(d)
            return out

        if isinstance(node, ProximityNode):
            l_docs = self._naive(node.left, work)
            r_docs = self._naive(node.right, work)
            max_dist = self._max_dist(node.operator.lower())
            left_terms, right_terms = self._collect_terms(node.left), self._collect_terms(node.right)
            out = set()
            for d in l_docs & r_docs:
                work.positional_checks += 1
                l_pos = [p for t in left_terms for p in self._positions_num(t, d)]
                r_pos = [p for t in right_terms for p in self._positions_num(t, d)]
                if l_pos and r_pos and any(abs(lp - rp) <= max_dist for lp in l_pos for rp in r_pos):
                    out.add(d)
            return out

        if isinstance(node, BooleanNode):
            l_docs = self._naive(node.left, work)
            r_docs = self._naive(node.right, work)
            return (l_docs & r_docs) if node.operator.upper() == "AND" else (l_docs | r_docs)

        if isinstance(node, NotNode):
            return self._all_nums - self._naive(node.child, work)

        return set()

    def _positions_num(self, term: str, num: int) -> list[int]:
        tp = self.index.term_postings(term)
        if tp is None:
            return []
        i = tp.find(num)
        return [] if i < 0 else tp.positions(i)

    def _phrase_naive(self, terms: list[str], num: int) -> bool:
        first_pos = self._positions_num(terms[0], num)
        if not first_pos:
            return False
        for start in first_pos:
            matched = True
            for offset, term in enumerate(terms[1:], start=1):
                if (start + offset) not in set(self._positions_num(term, num)):
                    matched = False
                    break
            if matched:
                return True
        return False

    @staticmethod
    def _max_dist(op: str) -> int:
        max_dist = 5  # /s and /p mean within 5 tokens
        if op.startswith("/") and op[1:].isdigit():
            max_dist = int(op[1:])
        return max_dist

    # --- AST candidate resolution: optimised ---

    @staticmethod
    def _flatten(node: object, operator: str) -> list[object]:
        """The operands of a chain of one Boolean operator, left to right (iterative: a long chain is a deep tree)."""
        out: list[object] = []
        stack = [node]
        while stack:
            n = stack.pop()
            if isinstance(n, BooleanNode) and n.operator.upper() == operator:
                stack.append(n.right)
                stack.append(n.left)
            else:
                out.append(n)
        return out

    def _estimate(self, node: object) -> int:
        """An upper bound on the number of matching documents, used only to order the operands of an AND."""
        if isinstance(node, TermNode):
            return self.index.df(node.term)
        if isinstance(node, PhraseNode):
            return min((self.index.df(t) for t in node.terms), default=0)
        if isinstance(node, ProximityNode):
            return min(self._estimate(node.left), self._estimate(node.right))
        if isinstance(node, BooleanNode):
            if node.operator.upper() == "AND":
                kids = [self._estimate(n) for n in self._flatten(node, "AND") if not isinstance(n, NotNode)]
                return min(kids, default=self.doc_count)
            return min(self.doc_count, sum(self._estimate(n) for n in self._flatten(node, "OR")))
        return self.doc_count  # a NOT matches the complement

    def _term_docs(self, tp: TermPostings | None, restrict: set[int] | None, work: WorkStats) -> set[int]:
        if tp is None:
            return set()
        if restrict is None:
            work.postings_read += tp.df
            return set(tp.docs())
        probe_cost = len(restrict) * max(1, tp.df.bit_length())
        if probe_cost < tp.df:
            work.postings_read += probe_cost
            return {n for n in restrict if tp.find(n) >= 0}
        work.postings_read += tp.df
        return restrict.intersection(tp.docs())

    def _phrase_docs(self, terms: list[str], restrict: set[int] | None, work: WorkStats) -> set[int]:
        if not terms:
            return set()
        tps: dict[str, TermPostings] = {}
        for t in terms:
            tp = self.index.term_postings(t)
            if tp is None:
                return set()  # a term that is not in the index: no document has the phrase
            tps[t] = tp
        candidates = restrict
        for t in sorted(tps, key=lambda term: (tps[term].df, term)):  # rarest term first
            candidates = self._term_docs(tps[t], candidates, work)
            if not candidates:
                return set()
        out = set()
        for d in candidates:  # type: ignore[union-attr]
            work.positional_checks += 1
            positions = [tps[t].positions(tps[t].find(d)) for t in terms]
            starts: set[int] | None = None
            for i in sorted(range(len(terms)), key=lambda j: len(positions[j])):  # the term with the fewest positions first
                shifted = {p - i for p in positions[i]}  # where the phrase would start if this term is its i-th word
                starts = shifted if starts is None else starts & shifted
                if not starts:
                    break
            if starts:
                out.add(d)
        return out

    def _proximity_docs(self, node: ProximityNode, restrict: set[int] | None, work: WorkStats) -> set[int]:
        first, second = (node.left, node.right) if self._estimate(node.left) <= self._estimate(node.right) else (node.right, node.left)
        a = self._opt(first, restrict, work)
        if not a:
            return set()
        candidates = self._opt(second, a, work)
        if not candidates:
            return set()
        max_dist = self._max_dist(node.operator.lower())
        left_terms, right_terms = self._collect_terms(node.left), self._collect_terms(node.right)
        tps = {t: self.index.term_postings(t) for t in set(left_terms) | set(right_terms)}

        def gather(terms: list[str], num: int) -> list[int]:
            out: list[int] = []
            for t in terms:
                tp = tps[t]
                if tp is not None:
                    i = tp.find(num)
                    if i >= 0:
                        out.extend(tp.positions(i))
            return out

        out = set()
        for d in candidates:
            work.positional_checks += 1
            l_pos, r_pos = gather(left_terms, d), gather(right_terms, d)
            if not l_pos or not r_pos:
                continue
            r_pos.sort()
            for p in l_pos:  # is there a right-hand position in [p - max_dist, p + max_dist]?
                j = bisect_left(r_pos, p - max_dist)
                if j < len(r_pos) and r_pos[j] <= p + max_dist:
                    out.add(d)
                    break
        return out

    def _opt(self, node: object, restrict: set[int] | None, work: WorkStats) -> set[int]:
        """The documents matching `node`, restricted to `restrict` when given: eval(node, R) = eval(node) & R, so the restriction
        can be handed down to every operand."""
        if restrict is not None and not restrict:
            return set()

        if isinstance(node, TermNode):
            return self._term_docs(self.index.term_postings(node.term), restrict, work)

        if isinstance(node, PhraseNode):
            return self._phrase_docs(node.terms, restrict, work)

        if isinstance(node, ProximityNode):
            return self._proximity_docs(node, restrict, work)

        if isinstance(node, BooleanNode) and node.operator.upper() == "AND":
            positives: list[object] = []
            negatives: list[object] = []
            for operand in self._flatten(node, "AND"):
                while isinstance(operand, NotNode) and isinstance(operand.child, NotNode):
                    operand = operand.child.child  # NOT NOT x is x
                if isinstance(operand, NotNode):
                    negatives.append(operand.child)
                else:
                    positives.append(operand)
            order = sorted(range(len(positives)), key=lambda i: (self._estimate(positives[i]), i))  # smallest posting list first
            running = restrict
            for i in order:
                running = self._opt(positives[i], running, work)
                if not running:
                    return set()  # nothing left: the other operands cannot add anything
            if running is None:
                running = set(self._all_nums)
            for child in negatives:  # a AND NOT b is a - b: read b only for the documents that are still candidates
                running = running - self._opt(child, running, work)
                if not running:
                    return set()
            return running

        if isinstance(node, BooleanNode):
            found: set[int] = set()
            for operand in self._flatten(node, "OR"):
                remaining = None if restrict is None else restrict - found
                if remaining is not None and not remaining:
                    break
                found |= self._opt(operand, remaining, work)
            return found

        if isinstance(node, NotNode):
            inner = self._opt(node.child, restrict, work)
            return set(self._all_nums if restrict is None else restrict) - inner

        return set()

    def evaluate(self, node: object, optimise: bool = True, restrict_ids: set[str] | None = None) -> tuple[set[str], WorkStats]:
        """The ids of the documents matching a parsed query and what the evaluation read. `optimise=False` is the naive reference."""
        work = WorkStats()
        if optimise:
            restrict = None if restrict_ids is None else {self.index.doc_num_of[d] for d in restrict_ids if d in self.index.doc_num_of}
            nums = self._opt(node, restrict, work)
        else:
            nums = self._naive(node, work)
            if restrict_ids is not None:
                nums = {n for n in nums if self.index.doc_ids[n] in restrict_ids}
        return self._ids(nums), work

    def _eval_ast(self, node: object, optimise: bool = True) -> set[str]:
        return self.evaluate(node, optimise)[0]

    def _collect_terms(self, node: object) -> list[str]:
        """The terms of a query tree, left to right (iterative: a long chain is a deep tree)."""
        out: list[str] = []
        stack = [node]
        while stack:
            n = stack.pop()
            if isinstance(n, TermNode):
                out.append(n.term)
            elif isinstance(n, PhraseNode):
                out.extend(n.terms)
            elif isinstance(n, (BooleanNode, ProximityNode)):
                stack.append(n.right)
                stack.append(n.left)
            elif isinstance(n, NotNode):
                stack.append(n.child)
        return out

    # --- BM25 Scoring ---

    def _zone_bm25(self, term: str, doc_id: str, zone: str) -> float:
        tp = self.index.term_postings(term)
        num = self.index.doc_num_of.get(doc_id)
        if tp is None or num is None or zone not in ZONE_INDEX:
            return 0.0
        i = tp.find(num)
        if i < 0:
            return 0.0
        tf = tp.zone_tfs(i)[ZONE_INDEX[zone]]
        if tf <= 0:
            return 0.0

        dl = self.index.doc_lengths.get(doc_id, {}).get(zone, 0)
        avgdl = self.avg_zone_length.get(zone, 1.0)
        idf = self._idf(term)
        denom = tf + K1 * (1.0 - B + B * (dl / avgdl))
        return idf * ((tf * (K1 + 1.0)) / denom)

    def _zone_scores(self, terms: list[str], nums: set[int]) -> dict[int, list[float]]:
        """Zone-weighted BM25 pieces for every candidate, one term at a time: doc number -> [BM25 of the terms in each zone]. The
        arithmetic and the order of the additions are those of the per-document formula, so the numbers are identical."""
        rows = {n: [0.0] * len(ZONES) for n in nums}
        if not rows:
            return rows
        k1p1 = K1 + 1.0
        for term in terms:
            tp = self.index.term_postings(term)
            if tp is None:
                continue
            idf = self._idf(term)
            for n, i in self._candidate_postings(tp, nums):
                row = rows[n]
                for zi, tf in enumerate(tp.zone_tfs(i)):
                    if tf > 0:
                        row[zi] += idf * ((tf * k1p1) / (tf + K1 * (1.0 - B + B * (self._zone_len[zi][n] / self._avg[zi]))))
        return rows

    @staticmethod
    def _total(row: list[float]) -> float:
        """The zone-weighted sum, added in ZONES order."""
        total = 0
        for i, z in enumerate(ZONES):
            total += ZONE_WEIGHTS.get(z, 1.0) * row[i]
        return total

    @classmethod
    def _combine(cls, row: list[float]) -> tuple[float, dict[str, float]]:
        return cls._total(row), {z: row[i] for i, z in enumerate(ZONES)}

    def bm25_score(self, terms: list[str], doc_id: str) -> tuple[float, dict[str, float]]:
        num = self.index.doc_num_of.get(doc_id)
        if num is None:
            return self._combine([0.0] * len(ZONES))
        return self._combine(self._zone_scores(terms, {num})[num])

    # --- query to candidates ---

    def _filter_nums(self, filters: dict | None) -> set[int] | None:
        """The documents that pass the parametric filters (year, bench_size), or None when no filter applies."""
        if not filters:
            return None
        nums: set[int] | None = None
        for key in ("year", "bench_size"):
            if key in filters:
                want = filters[key]
                passing = {n for n, d in enumerate(self.index.doc_ids) if self.doc_meta.get(d, {}).get(key) == want}
                nums = passing if nums is None else nums & passing
        return nums

    def _candidates(self, query: str, allowed: set[int] | None, work: WorkStats) -> tuple[set[int], list[str]]:
        """(matching document numbers, distinct query terms). A query that does not parse is treated as a bag of words."""
        try:
            ast = parse_query(query)
            nums = self._opt(ast, allowed, work)
            terms = list(dict.fromkeys(self._collect_terms(ast)))
        except (ValueError, RecursionError):
            # Fallback to plain query tokenization on free text
            terms = list(dict.fromkeys(tokenize(query)))
            nums = set()
            for t in terms:
                nums |= self._term_docs(self.index.term_postings(t), allowed, work)
        return nums, terms

    def search(self, query: str, k: int = 100, filters: dict | None = None) -> list[Hit]:
        if k <= 0 or not query.strip():
            return []

        work = WorkStats()
        allowed = self._filter_nums(filters)
        candidate_nums, terms = self._candidates(query, allowed, work)
        self.last_work = work

        rows = self._zone_scores(terms, candidate_nums)
        ids = self.index.doc_ids
        totals = {ids[n]: self._total(row) for n, row in rows.items()}
        hits = []
        for doc_id, rel in scorers.top_k(totals, k):
            _, zone_scores = self._combine(rows[self.index.doc_num_of[doc_id]])
            hits.append(Hit(doc_id=doc_id, rel=float(rel), zone_scores=zone_scores))
        for hit in hits:
            hit.validate()
        return hits

    def rank(self, query: str, k: int = 100, scoring: str = "bm25", filters: dict | None = None) -> list[Hit]:
        """The same candidates as `search()`, ranked by the chosen function: "bm25" (zone-weighted, what search() returns),
        "bm25_flat" (BM25 over each document's zones joined) or "lnc.ltc" (SMART cosine). Only "bm25" fills `zone_scores`."""
        if scoring not in SCORINGS:
            raise ValueError(f"unknown scoring {scoring!r}; choose from {SCORINGS}")
        if scoring == "bm25":
            return self.search(query, k=k, filters=filters)
        if k <= 0 or not query.strip():
            return []
        candidate_nums, terms = self._candidates(query, self._filter_nums(filters), WorkStats())
        candidates = self._ids(candidate_nums)
        function = scorers.bm25_scores if scoring == "bm25_flat" else scorers.lnc_ltc_scores
        scores = function(terms, self.index, candidates=candidates)
        for doc_id in candidates:  # a candidate with no query term (a NOT query) scores 0
            scores.setdefault(doc_id, 0.0)
        hits = [Hit(doc_id=d, rel=float(s)) for d, s in scorers.top_k(scores, k)]
        for hit in hits:
            hit.validate()
        return hits

    def print_postings_and_scores(self, term: str, top_n: int = 5) -> None:
        """Helper for demo video to display postings and raw calculations."""
        print(f"\n--- Video Evidence: Postings & Scores for {term!r} ---")
        postings = self.index.postings(term)
        print(f"Document Frequency: {len(postings)}")
        for doc_id, positions in postings[:top_n]:
            score, zones = self.bm25_score([term], doc_id)
            print(f"Doc: {doc_id} | Positions: {positions[:5]} | Raw BM25: {score:.4f} | Zones: {zones}")


def search(query: str, k: int = 100, filters: dict | None = None) -> list[Hit]:
    """Team API contract."""
    engine = RankedSearchEngine.get_instance()
    return engine.search(query, k=k, filters=filters)
