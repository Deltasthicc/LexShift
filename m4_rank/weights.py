"""Fusion weights per ablation config, read from the one config file.

`common/config.yaml` holds the starting weights (placeholders, never findings). When `ranking.use_tuned` is true and
`common/weights_tuned.yaml` exists, the DEV-tuned weights for a config replace its starting weights. That file is only ever
written by `python -m eval.run_ablation --tune`, which tunes on dev queries and refuses to run on test queries.

Weights are renormalised to sum to 1, so with every signal in [0, 1] the fused score also lies in [0, 1].
"""

from __future__ import annotations

import math
from pathlib import Path
from typing import Any, Mapping

import yaml

from common.config import ROOT, load_config

SIGNALS = ("rel", "cont", "health", "auth")
ALIASES = {"b2": "full"}  # the Guide calls the full system B2


class WeightsError(ValueError):
    """A weight vector is invalid."""


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
    name = canonical_config(config, cfg)
    raw: Mapping[str, float] = cfg["ranking"]["configs"][name]
    if cfg["ranking"].get("use_tuned", False):
        tuned = load_tuned(cfg)
        if name in tuned:
            raw = tuned[name]
    return normalise_weights(raw)
