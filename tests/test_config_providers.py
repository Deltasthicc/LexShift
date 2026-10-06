import copy

import pytest

from common import contracts
from common.config import ConfigError, load_config, resolve_path, validate_config
from common.io import read_jsonl, write_jsonl
from common.providers import ENV_VAR, SIGNAL_GROUP, load_providers, stub_flags


def test_shipped_config_is_valid_and_paths_resolve():
    cfg = load_config()
    validate_config(cfg)
    assert resolve_path("judgments").name == "judgments.jsonl"
    with pytest.raises(ConfigError):
        resolve_path("nope")


def test_config_rejects_missing_section_and_bad_stub_values():
    cfg = copy.deepcopy(load_config())
    del cfg["ranking"]
    with pytest.raises(ConfigError, match="ranking"):
        validate_config(cfg)
    cfg = copy.deepcopy(load_config())
    cfg["stubs"]["search"] = "yes"
    with pytest.raises(ConfigError, match="true or false"):
        validate_config(cfg)
    cfg = copy.deepcopy(load_config())
    cfg["stubs"]["extra"] = True
    with pytest.raises(ConfigError):
        validate_config(cfg)


def test_relation_weights_in_config_are_the_guide_starting_weights():
    w = load_config()["m2_statute"]["relation_weights"]
    assert w == {"equivalent": 1.0, "modified_punishment": 0.9, "modified_elements": 0.5, "split": 0.7, "merged": 0.7, "omitted": 0.1, "new": 0.0}
    assert load_config()["m3_treatment"]["health_values"] == {"overruled": 0.1, "doubted": 0.6, "default": 1.0}


@pytest.mark.parametrize(
    "value,expected_stubbed",
    [
        ("all", {"search", "statute", "health", "authority"}),
        ("none", set()),
        ("search, health", {"search", "health"}),
    ],
)
def test_env_override_of_stub_switches(monkeypatch, value, expected_stubbed):
    monkeypatch.setenv(ENV_VAR, value)
    flags = stub_flags()
    assert {g for g, on in flags.items() if on} == expected_stubbed


def test_env_override_rejects_unknown_group(monkeypatch):
    monkeypatch.setenv(ENV_VAR, "search,rank")
    with pytest.raises(ConfigError):
        stub_flags()


def test_real_providers_are_not_silently_replaced_by_stubs(monkeypatch):
    # With every switch off, the providers are the real modules' functions, never the stubs. Fake module objects stand in for
    # M1-M3 so the test neither loads their indexes nor depends on how far each module has got.
    import sys
    import types

    marker = lambda *a, **k: "real"  # noqa: E731
    fakes = {
        "m1_index": {"search": marker},
        "m2_statute": {"parse_query": marker, "continuity": marker},
        "m3_treatment": {"health": marker, "authority": marker},
    }
    for name, attrs in fakes.items():
        monkeypatch.setitem(sys.modules, name, types.SimpleNamespace(**attrs))
    monkeypatch.setenv(ENV_VAR, "none")
    p = load_providers()
    assert p.stubbed == frozenset()
    assert all(fn is marker for fn in (p.search, p.parse_query, p.continuity, p.health, p.authority))
    import stubs

    assert p.search is not stubs.search and p.health is not stubs.health


def test_stub_providers_report_what_is_stubbed():
    p = load_providers(flags={"search": True, "statute": False, "health": True, "authority": True})
    assert p.stubbed_signals() == ["rel", "health", "auth"]
    assert p.stubbed_signals(["cont", "rel"]) == ["rel"]
    assert set(SIGNAL_GROUP.values()) == {"search", "statute", "health", "authority"}


def test_stubs_honour_every_contract():
    p = load_providers(flags={g: True for g in ("search", "statute", "health", "authority")})
    hits = p.search("anything", k=100)
    assert contracts.check_hits(hits, 100) == []
    assert len(p.search("anything", k=3)) == 3
    qs = p.parse_query("BNS 103", "2025-01-10")
    assert contracts.check_query_statutes(qs) == []
    for h in hits:
        assert contracts.check_continuity(p.continuity(qs, h.doc_id)) == []
        assert contracts.check_health(p.health(h.doc_id, None)) == []
        assert contracts.check_authority(p.authority(h.doc_id)) == []


def test_stub_data_is_visibly_fake():
    p = load_providers(flags={g: True for g in ("search", "statute", "health", "authority")})
    assert all(h.doc_id.startswith("STUB-") for h in p.search("x"))
    _score, evidence = p.health("STUB-002", None)
    assert evidence and "STUB" in evidence[0]["sentence"]
    assert "STUB" in p.continuity(p.parse_query("x"), "STUB-001")[1]


def test_contract_checkers_catch_violations():
    from common.schema import Hit

    assert contracts.check_hits([Hit("a", 1.0), Hit("b", 2.0)], 10)  # not sorted by rel
    assert contracts.check_hits([Hit("a", 1.0), Hit("a", 0.5)], 10)  # duplicate id
    assert contracts.check_hits([Hit("a", -1.0)], 10)  # negative rel
    assert contracts.check_hits("nope", 10)
    assert contracts.check_continuity((1.5, "why"))
    assert contracts.check_continuity((0.5, ""))
    assert contracts.check_health((0.5, [{"citing_doc": "x", "label": "bad law", "sentence": "s"}]))
    assert contracts.check_authority(float("nan"))


def test_jsonl_round_trip_and_atomic_write(tmp_path):
    path = tmp_path / "sub" / "x.jsonl"
    assert write_jsonl(path, [{"a": 1, "t": "नमस्ते"}, {"a": 2}]) == 2
    assert list(read_jsonl(path)) == [{"a": 1, "t": "नमस्ते"}, {"a": 2}]
    assert b"\r\n" not in path.read_bytes()
    assert not list(path.parent.glob("*.tmp"))


def test_jsonl_error_names_the_line(tmp_path):
    path = tmp_path / "bad.jsonl"
    path.write_text('{"a": 1}\n{oops}\n', encoding="utf-8")
    with pytest.raises(ValueError, match=r"bad.jsonl:2"):
        list(read_jsonl(path))
