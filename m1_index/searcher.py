"""M1 Search Engine: Boolean, proximity, zone-weighted BM25 and lnc.ltc."""

from __future__ import annotations

import heapq
import math
from pathlib import Path

from common.schema import Hit, ZONES
from m1_index.index import InvertedIndex
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


class RankedSearchEngine:
    """Zone-weighted BM25 search over InvertedIndex."""

    _instance = None

    def __init__(self, index_dir: Path | str = "data/processed/index"):
        self.index = InvertedIndex.load(index_dir)
        self.doc_meta = self.index.doc_meta
        self.doc_count = len(self.doc_meta)
        self.all_doc_ids = set(self.doc_meta.keys())

        # Compute average zone lengths
        self.avg_zone_length = {z: 1.0 for z in ZONES}
        for z in ZONES:
            lens = [
                self.index.doc_lengths.get(d, {}).get(z, 0)
                for d in self.all_doc_ids
            ]
            self.avg_zone_length[z] = (sum(lens) / len(lens)) if lens else 1.0

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

    # --- AST Candidate Resolution ---

    def _get_term_positions(self, term: str, doc_id: str) -> list[int]:
        return self.index.postings_map.get(term, {}).get(doc_id, {}).get("positions", [])

    def _match_phrase(self, terms: list[str], doc_id: str) -> bool:
        if not terms:
            return True
        first_pos = self._get_term_positions(terms[0], doc_id)
        if not first_pos:
            return False
        for start in first_pos:
            matched = True
            for offset, term in enumerate(terms[1:], start=1):
                pos_set = set(self._get_term_positions(term, doc_id))
                if (start + offset) not in pos_set:
                    matched = False
                    break
            if matched:
                return True
        return False

    def _match_proximity(self, left_docs: set[str], right_docs: set[str], op: str, node: ProximityNode) -> set[str]:
        candidates = left_docs & right_docs
        matched = set()
        left_terms = self._collect_terms(node.left)
        right_terms = self._collect_terms(node.right)

        max_dist = 5
        if op.startswith("/") and op[1:].isdigit():
            max_dist = int(op[1:])

        for doc in candidates:
            # Check positional distance across all terms
            l_positions = [p for t in left_terms for p in self._get_term_positions(t, doc)]
            r_positions = [p for t in right_terms for p in self._get_term_positions(t, doc)]
            if not l_positions or not r_positions:
                continue

            found = any(abs(lp - rp) <= max_dist for lp in l_positions for rp in r_positions)
            if found:
                matched.add(doc)
        return matched

    def _eval_ast(self, node: object) -> set[str]:
        if isinstance(node, TermNode):
            return set(self.index.postings_map.get(node.term, {}).keys())

        if isinstance(node, PhraseNode):
            if not node.terms:
                return set()
            candidates = set(self.index.postings_map.get(node.terms[0], {}).keys())
            for t in node.terms[1:]:
                candidates &= set(self.index.postings_map.get(t, {}).keys())
            return {d for d in candidates if self._match_phrase(node.terms, d)}

        if isinstance(node, ProximityNode):
            l_docs = self._eval_ast(node.left)
            r_docs = self._eval_ast(node.right)
            return self._match_proximity(l_docs, r_docs, node.operator.lower(), node)

        if isinstance(node, BooleanNode):
            l_docs = self._eval_ast(node.left)
            r_docs = self._eval_ast(node.right)
            return (l_docs & r_docs) if node.operator.upper() == "AND" else (l_docs | r_docs)

        if isinstance(node, NotNode):
            return self.all_doc_ids - self._eval_ast(node.child)

        return set()

    def _collect_terms(self, node: object) -> list[str]:
        if isinstance(node, TermNode):
            return [node.term]
        if isinstance(node, PhraseNode):
            return list(node.terms)
        if isinstance(node, (BooleanNode, ProximityNode)):
            return self._collect_terms(node.left) + self._collect_terms(node.right)
        if isinstance(node, NotNode):
            return self._collect_terms(node.child)
        return []

    # --- BM25 Scoring ---

    def _zone_bm25(self, term: str, doc_id: str, zone: str) -> float:
        tf = self.index.postings_map.get(term, {}).get(doc_id, {}).get("zones", {}).get(zone, 0)
        if tf <= 0:
            return 0.0

        dl = self.index.doc_lengths.get(doc_id, {}).get(zone, 0)
        avgdl = self.avg_zone_length.get(zone, 1.0)
        idf = self._idf(term)
        denom = tf + K1 * (1.0 - B + B * (dl / avgdl))
        return idf * ((tf * (K1 + 1.0)) / denom)

    def bm25_score(self, terms: list[str], doc_id: str) -> tuple[float, dict[str, float]]:
        zone_scores = {}
        for z in ZONES:
            z_score = sum(self._zone_bm25(t, doc_id, z) for t in terms)
            zone_scores[z] = z_score

        total_rel = sum(ZONE_WEIGHTS.get(z, 1.0) * zone_scores[z] for z in ZONES)
        return total_rel, zone_scores

    def search(self, query: str, k: int = 100, filters: dict | None = None) -> list[Hit]:
        if k <= 0 or not query.strip():
            return []

        try:
            ast = parse_query(query)
            candidate_docs = self._eval_ast(ast)
            terms = list(dict.fromkeys(self._collect_terms(ast)))
        except ValueError:
            # Fallback to plain query tokenization on free text
            terms = list(dict.fromkeys(tokenize(query)))
            candidate_docs = set()
            for t in terms:
                candidate_docs.update(self.index.postings_map.get(t, {}).keys())

        # Parametric filtering
        if filters:
            if "year" in filters:
                y = filters["year"]
                candidate_docs = {d for d in candidate_docs if self.doc_meta.get(d, {}).get("year") == y}
            if "bench_size" in filters:
                bs = filters["bench_size"]
                candidate_docs = {d for d in candidate_docs if self.doc_meta.get(d, {}).get("bench_size") == bs}

        scored = []
        for doc_id in candidate_docs:
            score, zones = self.bm25_score(terms, doc_id)
            scored.append((score, doc_id, zones))

        top = heapq.nlargest(k, scored, key=lambda x: x[0])
        hits = [Hit(doc_id=d, rel=float(s), zone_scores=zs) for s, d, zs in top]
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