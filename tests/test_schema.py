import pytest

from common.schema import (
    Citation,
    DocHealth,
    DocStatutes,
    GoldWindow,
    Hit,
    Judgment,
    Qrel,
    Query,
    QueryStatutes,
    Result,
    SchemaError,
    StatuteMapRow,
    StatuteRef,
)


def judgment(**over):
    base = dict(
        doc_id="J1",
        title="A v. B",
        date="2019-03-04",
        bench_size=3,
        judges=["X", "Y", "Z"],
        reporter_citations=["(2019) 4 SCC 1"],
        zones={"holding": "..."},
        text="text",
    )
    base.update(over)
    return base


def test_judgment_round_trip():
    j = Judgment.from_dict(judgment())
    assert Judgment.from_dict(j.to_dict()) == j


@pytest.mark.parametrize(
    "over",
    [
        {"date": "04/03/2019"},
        {"bench_size": 0},
        {"zones": {"preamble": "x"}},
        {"doc_id": ""},
    ],
)
def test_judgment_rejects_bad_fields(over):
    with pytest.raises(SchemaError):
        Judgment.from_dict(judgment(**over))


def test_judgment_allows_unknown_bench_size():
    assert Judgment.from_dict(judgment(bench_size=None)).bench_size is None


def test_unknown_field_is_rejected():
    with pytest.raises(SchemaError, match="unknown field"):
        Hit.from_dict({"doc_id": "a", "rel": 1.0, "extra": 1})


def test_statute_ref_rules():
    assert StatuteRef.from_dict({"act": "UNKNOWN", "section": "302"}).offence_id is None
    with pytest.raises(SchemaError):
        StatuteRef.from_dict({"act": "XYZ", "section": "302"})
    with pytest.raises(SchemaError):
        StatuteRef.from_dict({"act": "IPC", "section": "302", "offence_id": "MURDER"})


def test_doc_statutes_nested_round_trip():
    d = DocStatutes.from_dict({"doc_id": "J1", "refs": [{"act": "IPC", "section": "302", "offence_id": "OFF_MURDER", "count": 4, "zone": "holding"}]})
    assert DocStatutes.from_dict(d.to_dict()) == d


def test_statute_map_row_requires_source_and_valid_relation():
    row = dict(old_act="IPC", old_section="302", new_act="BNS", new_section="103", relation="equivalent", weight=1.0, source="MHA table; PRS brief")
    assert StatuteMapRow.from_dict(row).relation == "equivalent"
    with pytest.raises(SchemaError):
        StatuteMapRow.from_dict({**row, "source": ""})
    with pytest.raises(SchemaError):
        StatuteMapRow.from_dict({**row, "relation": "renamed"})
    with pytest.raises(SchemaError):
        StatuteMapRow.from_dict({**row, "weight": 1.5})


def test_query_statutes_offence_ids_are_unique_and_sorted():
    qs = QueryStatutes(
        query="q",
        offence_date="2025-01-01",
        governing_act="BNS",
        refs=[
            StatuteRef(act="BNS", section="103", offence_id="OFF_MURDER"),
            StatuteRef(act="BNS", section="3(5)", offence_id="OFF_COMMON_INTENTION"),
            StatuteRef(act="IPC", section="302", offence_id="OFF_MURDER"),
            StatuteRef(act="UNKNOWN", section="999"),
        ],
    )
    assert qs.offence_ids == ["OFF_COMMON_INTENTION", "OFF_MURDER"]
    assert QueryStatutes.from_dict(qs.to_dict()) == qs


def test_citation_and_doc_health_and_gold():
    c = dict(citing_doc="A", cited_doc=None, cited_raw="(2018) 1 SCC 1", window="w", is_appeal_history=False,
             label="overruled", confidence=0.9, citing_bench=5, cited_bench=3, valid_negative=True)
    assert Citation.from_dict(c).cited_doc is None
    with pytest.raises(SchemaError):
        Citation.from_dict({**c, "label": "reversed"})
    with pytest.raises(SchemaError):
        Citation.from_dict({**c, "confidence": 1.2})
    dh = DocHealth.from_dict({"doc_id": "A", "health": 0.1, "authority": 0.4,
                              "evidence": [{"citing_doc": "B", "label": "overruled", "sentence": "s"}]})
    assert dh.health == 0.1
    with pytest.raises(SchemaError):
        DocHealth.from_dict({"doc_id": "A", "health": 1.1, "authority": 0.4})
    with pytest.raises(SchemaError):
        DocHealth.from_dict({"doc_id": "A", "health": 1.0, "authority": 0.4, "evidence": [{"citing_doc": "B"}]})
    with pytest.raises(SchemaError):
        GoldWindow.from_dict({"window_id": "w1", "window": "x", "gold_label": "bad law", "labeller": "L1"})


def test_query_and_qrel():
    assert Query.from_dict({"qid": "q1", "text": "murder", "offence_date": None, "split": "dev", "type": "A"}).split == "dev"
    with pytest.raises(SchemaError):
        Query.from_dict({"qid": "q1", "text": "murder", "offence_date": "2025-13-01", "split": "dev", "type": "A"})
    with pytest.raises(SchemaError):
        Query.from_dict({"qid": "q1", "text": "murder", "offence_date": None, "split": "validation", "type": "A"})
    with pytest.raises(SchemaError):
        Qrel.from_dict({"qid": "q1", "doc_id": "d", "grade": 3})


def test_hit_requires_numeric_rel():
    with pytest.raises(SchemaError):
        Hit.from_dict({"doc_id": "a", "rel": "high"})
    with pytest.raises(SchemaError):
        Hit.from_dict({"doc_id": "a", "rel": 1.0, "zone_scores": {"preamble": 0.1}})


def test_result_validates_unit_range_and_explanation():
    base = dict(doc_id="a", final=0.5, rel=0.5, cont=0.5, health=0.5, auth=0.5, explanation="why")
    assert Result.from_dict(base).final == 0.5
    with pytest.raises(SchemaError):
        Result.from_dict({**base, "final": 1.2})
    with pytest.raises(SchemaError):
        Result.from_dict({**base, "explanation": ""})
