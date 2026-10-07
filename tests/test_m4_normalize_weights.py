import math

import pytest
import yaml

from common.config import load_config
from m4_rank.normalize import NormalizationError, identity, minmax, normalize_column
from m4_rank.weights import (
    WeightsError,
    active_signals,
    canonical_config,
    load_weights,
    normalise_weights,
    weights_source,
)


# ---------------------------------------------------------------- normalisation
def test_minmax_scales_to_unit_interval():
    assert minmax([1.0, 2.0, 3.0]) == [0.0, 0.5, 1.0]
    assert minmax([-1.0, 1.0]) == [0.0, 1.0]
    assert minmax([10.0, 5.0, 0.0]) == [1.0, 0.5, 0.0]


def test_minmax_without_spread_cannot_discriminate():
    assert minmax([5.0, 5.0, 5.0]) == [1.0, 1.0, 1.0]
    assert minmax([0.0, 0.0]) == [0.0, 0.0]
    assert minmax([2.5]) == [1.0]
    assert minmax([]) == []


def test_identity_keeps_calibrated_values_and_clips_rounding_noise():
    assert identity([0.0, 0.6, 1.0]) == [0.0, 0.6, 1.0]
    assert identity([1.0 + 1e-12, -1e-12]) == [1.0, 0.0]


@pytest.mark.parametrize("bad", [1.5, -0.2])
def test_identity_rejects_values_outside_unit_interval(bad):
    with pytest.raises(NormalizationError):
        identity([0.5, bad])


def test_normalize_column_rejects_non_finite_and_unknown_strategy():
    with pytest.raises(NormalizationError):
        normalize_column([1.0, math.nan], "minmax")
    with pytest.raises(NormalizationError):
        normalize_column([1.0, math.inf], "identity")
    with pytest.raises(NormalizationError):
        normalize_column([1.0], "zscore")


# -------------------------------------------------------------------- weights
def test_normalise_weights_sums_to_one_and_fills_unused_signals():
    w = normalise_weights({"rel": 3, "cont": 1})
    assert w == {"rel": 0.75, "cont": 0.25, "health": 0.0, "auth": 0.0}
    assert math.isclose(sum(w.values()), 1.0)


@pytest.mark.parametrize(
    "raw",
    [{"rel": -1.0}, {"recency": 1.0}, {}, {"rel": 0.0}, {"rel": math.nan}, {"rel": math.inf}],
)
def test_normalise_weights_rejects_invalid_vectors(raw):
    with pytest.raises(WeightsError):
        normalise_weights(raw)


def test_active_signals_in_canonical_order():
    assert active_signals({"auth": 0.1, "rel": 0.5, "health": 0.0, "cont": 0.4}) == ("rel", "cont", "auth")


def test_signals_used_and_format_weights():
    from m4_rank.weights import format_weights, signals_used

    w = {n: load_weights(n) for n in ("b0", "b1", "full")}
    assert signals_used(w, ["b0"]) == ("rel",)
    assert signals_used(w, ["b0", "b1"]) == ("rel", "cont")
    assert signals_used(w, ["full", "b0"]) == ("rel", "cont", "health", "auth")
    assert signals_used(w, []) == ()
    assert format_weights(w["full"]) == "0.50/0.20/0.20/0.10" and format_weights(w["b0"]) == "1.00/0.00/0.00/0.00"


def test_canonical_config_resolves_alias_and_rejects_unknown():
    assert canonical_config("B2") == "full"
    assert canonical_config(" b0 ") == "b0"
    with pytest.raises(WeightsError, match="unknown config"):
        canonical_config("b9")


def test_shipped_starting_weights():
    cfg = load_config()
    assert load_weights("b0", cfg) == {"rel": 1.0, "cont": 0.0, "health": 0.0, "auth": 0.0}
    assert active_signals(load_weights("b1", cfg)) == ("rel", "cont")
    assert active_signals(load_weights("full", cfg)) == ("rel", "cont", "health", "auth")
    assert weights_source("full", cfg) == "starting weights (untuned placeholders)"


def test_tuned_weights_overlay_only_when_enabled(tmp_path, write_config, monkeypatch):
    tuned = tmp_path / "tuned.yaml"
    tuned.write_text(yaml.safe_dump({"full": {"rel": 0.4, "cont": 0.1, "health": 0.4, "auth": 0.1}}), encoding="utf-8")
    path = write_config(tmp_path / "config.yaml", {"ranking": {"use_tuned": True, "tuned_file": str(tuned)}})
    monkeypatch.setenv("LEXSHIFT_CONFIG", str(path))
    cfg = load_config()
    assert load_weights("full", cfg)["health"] == pytest.approx(0.4)
    assert weights_source("full", cfg) == "tuned on dev"
    # a config with no tuned entry keeps its starting weights
    assert weights_source("b1", cfg) == "starting weights (untuned placeholders)"

    path = write_config(tmp_path / "config_off.yaml", {"ranking": {"use_tuned": False, "tuned_file": str(tuned)}})
    monkeypatch.setenv("LEXSHIFT_CONFIG", str(path))
    assert load_weights("full", load_config())["health"] == pytest.approx(0.2)


def mutated(section, key, value):
    """A copy of the config whose ranking/evaluation section has one value replaced (None deletes the key)."""
    import copy

    cfg = copy.deepcopy(load_config())
    if value is None:
        del cfg[section][key]
    else:
        cfg[section][key] = value
    return cfg


@pytest.mark.parametrize(
    "section,key,value,message",
    [
        ("ranking", "normalize", {"rel": "minmax", "cont": "identity", "health": "identity"}, "exactly"),
        ("ranking", "normalize", {"rel": "minmaxx", "cont": "identity", "health": "identity", "auth": "minmax"}, "must be one of"),
        ("ranking", "configs", {"b0": {"rel": 1.0}, "b1": {"rel": 1.0, "cont": 1.0}}, "full is missing"),
        ("ranking", "configs", {"b0": {"rel": 1.0}, "b1": {"rel": -1.0}, "full": {"rel": 1.0}}, ">= 0"),
        ("ranking", "configs", {"b0": {"rel": 1.0}, "b1": {"rel": 1.0, "cont": 1.0}, "full": {"cont": 1.0, "health": 1.0}},
         "needs a positive rel weight"),
        ("ranking", "candidates", 5, "candidates must be >= evaluation.depth"),
        ("ranking", "max_evidence", None, "max_evidence is missing"),
        ("evaluation", "depth", 9, "depth must be >= 10"),
        ("evaluation", "relevant_threshold", 3, "relevant_threshold"),
        ("evaluation", "gain", "log", "gain"),
        ("evaluation", "seed", None, "seed is missing"),
    ],
)
def test_ranking_and_evaluation_config_errors_are_clear(section, key, value, message):
    from m4_rank.weights import validate_ranking_config

    cfg = mutated(section, key, value)
    with pytest.raises(WeightsError, match=message):
        validate_ranking_config(cfg)
    with pytest.raises(WeightsError):
        load_weights("full", cfg)  # every ranking call validates first


def test_shipped_ranking_and_evaluation_config_is_valid():
    from m4_rank.weights import validate_ranking_config

    validate_ranking_config(load_config())


def test_missing_tuned_file_is_not_an_error(tmp_path, write_config, monkeypatch):
    path = write_config(tmp_path / "config.yaml", {"ranking": {"use_tuned": True, "tuned_file": str(tmp_path / "none.yaml")}})
    monkeypatch.setenv("LEXSHIFT_CONFIG", str(path))
    assert weights_source("full", load_config()) == "starting weights (untuned placeholders)"
