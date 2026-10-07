import json
from pathlib import Path

from m1_index.parser import (
    TermNode,
    PhraseNode,
    ProximityNode,
    BooleanNode,
    NotNode,
    parse_query,
)


BASE_DIR = Path.home() / "lexshift"

INDEX_FILE = (
    BASE_DIR
    / "data/processed/inverted_index.json"
)

CORPUS_FILE = (
    BASE_DIR
    / "data/processed/tokenized_judgments.jsonl"
)


class SearchEngine:

    def __init__(self):
        print("Loading index...")

        with open(INDEX_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)

        self.index = data["index"]
        self.metadata = data["metadata"]

        self.all_docs = set()

        for postings in self.index.values():
            self.all_docs.update(postings.keys())

        print(
            f"Loaded {len(self.all_docs)} documents "
            f"and {len(self.index)} terms."
        )

    # ==========================================================
    # Basic term lookup
    # ==========================================================

    def get_docs(self, term):
        """Return all documents containing term."""

        if term not in self.index:
            return set()

        return set(self.index[term].keys())

    def get_posting(self, term, doc_id):
        """Return posting for term/document."""

        return self.index.get(term, {}).get(doc_id)

    def get_positions(self, term, doc_id):
        """Return token positions for a term."""

        posting = self.get_posting(term, doc_id)

        if not posting:
            return []

        return posting.get("positions", [])

    # ==========================================================
    # Occurrence information
    # ==========================================================

    def term_occurrences(self, term, doc_id):
        """
        Return occurrences as:

            (position, sentence_id, paragraph_id)
        """

        posting = self.get_posting(term, doc_id)

        if not posting:
            return []

        positions = posting.get("positions", [])
        sentence_ids = posting.get("sentence_ids", [])
        paragraph_ids = posting.get("paragraph_ids", [])

        occurrences = []

        for i, position in enumerate(positions):

            sentence_id = (
                sentence_ids[i]
                if i < len(sentence_ids)
                else None
            )

            paragraph_id = (
                paragraph_ids[i]
                if i < len(paragraph_ids)
                else None
            )

            occurrences.append(
                (position, sentence_id, paragraph_id)
            )

        return occurrences

    # ==========================================================
    # Phrase matching
    # ==========================================================

    def phrase_positions(self, terms, doc_id):
        """
        Return starting positions where the complete phrase occurs.

        Example:

            common intention murder

        returns positions where:

            common
            intention
            murder

        occur consecutively.
        """

        if not terms:
            return []

        first_positions = self.get_positions(
            terms[0],
            doc_id
        )

        if not first_positions:
            return []

        term_position_sets = []

        for term in terms[1:]:
            positions = set(
                self.get_positions(term, doc_id)
            )

            if not positions:
                return []

            term_position_sets.append(positions)

        matches = []

        for start_position in first_positions:

            matched = True

            for offset, position_set in enumerate(
                term_position_sets,
                start=1
            ):
                if start_position + offset not in position_set:
                    matched = False
                    break

            if matched:
                matches.append(start_position)

        return matches

    def phrase_occurrences(self, terms, doc_id):
        """
        Return phrase occurrences as:

            (start_position, sentence_id, paragraph_id)
        """

        positions = self.phrase_positions(
            terms,
            doc_id
        )

        if not positions:
            return []

        first_term = terms[0]

        posting = self.get_posting(
            first_term,
            doc_id
        )

        if not posting:
            return []

        posting_positions = posting.get(
            "positions",
            []
        )

        sentence_ids = posting.get(
            "sentence_ids",
            []
        )

        paragraph_ids = posting.get(
            "paragraph_ids",
            []
        )

        position_to_index = {
            position: i
            for i, position in enumerate(posting_positions)
        }

        occurrences = []

        for position in positions:

            i = position_to_index.get(position)

            if i is None:
                continue

            sentence_id = (
                sentence_ids[i]
                if i < len(sentence_ids)
                else None
            )

            paragraph_id = (
                paragraph_ids[i]
                if i < len(paragraph_ids)
                else None
            )

            occurrences.append(
                (position, sentence_id, paragraph_id)
            )

        return occurrences

    def phrase_match(self, terms, doc_id):
        """Return True if phrase occurs in document."""

        return bool(
            self.phrase_positions(
                terms,
                doc_id
            )
        )

    # ==========================================================
    # AST occurrence extraction
    # ==========================================================

    def node_occurrences(self, node, doc_id):
        """
        Return occurrences for a query node.

        Each occurrence is:

            (position, sentence_id, paragraph_id)
        """

        if isinstance(node, TermNode):

            return self.term_occurrences(
                node.term,
                doc_id
            )

        if isinstance(node, PhraseNode):

            return self.phrase_occurrences(
                node.terms,
                doc_id
            )

        if isinstance(node, ProximityNode):

            left_occurrences = self.node_occurrences(
                node.left,
                doc_id
            )

            right_occurrences = self.node_occurrences(
                node.right,
                doc_id
            )

            if not left_occurrences or not right_occurrences:
                return []

            operator = node.operator.lower()

            matches = []

            for left in left_occurrences:

                for right in right_occurrences:

                    left_position, left_sentence, left_paragraph = left
                    right_position, right_sentence, right_paragraph = right

                    matched = False

                    # ------------------------------------------
                    # /s = same sentence
                    # ------------------------------------------

                    if operator == "/s":
                        matched = (
                            left_sentence is not None
                            and right_sentence is not None
                            and left_sentence == right_sentence
                        )

                    # ------------------------------------------
                    # /p = same paragraph
                    # ------------------------------------------

                    elif operator == "/p":
                        matched = (
                            left_paragraph is not None
                            and right_paragraph is not None
                            and left_paragraph == right_paragraph
                        )

                    # ------------------------------------------
                    # /k = within k token positions
                    # ------------------------------------------

                    elif operator.startswith("/"):

                        try:
                            k = int(operator[1:])
                        except ValueError:
                            k = 0

                        matched = (
                            abs(
                                left_position
                                - right_position
                            )
                            <= k
                        )

                    if matched:

                        # Keep the left occurrence as the
                        # representative occurrence.
                        matches.append(left)

            # Remove duplicates
            unique = []

            seen = set()

            for occurrence in matches:

                if occurrence not in seen:
                    seen.add(occurrence)
                    unique.append(occurrence)

            return unique

        return []

    # ==========================================================
    # Proximity matching
    # ==========================================================

    def proximity_match(
        self,
        left,
        operator,
        right,
        doc_id
    ):
        """
        Evaluate:

            left /s right
            left /p right
            left /k right
        """

        node = ProximityNode(
            left=left,
            operator=operator,
            right=right
        )

        return bool(
            self.node_occurrences(
                node,
                doc_id
            )
        )

    # ==========================================================
    # Node document retrieval
    # ==========================================================

    def node_docs(self, node):
        """Return documents satisfying a query node."""

        if isinstance(node, TermNode):

            return self.get_docs(node.term)

        if isinstance(node, PhraseNode):

            if not node.terms:
                return set()

            candidate_docs = self.get_docs(
                node.terms[0]
            )

            for term in node.terms[1:]:

                candidate_docs &= self.get_docs(term)

                if not candidate_docs:
                    return set()

            return {
                doc_id
                for doc_id in candidate_docs
                if self.phrase_match(
                    node.terms,
                    doc_id
                )
            }

        if isinstance(node, ProximityNode):

            left_docs = self.node_docs(
                node.left
            )

            right_docs = self.node_docs(
                node.right
            )

            candidate_docs = (
                left_docs & right_docs
            )

            return {
                doc_id
                for doc_id in candidate_docs
                if self.proximity_match(
                    node.left,
                    node.operator,
                    node.right,
                    doc_id
                )
            }

        if isinstance(node, BooleanNode):

            operator = node.operator.upper()

            # Optimize AND by evaluating the smaller side first.
            if operator == "AND":

                left_docs = self.node_docs(
                    node.left
                )

                right_docs = self.node_docs(
                    node.right
                )

                return left_docs & right_docs

            if operator == "OR":

                return (
                    self.node_docs(node.left)
                    |
                    self.node_docs(node.right)
                )

        if isinstance(node, NotNode):

            return (
                self.all_docs
                -
                self.node_docs(node.child)
            )

        return set()

    # ==========================================================
    # Query term extraction
    # ==========================================================

    def node_terms(self, node):

        if isinstance(node, TermNode):
            return [node.term]

        if isinstance(node, PhraseNode):
            return list(node.terms)

        if isinstance(node, ProximityNode):

            return (
                self.node_terms(node.left)
                +
                self.node_terms(node.right)
            )

        if isinstance(node, BooleanNode):

            return (
                self.node_terms(node.left)
                +
                self.node_terms(node.right)
            )

        if isinstance(node, NotNode):
            return self.node_terms(node.child)

        return []

    # ==========================================================
    # Public search
    # ==========================================================

    def search(self, query):
        """
        Boolean / phrase / proximity search.

        Returns document IDs sorted for deterministic output.
        """

        ast = parse_query(query)

        if ast is None:
            return []

        results = self.node_docs(ast)

        return sorted(results)


# ==============================================================
# Simple command-line test
# ==============================================================

if __name__ == "__main__":

    engine = SearchEngine()

    queries = [
        "ipc",
        "ipc AND murder",
        "ipc AND NOT bns",
        '"common intention"',
        '"common intention" /s murder',
        '"common intention" /p murder',
        '"common intention" /10 murder',
    ]

    print()
    print("=" * 70)
    print("LEXSHIFT SEARCH TESTS")
    print("=" * 70)

    for query in queries:

        results = engine.search(query)

        print()
        print(f"QUERY: {query}")
        print(f"RESULT COUNT: {len(results)}")
        print(f"TOP RESULTS: {results[:10]}")
