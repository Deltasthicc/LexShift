"""Inverted index with positions, zone fields and parametric fields.

IR concepts: dictionary + postings, positional index (phrase and proximity queries), zone index, parametric index,
document frequency for query optimisation, optional tiered index (larger benches in tier 1) as a stretch goal.
"""

from __future__ import annotations

import sys
from typing import Iterable

from common.schema import Judgment
from common.skeleton import not_implemented, todo_main


class InvertedIndex:
    """term -> postings [(doc_id, [positions])], per zone, plus parametric fields (year, bench_size)."""

    @classmethod
    def build(cls, judgments: Iterable[Judgment]) -> "InvertedIndex":
        not_implemented("M1", "InvertedIndex.build()")

    def save(self, directory) -> None:
        not_implemented("M1", "InvertedIndex.save()")

    @classmethod
    def load(cls, directory) -> "InvertedIndex":
        not_implemented("M1", "InvertedIndex.load()")

    def postings(self, term: str, zone: str | None = None) -> list[tuple[str, list[int]]]:
        not_implemented("M1", "InvertedIndex.postings()")

    def df(self, term: str) -> int:
        not_implemented("M1", "InvertedIndex.df()")


def main(argv: list[str] | None = None) -> int:
    return todo_main("M1", "index build")


if __name__ == "__main__":
    sys.exit(main())
