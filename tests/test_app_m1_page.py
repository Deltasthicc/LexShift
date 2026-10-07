"""The Index page's views of M1: checked on a three-judgment corpus small enough to count by hand, through the service and over HTTP.

The corpus (zones headnote / facts / arguments / holding):
  A  headnote "murder intention"          holding "murder murder common intention"
  B  headnote "theft"                     holding "theft of property"
  C  facts "common intention shared"      holding "intention"
M1's own code builds the index and answers the queries; the explorer only reads it.
"""

from __future__ import annotations

import http.client
import json
import threading

import pytest

pytest.importorskip("nltk")
try:
    from m1_index.index import InvertedIndex
    from m1_index.searcher import RankedSearchEngine
except (LookupError, RuntimeError, ImportError) as exc:  # NLTK stop words missing, for example
    pytest.skip(f"M1 cannot be imported here: {exc}", allow_module_level=True)

from app.m1_view import ExplorerError, IndexExplorer
from app.server import make_server
from app.service import Service, ServiceError
from common.schema import Judgment

DOCS = {
    "A": {"headnote": "murder intention", "holding": "murder murder common intention"},
    "B": {"headnote": "theft", "holding": "theft of property"},
    "C": {"facts": "common intention shared", "holding": "intention"},
}


@pytest.fixture(scope="module")
def corpus(tmp_path_factory):
    folder = tmp_path_factory.mktemp("m1corpus")
    judgments = [Judgment(doc_id=f"2025_1_{i}_{i + 1}_EN", title=f"Case {name}", date="2025-01-0%d" % (i + 1), bench_size=2 if name != "C" else None,
                          judges=[], reporter_citations=[], zones=zones, text=" ".join(zones.values()))
                 for i, (name, zones) in enumerate(DOCS.items())]
    InvertedIndex.build(judgments).save(folder)
    path = folder / "judgments.jsonl"
    path.write_text("\n".join(json.dumps(j.to_dict()) for j in judgments) + "\n", encoding="utf-8")
    return folder, path


@pytest.fixture
def explorer(corpus):
    folder, path = corpus
    return IndexExplorer(engine_factory=lambda: RankedSearchEngine(index_dir=folder), judgments=path)


def test_the_overview_counts_the_index_that_is_on_disk(explorer):
    o = explorer.overview()
    assert o["docs"] == 3 and o["years"] == {"2025": 3} and o["bench"] == {"2": 2, "unknown": 1}
    assert o["tokens"] == o["positions"] == sum(o["zone_tokens"].values())
    assert o["zone_tokens"]["headnote"] == 3 and o["zone_tokens"]["holding"] == 4 + 2 + 1  # "of" is a stop word: 4 + (theft, properti) + 1
    assert o["bm25"] == {"k1": 1.2, "b": 0.75} and o["zone_weights"]["headnote"] == 3.0
    assert o["capabilities"]["lnc_ltc"] == "implemented"  # probed from m1_index.scoring, not asserted by the page
    assert {"term": "intent", "df": 2} in o["top_terms"] and {"term": "theft", "df": 1} in o["top_terms"]


def test_the_text_walk_through_gives_exactly_m1s_tokens(explorer):
    a = explorer.analyze("Sections 302 and 120-B of the IPC [2025] 1 S.C.R. 1; murdered")
    fates = {s["raw"]: s["fate"] for s in a["steps"]}
    assert fates["and"] == "stopword" and fates["the"] == "stopword" and fates["302"] == "kept" and fates["ipc"] == "kept"
    assert fates["sections"] == "stemmed" and fates["murdered"] == "stemmed" and fates["scr"] == "kept"
    assert a["consistent"] is True and "murder" in a["tokens"] and "section" in a["tokens"] and "and" not in a["tokens"]


def test_a_term_lookup_returns_the_postings_with_zone_counts_and_idf(explorer):
    t = explorer.term("Murders")  # normalised the way the index was built
    assert t["term"] == "murder" and t["df"] == 1 and t["docs"] == 3
    (row,) = t["postings"]
    assert row["title"] == "Case A" and row["tf"] == 3 and row["zones"] == {"headnote": 1, "holding": 2} and row["n_positions"] == 3
    assert t["idf"] == pytest.approx(0.9808, abs=1e-4)  # ln(1 + (N - df + 0.5) / (df + 0.5)) = ln(1 + 2.5 / 1.5)
    assert explorer.term("zzzzqq")["df"] == 0


def test_a_boolean_query_is_parsed_and_its_hits_explain_their_score(explorer):
    q = explorer.query("murder AND intention", k=5)
    assert q["mode"] == "boolean" and q["tree"]["type"] == "and" and q["candidates"] == 1 and q["docs"] == 3
    (hit,) = q["hits"]
    assert hit["title"] == "Case A"
    parts = sum(z["part"] for z in hit["zones"].values())
    assert parts == pytest.approx(hit["rel"], abs=1e-3)  # rel is the weighted sum of the zone scores
    w = q["worked"]
    assert w["doc_id"] == hit["doc_id"] and w["term"] == "murder" and w["zone"] in ("headnote", "holding")
    expected = w["idf"] * (w["tf"] * (w["k1"] + 1)) / (w["tf"] + w["k1"] * (1 - w["b"] + w["b"] * w["dl"] / w["avgdl"]))
    assert w["bm25"] == pytest.approx(expected, abs=1e-3)  # the page's arithmetic is the formula, with the real numbers in it


def test_plain_text_falls_back_to_a_bag_of_words_like_search_does(explorer):
    q = explorer.query("theft of property section 9", k=3)
    assert q["mode"] == "plain" and q["tree"] is None and "theft" in q["terms"] and q["hits"][0]["title"] == "Case B"


def test_the_phrase_proximity_and_not_trees_are_drawn(explorer):
    assert explorer.query('"common intention"')["tree"] == {"type": "phrase", "terms": ["common", "intent"]}
    prox = explorer.query("murder /5 intention")["tree"]
    assert prox["type"] == "proximity" and prox["op"] == "/5"
    assert explorer.query("intention AND NOT theft")["tree"]["right"]["type"] == "not"


def test_the_brute_force_scan_agrees_with_the_index_and_says_what_it_cannot_check(explorer):
    for q, n in (("murder AND intention", 1), ('"common intention"', 2), ("theft OR murder", 2), ("intention AND NOT murder", 1)):
        v = explorer.verify(q)
        assert v["checked"] and v["agree"] and v["engine"] == v["scan"] == n, q
    assert explorer.verify("murder /5 intention")["checked"] is False
    assert explorer.verify("theft of property")["checked"] is False  # plain text has no Boolean structure


def test_the_benchmark_measures_real_runs(explorer):
    b = explorer.bench()
    assert [r["label"] for r in b["rows"]] == ["one term", "plain text", "Boolean", "phrase", "proximity"]
    assert all(0 <= r["min_ms"] <= r["median_ms"] <= r["p95_ms"] for r in b["rows"]) and b["runs"] == 15


@pytest.mark.parametrize("bad", ["", "   ", None, 5])
def test_empty_or_non_text_input_is_a_clear_error(explorer, bad):
    with pytest.raises(ExplorerError) as err:
        explorer.analyze(bad)
    assert err.value.status == 400


def test_a_missing_index_is_one_clear_message_with_the_build_command(tmp_path):
    def missing():
        return RankedSearchEngine(index_dir=tmp_path / "nothing")

    with pytest.raises(ExplorerError) as err:
        IndexExplorer(engine_factory=missing).overview()
    assert err.value.status == 503 and "python -m m1_index.index build" in err.value.message


# ------------------------------------------------------------------------------------------------------------------ over HTTP
@pytest.fixture
def live(corpus):
    folder, path = corpus
    service = Service(providers=None, explorer=IndexExplorer(engine_factory=lambda: RankedSearchEngine(index_dir=folder), judgments=path))
    server = make_server("127.0.0.1", 0, service)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    host, port = server.server_address[:2]

    def get(target):
        conn = http.client.HTTPConnection(host, port, timeout=20)
        conn.request("GET", target, headers={"Host": f"127.0.0.1:{port}"})
        resp = conn.getresponse()
        body = json.loads(resp.read().decode("utf-8"))
        conn.close()
        return resp.status, body

    yield get
    server.shutdown()
    server.server_close()


def test_the_endpoints_answer_as_json(live):
    status, o = live("/api/m1/overview")
    assert status == 200 and o["docs"] == 3
    assert live("/api/m1/analyze?text=the+murder")[1]["tokens"] == ["murder"]
    assert live("/api/m1/term?t=theft")[1]["df"] == 1
    assert live("/api/m1/query?q=murder+AND+intention&k=3")[1]["candidates"] == 1
    assert live("/api/m1/verify?q=%22common+intention%22")[1]["agree"] is True
    assert live("/api/m1/bench")[0] == 200


def test_the_endpoints_report_bad_input_as_json_errors(live):
    status, body = live("/api/m1/analyze")
    assert status == 400 and body["error"]["kind"] == "bad_input"
    assert live("/api/m1/term?t=%20")[0] == 400


def test_the_service_turns_explorer_errors_into_service_errors(tmp_path):
    def missing():
        return RankedSearchEngine(index_dir=tmp_path / "nothing")

    service = Service(providers=None, explorer=IndexExplorer(engine_factory=missing))
    with pytest.raises(ServiceError) as err:
        service.m1_overview()
    assert err.value.status == 503 and err.value.kind == "index_missing"
