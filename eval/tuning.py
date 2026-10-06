"""Tune fusion weights by grid search on DEV queries only.

The search walks every weight vector on a coarse simplex grid (step 0.1 by default), ranks the dev queries with it and keeps
the vector with the best mean objective (default nDCG@10). With about ten dev queries a fine grid would only fit noise, so the
grid is coarse, relevance keeps a floor weight (the other signals re-rank BM25 candidates, they do not replace relevance),
and ties go to the vector closest to the starting weights.

`tune_config` raises TuningError if it is handed a query that is not in the dev split: tuning on test queries is the one thing
this project must never do.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any, Iterator, Mapping, Sequence

import yaml

from common.config import load_config
from common.schema import Query
from eval.metrics import OBJECTIVES, aggregate, evaluate_query
from m4_rank.rank import Collected, fuse_collected
from m4_rank.weights import SIGNALS, active_signals, canonical_config, normalise_weights, tuned_path


class TuningError(RuntimeError):
    """Tuning was asked to do something that would invalidate the evaluation."""


def simplex_grid(
    signals: Sequence[str], step: float = 0.1, floors: Mapping[str, float] | None = None
) -> Iterator[dict[str, float]]:
    """Every weight vector over `signals` with multiples of `step` summing to 1 and each weight >= its floor."""
    units = round(1.0 / step)
    if abs(units * step - 1.0) > 1e-9 or units < 1:
        raise ValueError(f"step must divide 1 exactly, got {step}")
    floors = floors or {}
    min_units = [math.ceil(floors.get(s, 0.0) / step - 1e-9) for s in signals]

    def rec(i: int, left: int) -> Iterator[list[int]]:
        if i == len(signals) - 1:
            if left >= min_units[i]:
                yield [left]
            return
        for u in range(min_units[i], left - sum(min_units[i + 1 :]) + 1):
            for rest in rec(i + 1, left - u):
                yield [u, *rest]

    for combo in rec(0, units):
        yield {s: u / units for s, u in zip(signals, combo)}


@dataclass
class Trial:
    weights: dict[str, float]  # all four signals
    score: float
    per_query: dict[str, dict[str, float | None]]


@dataclass
class TuningResult:
    config: str
    objective: str
    best: Trial
    trials: list[Trial]  # best first
    n_queries: int
    grid_size: int


def _objective(per_query: Mapping[str, Mapping[str, float | None]], name: str) -> float:
    mean, n = aggregate(per_query)[name]
    return mean if mean is not None and n else float("-inf")


def tune_config(
    config: str,
    collected: Mapping[str, Collected],
    queries: Sequence[Query],
    qrels: Mapping[str, Mapping[str, int]],
    overruled: set[str] | None,
    *,
    objective: str = "nDCG@10",
    step: float = 0.1,
    floors: Mapping[str, float] | None = None,
    cfg: dict[str, Any] | None = None,
) -> TuningResult:
    """Grid-search the weights of `config` on `queries` (which must all be dev queries)."""
    cfg = cfg or load_config()
    if objective not in OBJECTIVES:
        raise TuningError(f"objective must be a higher-is-better ranking metric, one of {OBJECTIVES}; got {objective!r}")
    not_dev = [q.qid for q in queries if q.split != "dev"]
    if not_dev:
        raise TuningError(f"refusing to tune on non-dev queries: {not_dev[:5]}. Tuning uses the dev split only.")
    if not queries:
        raise TuningError("no dev queries with judgements to tune on")
    name = canonical_config(config, cfg)
    start = normalise_weights(cfg["ranking"]["configs"][name])
    signals = active_signals(start)
    if len(signals) < 2:
        raise TuningError(f"config {name!r} uses a single signal; there is nothing to tune")
    depth = int(cfg["evaluation"]["depth"])
    threshold = int(cfg["evaluation"]["relevant_threshold"])
    gain = str(cfg["evaluation"]["gain"])

    trials: list[Trial] = []
    for vector in simplex_grid(signals, step, floors):
        weights = {s: vector.get(s, 0.0) for s in SIGNALS}
        per_query: dict[str, dict[str, float | None]] = {}
        for q in queries:
            ranked = [r.doc_id for r in fuse_collected(collected[q.qid], weights, depth, cfg)]
            per_query[q.qid] = evaluate_query(
                ranked, qrels[q.qid], overruled, depth=depth, threshold=threshold, gain=gain
            )
        trials.append(Trial(weights, _objective(per_query, objective), per_query))

    def distance(t: Trial) -> float:
        return sum(abs(t.weights[s] - start[s]) for s in SIGNALS)

    trials.sort(key=lambda t: (-round(t.score, 12), round(distance(t), 12), tuple(t.weights[s] for s in SIGNALS)))
    return TuningResult(name, objective, trials[0], trials, len(queries), len(trials))


def save_tuned(new: Mapping[str, Mapping[str, float]], cfg: dict[str, Any] | None = None) -> str:
    """Merge tuned weights into common/weights_tuned.yaml (other configs are kept). Returns the file path."""
    path = tuned_path(cfg)
    existing: dict[str, dict[str, float]] = {}
    if path.exists():
        with open(path, "r", encoding="utf-8") as fh:
            existing = yaml.safe_load(fh) or {}
    for name, weights in new.items():
        existing[name] = {s: round(float(w), 4) for s, w in weights.items() if w > 0}
    header = (
        "# Fusion weights tuned on the DEV split only (python -m eval.run_ablation --tune).\n"
        "# Generated: do not edit by hand. Delete this file to fall back to the starting weights in config.yaml.\n"
    )
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8", newline="\n") as fh:
        fh.write(header)
        yaml.safe_dump(existing, fh, sort_keys=True, default_flow_style=False)
    return str(path)
