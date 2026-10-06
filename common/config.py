"""Load and validate common/config.yaml; resolve repository paths.

`LEXSHIFT_CONFIG` points at an alternative config file (used by tests and for experiments).
"""

from __future__ import annotations

import os
from functools import lru_cache
from pathlib import Path
from typing import Any

import yaml

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_CONFIG = ROOT / "common" / "config.yaml"

STUB_GROUPS = ("search", "statute", "health", "authority")
REQUIRED_SECTIONS = ("paths", "stubs", "ranking", "evaluation")


class ConfigError(ValueError):
    """The configuration file is missing something or contains an invalid value."""


def config_path() -> Path:
    return Path(os.environ.get("LEXSHIFT_CONFIG", DEFAULT_CONFIG))


@lru_cache(maxsize=4)
def _load(path_str: str) -> dict[str, Any]:
    with open(path_str, "r", encoding="utf-8") as fh:
        cfg = yaml.safe_load(fh)
    if not isinstance(cfg, dict):
        raise ConfigError(f"{path_str}: top level must be a mapping")
    validate_config(cfg)
    return cfg


def load_config(path: str | os.PathLike | None = None) -> dict[str, Any]:
    """Return the parsed config (cached). Callers must treat the result as read-only."""
    return _load(str(Path(path) if path else config_path()))


def validate_config(cfg: dict[str, Any]) -> None:
    for section in REQUIRED_SECTIONS:
        if section not in cfg:
            raise ConfigError(f"config is missing the '{section}' section")
    stubs = cfg["stubs"]
    if set(stubs) != set(STUB_GROUPS):
        raise ConfigError(f"stubs must define exactly {STUB_GROUPS}, got {sorted(stubs)}")
    for name, value in stubs.items():
        if not isinstance(value, bool):
            raise ConfigError(f"stubs.{name} must be true or false, got {value!r}")


def resolve_path(key: str, cfg: dict[str, Any] | None = None) -> Path:
    """Absolute path for a key under `paths:` (relative values are anchored at the repository root)."""
    cfg = cfg or load_config()
    try:
        rel = cfg["paths"][key]
    except KeyError as exc:
        raise ConfigError(f"unknown path key {key!r}; known: {sorted(cfg['paths'])}") from exc
    p = Path(rel)
    return p if p.is_absolute() else ROOT / p
