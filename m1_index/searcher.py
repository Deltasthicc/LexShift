from __future__ import annotations

import json
import math
import heapq
from dataclasses import dataclass
from pathlib import Path

from .search import SearchEngine


ROOT = Path(__file__).resolve().parent.parent
INDEX_PATH = ROOT / "data" / "processed" / "index" / "inverted_index.json"
CORPUS_PATH = ROOT / "data" / "processed" / "index" / "tokenized_judgments.jsonl"


ZONE_WEIGHTS = {
    "headnote": 3.0,
    "holding": 2.5,
    "facts": 1.0,
    "arguments": 0.75,
}

K1 = 1.2
B = 0.75


@dataclass
class Hit:
    doc_id: str
    rel: float
    zone_scores: dict[str, float]


class RankedSearchEngine:
    """
    M1 ranked retrieval layer.

    Boolean, phrase and proximity candidate retrieval is delegated
    to the verified SearchEngine in search.py.

    Ranking:
        - zone-weighted BM25
        - lnc.ltc cosine baseline
        - heap-based Top-K
        - optional year / bench-size filters
    """

    def __init__(
        self,
        index_path: Path = INDEX_PATH,
        corpus_path: Path = CORPUS_PATH,
    ):
        print("Loading index...")

        with open(index_path, "r", encoding="utf-8") as f:
            data = json.load(f)

        self.index = data["index"]
        self.meta = data.get("metadata", {})

        self.doc_count = self.meta.get(
            "document_count",
            len(self._all_doc_ids()),
        )

        print(
            f"Loaded {self.doc_count} documents "
            f"and {len(self.index)} terms."
        )

        self.search_engine = SearchEngine()

        self.docs = {}
        with open(corpus_path, "r", encoding="utf-8") as f:
            for line in f:
                if line.strip():
                    doc = json.loads(line)
                    self.docs[doc["doc_id"]] = doc

        print(f"Loaded metadata for {len(self.docs)} documents.")

        self.zone_lengths = {}
        self.avg_zone_length = {}

        for doc_id, doc in self.docs.items():
            self.zone_lengths[doc_id] = {}

            for zone in ZONE_WEIGHTS:
                tokens = doc.get("zone_tokens", {}).get(zone, [])
                self.zone_lengths[doc_id][zone] = len(tokens)

        for zone in ZONE_WEIGHTS:
            lengths = [
                self.zone_lengths[d][zone]
                for d in self.docs
            ]

            self.avg_zone_length[zone] = (
                sum(lengths) / len(lengths)
                if lengths
                else 1.0
            )

    # ---------------------------------------------------------
    # Basic document helpers
    # ---------------------------------------------------------

    def _all_doc_ids(self):
        docs = set()

        for posting in self.index.values():
            docs.update(posting.keys())

        return docs

    def _df(self, term: str) -> int:
        posting = self.index.get(term)

        if not posting:
            return 0

        return len(posting)

    def _idf(self, term: str) -> float:
        df = self._df(term)

        if df == 0:
            return 0.0

        # BM25 Robertson/Sparck Jones IDF.
        return math.log(
            1.0 + (self.doc_count - df + 0.5) / (df + 0.5)
        )

    def _terms_from_query(self, query: str) -> list[str]:
        """
        Extract normalized query terms using the same tokenizer
        used by the corpus.
        """
        from .text_tokenizer import tokenize

        return tokenize(query)

    # ---------------------------------------------------------
    # Candidate retrieval
    # ---------------------------------------------------------

    def candidate_docs(self, query: str) -> set[str]:
        """
        Use the verified Boolean/phrase/proximity engine to obtain
        the exact candidate set before ranking.
        """
        return set(self.search_engine.search(query))

    # ---------------------------------------------------------
    # Zone BM25
    # ---------------------------------------------------------

    def zone_bm25(
        self,
        term: str,
        doc_id: str,
        zone: str,
    ) -> float:
        posting = self.index.get(term, {}).get(doc_id)

        if not posting:
            return 0.0

        tf = posting.get("zones", {}).get(zone, 0)

        if tf <= 0:
            return 0.0

        dl = self.zone_lengths[doc_id].get(zone, 0)
        avgdl = self.avg_zone_length.get(zone, 1.0)

        idf = self._idf(term)

        denominator = (
            tf
            + K1
            * (
                1.0
                - B
                + B * (dl / avgdl)
            )
        )

        return idf * (
            (tf * (K1 + 1.0))
            / denominator
        )

    def bm25_score(
        self,
        terms: list[str],
        doc_id: str,
    ) -> tuple[float, dict[str, float]]:
        zone_scores = {}

        for zone, weight in ZONE_WEIGHTS.items():
            score = 0.0

            for term in terms:
                score += self.zone_bm25(
                    term,
                    doc_id,
                    zone,
                )

            zone_scores[zone] = score

        total = sum(
            ZONE_WEIGHTS[z] * zone_scores[z]
            for z in ZONE_WEIGHTS
        )

        return total, zone_scores

    # ---------------------------------------------------------
    # lnc.ltc cosine baseline
    # ---------------------------------------------------------

    def _document_weight(
        self,
        term: str,
        doc_id: str,
    ) -> float:
        """
        lnc document weight:

            1 + log(tf)

        followed by cosine normalization.
        """
        posting = self.index.get(term, {}).get(doc_id)

        if not posting:
            return 0.0

        tf = posting.get("tf", 0)

        if tf <= 0:
            return 0.0

        return 1.0 + math.log10(tf)

    def _query_weight(
        self,
        term: str,
    ) -> float:
        """
        ltc query weight:

            (1 + log(tf)) * idf

        For the short query representation used here,
        query tf is normally 1.
        """
        return self._idf(term)

    def lnc_ltc_score(
        self,
        terms: list[str],
        doc_id: str,
    ) -> float:
        if not terms:
            return 0.0

        unique_terms = list(dict.fromkeys(terms))

        doc_weights = {
            term: self._document_weight(term, doc_id)
            for term in unique_terms
        }

        query_weights = {
            term: self._query_weight(term)
            for term in unique_terms
        }

        numerator = sum(
            doc_weights[t] * query_weights[t]
            for t in unique_terms
        )

        doc_norm = math.sqrt(
            sum(
                value * value
                for value in doc_weights.values()
            )
        )

        query_norm = math.sqrt(
            sum(
                value * value
                for value in query_weights.values()
            )
        )

        if doc_norm == 0.0 or query_norm == 0.0:
            return 0.0

        return numerator / (
            doc_norm * query_norm
        )

    # ---------------------------------------------------------
    # Filters
    # ---------------------------------------------------------

    def apply_filters(
        self,
        doc_ids: set[str],
        filters: dict | None,
    ) -> set[str]:

        if not filters:
            return doc_ids

        result = set(doc_ids)

        if "year" in filters:
            year_filter = filters["year"]

            if isinstance(year_filter, int):
                year_filter = {year_filter}

            year_filter = set(year_filter)

            result = {
                doc_id
                for doc_id in result
                if self._doc_year(doc_id) in year_filter
            }

        if "min_year" in filters:
            result = {
                doc_id
                for doc_id in result
                if self._doc_year(doc_id) >= filters["min_year"]
            }

        if "max_year" in filters:
            result = {
                doc_id
                for doc_id in result
                if self._doc_year(doc_id) <= filters["max_year"]
            }

        if "bench_size" in filters:
            bench = filters["bench_size"]

            if isinstance(bench, int):
                bench = {bench}

            bench = set(bench)

            result = {
                doc_id
                for doc_id in result
                if self.docs.get(doc_id, {}).get("bench_size")
                in bench
            }

        if "min_bench_size" in filters:
            result = {
                doc_id
                for doc_id in result
                if self.docs.get(doc_id, {}).get("bench_size", 0)
                >= filters["min_bench_size"]
            }

        if "max_bench_size" in filters:
            result = {
                doc_id
                for doc_id in result
                if self.docs.get(doc_id, {}).get("bench_size", 0)
                <= filters["max_bench_size"]
            }

        return result

    def _doc_year(self, doc_id: str) -> int | None:
        doc = self.docs.get(doc_id)

        if not doc:
            return None

        date = str(doc.get("date", ""))

        try:
            return int(date[:4])
        except (ValueError, TypeError):
            return None

    # ---------------------------------------------------------
    # Heap-based Top-K
    # ---------------------------------------------------------

    def top_k(
        self,
        scored_docs: list[tuple[float, str, dict]],
        k: int,
    ) -> list[Hit]:

        heap = []

        for score, doc_id, zones in scored_docs:

            item = (score, doc_id, zones)

            if len(heap) < k:
                heapq.heappush(heap, item)

            elif score > heap[0][0]:
                heapq.heapreplace(
                    heap,
                    item,
                )

        heap.sort(
            key=lambda x: (-x[0], x[1])
        )

        return [
            Hit(
                doc_id=doc_id,
                rel=score,
                zone_scores=zones,
            )
            for score, doc_id, zones in heap
        ]

    # ---------------------------------------------------------
    # Public API
    # ---------------------------------------------------------

    def search(
        self,
        query: str,
        k: int = 100,
        filters: dict | None = None,
    ) -> list[Hit]:

        if k <= 0:
            return []

        candidate_docs = self.candidate_docs(query)

        candidate_docs = self.apply_filters(
            candidate_docs,
            filters,
        )

        if not candidate_docs:
            return []

        terms = self._terms_from_query(query)

        # Deduplicate while preserving order.
        terms = list(dict.fromkeys(terms))

        scored = []

        for doc_id in candidate_docs:

            score, zones = self.bm25_score(
                terms,
                doc_id,
            )

            scored.append(
                (score, doc_id, zones)
            )

        return self.top_k(
            scored,
            min(k, len(scored)),
        )

    # ---------------------------------------------------------
    # Baseline comparison
    # ---------------------------------------------------------

    def lnc_ltc_search(
        self,
        query: str,
        k: int = 100,
        filters: dict | None = None,
    ) -> list[tuple[str, float]]:

        candidates = self.candidate_docs(query)

        candidates = self.apply_filters(
            candidates,
            filters,
        )

        terms = list(
            dict.fromkeys(
                self._terms_from_query(query)
            )
        )

        scored = [
            (
                self.lnc_ltc_score(
                    terms,
                    doc_id,
                ),
                doc_id,
            )
            for doc_id in candidates
        ]

        return heapq.nlargest(
            min(k, len(scored)),
            scored,
            key=lambda x: (x[0], x[1]),
        )


# -------------------------------------------------------------
# Verification / demo
# -------------------------------------------------------------

if __name__ == "__main__":

    engine = RankedSearchEngine()

    queries = [
        "ipc",
        "ipc AND murder",
        "ipc AND NOT bns",
        '"common intention"',
        '"common intention" /s murder',
        '"common intention" /p murder',
        '"common intention" /10 murder',
    ]

    print("\n" + "=" * 70)
    print("LEXSHIFT RANKED SEARCH TESTS")
    print("=" * 70)

    for query in queries:

        print(f"\nQUERY: {query}")

        hits = engine.search(
            query,
            k=5,
        )

        print(
            f"Candidates: "
            f"{len(engine.candidate_docs(query))}"
        )

        for i, hit in enumerate(hits, 1):
            print(
                f"{i}. "
                f"{hit.doc_id} "
                f"score={hit.rel:.4f} "
                f"zones={hit.zone_scores}"
            )

    print("\n" + "=" * 70)
    print("LNC.LTC BASELINE")
    print("=" * 70)

    query = "ipc AND murder"

    results = engine.lnc_ltc_search(
        query,
        k=5,
    )

    for i, (score, doc_id) in enumerate(
        results,
        1,
    ):
        print(
            f"{i}. {doc_id} "
            f"score={score:.6f}"
        )
# Team public API
_engine = RankedSearchEngine()

def search(query: str, k: int = 100, filters: dict | None = None) -> list[Hit]:
    return _engine.search(query, k=k, filters=filters)
