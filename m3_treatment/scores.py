"""health(d) and authority(d): the two static quality scores g(d) fused by M4.

health(d): the strongest VALID negative treatment (overruled 0.1, doubted/criticised 0.6, otherwise 1.0), values
from common/config.yaml. A negative counts only if the citing bench is at least as large as the cited bench.
authority(d): PageRank over positive and neutral citation edges x bench weight, normalised to [0, 1].

IR concepts: citation graph, PageRank as a static quality score g(d), net score.

Both read data/processed/doc_health.jsonl, built offline by `python -m m3_treatment.scores build`; nothing here calls
a model or the network. The file covers every judgment in the corpus, so an unknown doc_id is an error, not 1.0.
"""

from __future__ import annotations

import sys
from functools import lru_cache

from common.config import load_config, resolve_path
from common.io import read_jsonl
from common.schema import NEGATIVE_LABELS


@lru_cache(maxsize=1)
def _table() -> dict[str, dict]:
    path = resolve_path("doc_health")
    if not path.exists():
        raise FileNotFoundError(f"{path} not found; run `python -m app.setup` (restores it from the files in git, no API key), or rebuild it with `make m3`")
    return {r["doc_id"]: r for r in read_jsonl(path)}


def _row(doc_id: str) -> dict:
    try:
        return _table()[doc_id]
    except KeyError:
        raise KeyError(f"{doc_id!r} is not in doc_health.jsonl (it must cover every judgment in judgments.jsonl)") from None


def health(doc_id: str, offence_ids: list[str] | None = None) -> tuple[float, list[dict]]:
    """(score in [0, 1], evidence [{citing_doc, label, sentence}]).

    `offence_ids` supports the stretch goal "point-level health": apply a penalty only for queries about the offence
    the overruling discusses. A negative whose citing judgment has known offence ids (from M2's doc_statutes.jsonl)
    counts only if they overlap the query's; a negative with unknown offence ids always counts.
    """
    row = _row(doc_id)
    evidence = list(row["evidence"])
    if not offence_ids:
        return float(row["health"]), evidence
    values = load_config()["m3_treatment"]["health_values"]
    wanted = set(offence_ids)
    score = values["default"]
    kept = []
    for ev in evidence:
        if ev["label"] in NEGATIVE_LABELS:
            on_point = not ev.get("offence_ids") or bool(wanted & set(ev["offence_ids"]))
            if not on_point:
                continue
            score = min(score, values.get(ev["label"], values["default"]))
        kept.append(ev)
    return float(score), kept


def authority(doc_id: str) -> float:
    return float(_row(doc_id)["authority"])


def main(argv: list[str] | None = None) -> int:
    from m3_treatment.pipeline import main as pipeline_main

    args = list(argv if argv is not None else sys.argv[1:])
    if not args or args[0] != "build":
        print("usage: python -m m3_treatment.scores build")
        return 2
    return pipeline_main(["health"])


if __name__ == "__main__":
    sys.exit(main())
