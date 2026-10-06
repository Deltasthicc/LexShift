"""health(d) and authority(d): the two static quality scores g(d) fused by M4.

health(d): the strongest VALID negative treatment (overruled 0.1, doubted/criticised 0.6, otherwise 1.0), values
from common/config.yaml. A negative counts only if the citing bench is at least as large as the cited bench.
authority(d): PageRank over positive and neutral citation edges x bench weight, normalised to [0, 1].

IR concepts: citation graph, PageRank as a static quality score g(d), net score.
"""

from __future__ import annotations

import sys

from common.skeleton import not_implemented, todo_main


def health(doc_id: str, offence_ids: list[str] | None = None) -> tuple[float, list[dict]]:
    """(score in [0, 1], evidence [{citing_doc, label, sentence}]).

    `offence_ids` supports the stretch goal "point-level health": apply a penalty only for queries about the offence
    the overruling discusses. It may be ignored at first.
    """
    not_implemented("M3", "health()")


def authority(doc_id: str) -> float:
    not_implemented("M3", "authority()")


def main(argv: list[str] | None = None) -> int:
    return todo_main("M3", "scores build (doc_health.jsonl)")


if __name__ == "__main__":
    sys.exit(main())
