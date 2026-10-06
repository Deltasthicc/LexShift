"""Fusion weights per ablation config, read from the one config file.

`common/config.yaml` holds the starting weights (placeholders, never findings). When `ranking.use_tuned` is true and
`common/weights_tuned.yaml` exists, the DEV-tuned weights for a config replace its starting weights. That file is only ever
written by `python -m eval.run_ablation --tune`, which tunes on dev queries and refuses to run on test queries.

Weights are renormalised to sum to 1, so with every signal in [0, 1] the fused score also lies in [0, 1].
"""

from __future__ import annotations

import math
from pathlib import Path
from typing import Any, Mapping, Sequence

import yaml

from common.config import ROOT, load_config

SIGNALS = ("rel", "cont", "health", "auth")
ALIASES = {"b2": "full"}  # the Guide calls the full system B2


class WeightsError(ValueError):
    """A weight vector is invalid."""


def validate_ranking_config(cfg: dict[str, Any]) -> None:
    """Clear errors for a mistyped `ranking:` or `evaluation:` section, instead of a KeyError deep inside fusion."""
    from m4_rank.normalize import NORMALIZERS

    r, ev = cfg["ranking"], cfg["evaluation"]
    for key in ("candidates", "max_evidence", "normalize", "configs"):
        if key not in r:
            raise WeightsError(f"config ranking.{key} is missing")
    if set(r["normalize"]) != set(SIGNALS):
        raise WeightsError(f"ranking.normalize must define exactly {SIGNALS}, got {sorted(r['normalize'])}")
    for signal, strategy in r["normalize"].items():
        if strategy not in NORMALIZERS:
            raise WeightsError(f"ranking.normalize.{signal} must be one of {sorted(NORMALIZERS)}, got {strategy!r}")
    for name in ("b0", "b1", "full"):
        if name not in r["configs"]:
            raise WeightsError(f"ranking.configs must define b0, b1 and full; {name} is missing")
    for name, raw in r["configs"].items():
        if normalise_weights(raw)["rel"] <= 0:
            raise WeightsError(f"ranking.configs.{name} needs a positive rel weight: candidates always come from search(), "
                               "so every system keeps text relevance in its score")
    if int(r["candidates"]) < 1 or int(r["max_evidence"]) < 0:
        raise WeightsError("ranking.candidates must be >= 1 and ranking.max_evidence >= 0")
    for key in ("depth", "relevant_threshold", "gain", "seed"):
        if key not in ev:
            raise WeightsError(f"config evaluation.{key} is missing")
    if int(ev["depth"]) < 10:
        raise WeightsError("evaluation.depth must be >= 10: P@10, Recall@10 and nDCG@10 are computed inside it")
    if int(r["candidates"]) < int(ev["depth"]):
        raise WeightsError("ranking.candidates must be >= evaluation.depth: evaluation cannot look deeper than the candidates")
    if int(ev["relevant_threshold"]) not in (1, 2):
        raise WeightsError("evaluation.relevant_threshold must be 1 or 2")
    if ev["gain"] not in ("exp", "linear"):
        raise WeightsError("evaluation.gain must be exp or linear")


def canonical_config(name: str, cfg: dict[str, Any] | None = None) -> str:
    cfg = cfg or load_config()
    key = ALIASES.get(name.strip().lower(), name.strip().lower())
    known = cfg["ranking"]["configs"]
    if key not in known:
        raise WeightsError(f"unknown config {name!r}; choose one of {sorted(known)} (b2 is an alias of full)")
    return key


def normalise_weights(raw: Mapping[str, float]) -> dict[str, float]:
    """{signal: weight} -> all four signals, non-negative, summing to 1 (unused signals get 0.0)."""
    unknown = set(raw) - set(SIGNALS)
    if unknown:
        raise WeightsError(f"unknown signal(s) {sorted(unknown)}; allowed {SIGNALS}")
    values = {s: float(raw.get(s, 0.0)) for s in SIGNALS}
    for s, v in values.items():
        if not math.isfinite(v) or v < 0:
            raise WeightsError(f"weight for {s} must be a finite number >= 0, got {v!r}")
    total = sum(values.values())
    if total <= 0:
        raise WeightsError("at least one weight must be positive")
    return {s: v / total for s, v in values.items()}


def active_signals(weights: Mapping[str, float]) -> tuple[str, ...]:
    """Signals with a positive weight, in canonical order."""
    return tuple(s for s in SIGNALS if weights.get(s, 0.0) > 0)


def signals_used(weights_by_config: Mapping[str, Mapping[str, float]], names: Sequence[str]) -> tuple[str, ...]:
    """Union of the signals that any of the named configs gives a weight to, in canonical order."""
    return tuple(s for s in SIGNALS if any(s in active_signals(weights_by_config[n]) for n in names))


def format_weights(weights: Mapping[str, float]) -> str:
    """`0.50/0.20/0.20/0.10`, in the order rel/cont/health/auth."""
    return "/".join(f"{weights[s]:.2f}" for s in SIGNALS)


def tuned_path(cfg: dict[str, Any] | None = None) -> Path:
    cfg = cfg or load_config()
    p = Path(cfg["ranking"]["tuned_file"])
    return p if p.is_absolute() else ROOT / p


def load_tuned(cfg: dict[str, Any] | None = None) -> dict[str, dict[str, float]]:
    """DEV-tuned weights keyed by config name; {} when the file does not exist."""
    path = tuned_path(cfg)
    if not path.exists():
        return {}
    with open(path, "r", encoding="utf-8") as fh:
        data = yaml.safe_load(fh) or {}
    if not isinstance(data, dict):
        raise WeightsError(f"{path}: expected a mapping of config name to weights")
    return {name: dict(w) for name, w in data.items()}


def weights_source(config: str, cfg: dict[str, Any] | None = None) -> str:
    """Where `load_weights` takes this config's weights from, for honest reporting."""
    cfg = cfg or load_config()
    name = canonical_config(config, cfg)
    if cfg["ranking"].get("use_tuned", False) and name in load_tuned(cfg):
        return "tuned on dev"
    return "starting weights (untuned placeholders)"


def load_weights(config: str, cfg: dict[str, Any] | None = None) -> dict[str, float]:
    """Normalised weights for `config` (b0, b1, full): tuned if available and enabled, else the starting weights."""
    cfg = cfg or load_config()
    validate_ranking_config(cfg)
    name = canonical_config(config, cfg)
    raw: Mapping[str, float] = cfg["ranking"]["configs"][name]
    if cfg["ranking"].get("use_tuned", False):
        tuned = load_tuned(cfg)
        if name in tuned:
            raw = tuned[name]
    return normalise_weights(raw)
