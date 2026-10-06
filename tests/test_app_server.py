"""The web interface: the service behind it, the HTTP layer, the judging workbench and the shipped page.

Fake providers from `make_providers` stand in for M1 to M3 so the numbers are hand-checkable; the HTTP tests start the real
server on a free port and talk to it with http.client, exactly as a browser would.
"""

from __future__ import annotations

import http.client
import json
import re
import threading
from pathlib import Path

import pytest

from app.server import WEB, make_server
from app.service import GRADES, JUDGES, Service, ServiceError
from eval.loaders import read_table
from eval.make_qrels import read_judge_file

SHEET_COLUMNS = ["qid", "query", "type", "offence_date", "doc_id", "title", "date", "bench_size", "excerpt", "grade", "note"]


def _sheet_rows():
    rows = []
    for qid, query in (("dev1", "murder"), ("dev2", "common intention")):
        for doc in ("A", "B", "C"):
            rows.append({"qid": qid, "query": query, "type": "A", "offence_date": "2025-01-10", "doc_id": f"{doc}-{qid}",
                         "title": f"Case {doc}", "date": "2019-03-04", "bench_size": "2",
                         "excerpt": f"excerpt of {doc}", "grade": "", "note": ""})
    return rows


@pytest.fixture
def service(eval_workspace):
    return Service(providers=eval_workspace.providers)


@pytest.fixture
def round_dir(eval_workspace):
    d = eval_workspace.judging / "round1"
    d.mkdir(parents=True)
    from eval.loaders import write_table

    write_table(d / "sheet_template.csv", SHEET_COLUMNS, _sheet_rows())
    (d / "provenance.csv").write_text("qid,doc_id,b0,b1,full\ndev1,A-dev1,1,2,3\n", encoding="utf-8")
    return d


@pytest.fixture
def live(service):
    server = make_server("127.0.0.1", 0, service)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    host, port = server.server_address[:2]

    class Client:
        def request(self, method, path, body=None, headers=None):
            conn = http.client.HTTPConnection(host, port, timeout=10)
            h = dict(headers or {})
            data = None
            if body is not None:
                data = body if isinstance(body, (bytes, str)) else json.dumps(body)
                h.setdefault("Content-Type", "application/json")
            conn.request(method, path, body=data, headers=h)
            resp = conn.getresponse()
            raw = resp.read()
            conn.close()
            return resp.status, resp, raw

        def json(self, method, path, body=None, headers=None):
            status, resp, raw = self.request(method, path, body, headers)
            return status, json.loads(raw)

    yield Client()
    server.shutdown()
    server.server_close()


# ----------------------------------------------------------------------------------------------- service
def test_status_reports_which_signals_are_stubs(eval_workspace):
    s = Service(providers=eval_workspace.providers)
    st = s.status()
    assert st["stub_mode"] is False and st["stubbed"] == []
    assert set(st["providers"]) == {"search", "statute", "health", "authority"}
    assert set(st["configs"]) == {"b0", "b1", "full"}
    assert abs(sum(st["configs"]["full"]["weights"].values()) - 1.0) < 1e-9
    stubbed = Service(providers=eval_workspace.providers.__class__(
        *[getattr(eval_workspace.providers, f) for f in ("search", "parse_query", "continuity", "health", "authority")],
        frozenset({"health"}),
    ))
    assert stubbed.status()["stub_mode"] is True and stubbed.status()["stubbed"] == ["health"]


def test_search_returns_the_breakdown_and_flags_stubs(eval_workspace, make_providers):
    s = Service(providers=make_providers(stubbed=("health",)))
    out = s.search("murder", "2025-01-10", 3, "full")
    assert out["config"] == "full" and out["k"] == 3 and len(out["results"]) == 3
    assert out["stubbed"] == ["health"]
    top = out["results"][0]
    assert top["rank"] == 1 and top["doc_id"] in "ABCD"
    assert abs(sum(top["contributions"].values()) - top["final"]) < 1e-9
    assert set(top["normalised"]) == {"rel", "cont", "health", "auth"}
    assert top["parts"] and "rel" in top["parts"][0]
    assert out["statutes"]["used"] is True
    assert "not legal advice" in out["note"]


def test_b0_does_not_use_the_statute_module(eval_workspace, make_providers):
    providers = make_providers()
    s = Service(providers=providers)
    out = s.search("murder", None, 4, "b0")
    assert out["signals_used"] == ["rel"] and out["statutes"] == {"used": False}
    assert providers.calls["parse_query"] == providers.calls["continuity"] == providers.calls["health"] == 0


def test_evidence_is_carried_in_full_and_cleaned(eval_workspace, make_providers, scenario):
    long = "In X this Court overruled Y. " * 40 + "\x08tail\x07"
    scenario["A"]["evidence"] = [{"citing_doc": "Z", "label": "overruled", "sentence": long, "confidence": 0.9, "citing_bench": 5}]
    out = Service(providers=make_providers(scenario)).search("murder", None, 4, "full")
    ev = next(r for r in out["results"] if r["doc_id"] == "A")["evidence"][0]
    assert ev["sentence"].endswith("tail") and "\x08" not in ev["sentence"] and len(ev["sentence"]) > 1000
    assert ev["confidence"] == 0.9 and ev["citing_bench"] == 5


@pytest.mark.parametrize("args, fragment", [
    (("", None, 10, "full"), "Enter a query"),
    (("murder", "10-01-2025", 10, "full"), "ISO date"),
    (("murder", None, 10, "nope"), "unknown config"),
    (("murder", None, "ten", "full"), "whole number"),
    (("x" * 600, None, 10, "full"), "longer than"),
])
def test_search_rejects_bad_input_with_a_400(service, args, fragment):
    with pytest.raises(ServiceError) as exc:
        service.search(*args)
    assert exc.value.status == 400 and fragment in exc.value.message


def test_k_is_clamped(service):
    assert service.search("murder", None, 9999, "b0")["k"] == 50
    assert service.search("murder", None, 0, "b0")["k"] == 1


def test_a_missing_artefact_is_a_503_not_a_traceback(eval_workspace, make_providers):
    providers = make_providers()

    def broken(doc_id, offence_ids=None):
        raise KeyError(doc_id)

    object.__setattr__(providers, "health", broken)
    with pytest.raises(ServiceError) as exc:
        Service(providers=providers).search("murder", None, 3, "full")
    assert exc.value.status == 503 and exc.value.kind == "artefact" and "health(" in exc.value.message


def test_compare_gives_every_config_and_every_documents_rank_under_each(service):
    out = service.compare("murder", "2025-01-10", 4)
    assert list(out["configs"]) == ["b0", "b1", "full"]
    for name, block in out["configs"].items():
        assert [r["rank"] for r in block["results"]] == [1, 2, 3, 4]
        for r in block["results"]:
            assert set(r["ranks"]) == {"b0", "b1", "full"}
            assert r["ranks"][name] == r["rank"]
    # in the fixture A is the best text match but has health 0.1: BM25 puts it first, the full system does not
    b0, full = out["configs"]["b0"]["results"], out["configs"]["full"]["results"]
    assert b0[0]["doc_id"] == "A" and full[0]["doc_id"] != "A"
    a_in_full = next(r for r in b0 if r["doc_id"] == "A")["ranks"]["full"]
    assert a_in_full > 1


def test_documents_come_from_the_corpus_and_are_cleaned(eval_workspace, service):
    rec = {"doc_id": "D1", "title": "Alpha v. State", "date": "2019-03-04", "bench_size": 3, "judges": ["J. One"],
           "reporter_citations": ["(2019) 1 SCC 1"], "zones": {"headnote": "h"}, "text": "Line one\x08\n" + "word " * 400}
    eval_workspace.judgments_path.write_text(json.dumps(rec) + "\n" + json.dumps({**rec, "doc_id": "D2", "title": "Beta"}) + "\n",
                                             encoding="utf-8")
    doc = service.document("D2", 50)
    assert doc["title"] == "Beta" and doc["truncated"] is True and len(doc["text"]) == 1000  # the smallest page is 1,000 characters
    assert "\x08" not in service.document("D1")["text"]
    with pytest.raises(ServiceError) as exc:
        service.document("NOPE")
    assert exc.value.status == 404
    with pytest.raises(ServiceError) as exc:
        service.document("STUB-001")
    assert "stand-in" in exc.value.message


def test_documents_without_a_corpus_are_a_clear_404(service):
    with pytest.raises(ServiceError) as exc:
        service.document("A")
    assert exc.value.status == 404 and exc.value.kind == "no_corpus"


def test_results_carry_titles_when_the_corpus_has_them(eval_workspace, service):
    eval_workspace.judgments_path.write_text(
        "".join(json.dumps({"doc_id": d, "title": f"Title {d}", "date": "2019-03-04", "bench_size": 2, "text": "t"}) + "\n" for d in "ABCD"),
        encoding="utf-8")
    top = service.search("murder", None, 2, "b0")["results"][0]
    assert top["title"] == f"Title {top['doc_id']}" and "2-judge bench" in top["label"]


def test_examples_are_marked_as_suggestions(service):
    ex = service.examples()
    assert ex["suggested"] is True and len(ex["queries"]) == 30 and {"qid", "text", "type"} <= set(ex["queries"][0])


# ----------------------------------------------------------------------------------------------- evaluation
def test_evaluation_with_nothing_built_is_honest(service):
    out = service.evaluation()
    assert out["runs"] == [] and out["rounds"] == []
    assert out["data"]["queries"]["total"] == 4  # the workspace fixture's four placeholder queries; no qrels or gold list exist
    assert out["data"]["qrels"]["rows"] == 0 and out["data"]["gold_overrulings"] == 0
    assert out["data"]["checks"]["warnings"]  # the plan wants 30 queries


def test_evaluation_reads_hand_made_files_and_flags_stub_runs(eval_workspace, service):
    eval_workspace.write_qrels([("dev1", "A", 2), ("dev1", "B", 0), ("test1", "C", 1)])
    eval_workspace.write_gold(["B"])
    eval_workspace.results.mkdir()
    header = "config,n_queries,w_rel,w_cont,w_health,w_auth,P@5,P@10,R@10,MAP,nDCG@10,harmful@10,judged@10\n"
    (eval_workspace.results / "ablation_test.csv").write_text(header + "b0,2,1,0,0,0,0.4,0.3,0.5,0.45,0.55,0.1,0.9\n", encoding="utf-8")
    (eval_workspace.results / "stub_ablation_dev.csv").write_text(header + "b0,2,1,0,0,0,0.9,0.9,0.9,0.9,0.9,0,1\n", encoding="utf-8")
    (eval_workspace.results / "per_query_test.csv").write_text(
        "qid,type,config,P@5,P@10,R@10,MAP,nDCG@10,harmful@10,judged@10\ntest1,A,b0,0.4,0.3,0.5,0.4,0.6,0,1\ntest2,A,b0,0.4,0.3,0.5,0.4,0.4,0,1\n",
        encoding="utf-8")
    out = service.evaluation()
    assert out["data"]["queries"]["total"] == 4 and out["data"]["qrels"]["grades"] == {"0": 1, "1": 1, "2": 1}
    assert out["data"]["gold_overrulings"] == 1
    runs = {r["file"]: r for r in out["runs"]}
    assert runs["ablation_test.csv"]["stub"] is False and runs["stub_ablation_dev.csv"]["stub"] is True
    assert runs["ablation_test.csv"]["rows"][0]["nDCG@10"] == 0.55
    assert runs["ablation_test.csv"]["ndcg_by_type"] == {"A": {"b0": 0.5}}


# ----------------------------------------------------------------------------------------------- judging
def test_rounds_are_listed_with_progress(service, round_dir):
    out = service.judge_rounds()
    assert out["rounds"][0]["round"] == "round1" and out["rounds"][0]["rows"] == 6 and out["rounds"][0]["queries"] == 2
    assert out["rounds"][0]["judges"]["judge1"] == {"started": False, "graded": 0}


def test_the_sheet_is_blind(service, round_dir):
    sheet = service.judge_sheet("round1", "judge1")
    text = json.dumps(sheet)
    assert "provenance" not in text and '"b0"' not in text and "rank" not in text
    assert [q["qid"] for q in sheet["queries"]] == ["dev1", "dev2"] and sheet["progress"] == {"graded": 0, "total": 6}
    assert set(sheet["queries"][0]["docs"][0]) == {"doc_id", "title", "date", "bench_size", "excerpt", "grade", "note"}


def test_a_grade_is_saved_to_the_judges_own_file_and_make_qrels_can_read_it(service, round_dir):
    out = service.judge_grade("round1", "judge1", "dev1", "B-dev1", 2, "good law, on the point")
    assert out["saved"] and out["progress"] == {"graded": 1, "total": 6}
    assert not (round_dir / "judge2.csv").exists()
    rows = read_table(round_dir / "judge1.csv")
    assert [r["grade"] for r in rows].count("2") == 1 and list(rows[0]) == SHEET_COLUMNS
    assert next(r for r in rows if r["doc_id"] == "B-dev1")["note"] == "good law, on the point"
    expected = {(r["qid"], r["doc_id"]) for r in read_table(round_dir / "sheet_template.csv")}
    grades, problems = read_judge_file(round_dir / "judge1.csv", expected)
    assert grades == {("dev1", "B-dev1"): 2} and len(problems) == 1 and "5 row(s) have no grade yet" in problems[0]
    assert service.judge_sheet("round1", "judge1")["queries"][0]["docs"][1]["grade"] == 2


def test_each_judge_has_a_separate_file_and_a_grade_can_be_changed_or_cleared(service, round_dir):
    service.judge_grade("round1", "judge1", "dev1", "A-dev1", 1)
    service.judge_grade("round1", "judge2", "dev1", "A-dev1", 0)
    service.judge_grade("round1", "judge1", "dev1", "A-dev1", 2)
    assert service.judge_sheet("round1", "judge1")["queries"][0]["docs"][0]["grade"] == 2
    assert service.judge_sheet("round1", "judge2")["queries"][0]["docs"][0]["grade"] == 0
    cleared = service.judge_grade("round1", "judge1", "dev1", "A-dev1", None)
    assert cleared["grade"] is None and cleared["progress"]["graded"] == 0


def test_notes_that_look_like_formulas_are_neutralised_and_read_back_unchanged(service, round_dir):
    service.judge_grade("round1", "judge1", "dev1", "A-dev1", 0, "=SUM(A1:A9) overruled by Z")
    stored = next(r for r in read_table(round_dir / "judge1.csv") if r["doc_id"] == "A-dev1")["note"]
    assert stored.startswith("'=")
    assert service.judge_sheet("round1", "judge1")["queries"][0]["docs"][0]["note"] == "=SUM(A1:A9) overruled by Z"


@pytest.mark.parametrize("kwargs, status", [
    (dict(round_name="../etc", judge="judge1", qid="dev1", doc_id="A-dev1", grade=1), 400),
    (dict(round_name="nope", judge="judge1", qid="dev1", doc_id="A-dev1", grade=1), 404),
    (dict(round_name="round1", judge="judge3", qid="dev1", doc_id="A-dev1", grade=1), 400),
    (dict(round_name="round1", judge="judge1", qid="dev1", doc_id="ZZZ", grade=1), 404),
    (dict(round_name="round1", judge="judge1", qid="dev1", doc_id="A-dev1", grade=3), 400),
    (dict(round_name="round1", judge="judge1", qid="dev1", doc_id="A-dev1", grade="2"), 400),
    (dict(round_name="round1", judge="judge1", qid="dev1", doc_id="A-dev1", grade=True), 400),
])
def test_judge_grade_validates_everything(service, round_dir, kwargs, status):
    with pytest.raises(ServiceError) as exc:
        service.judge_grade(**kwargs)
    assert exc.value.status == status
    assert not (round_dir / "judge1.csv").exists()


def test_a_judge_file_that_no_longer_matches_the_template_is_not_overwritten(service, round_dir):
    (round_dir / "judge1.csv").write_text(",".join(SHEET_COLUMNS) + "\ndev1,q,A,,ONLY-ROW,t,d,2,e,1,n\n", encoding="utf-8")
    before = (round_dir / "judge1.csv").read_text(encoding="utf-8")
    with pytest.raises(ServiceError) as exc:
        service.judge_grade("round1", "judge1", "dev1", "A-dev1", 1)
    assert exc.value.status == 409 and (round_dir / "judge1.csv").read_text(encoding="utf-8") == before


def test_the_workbench_never_offers_a_grade():
    assert GRADES == (0, 1, 2) and JUDGES == ("judge1", "judge2")
    source = (Path(__file__).resolve().parents[1] / "app" / "service.py").read_text(encoding="utf-8")
    assert "suggest" not in source.split("def judge_rounds")[1].lower()


# ----------------------------------------------------------------------------------------------- HTTP layer
def test_the_page_and_its_assets_are_served(live):
    status, resp, raw = live.request("GET", "/")
    assert status == 200 and b"<title>" in raw and resp.getheader("Content-Type").startswith("text/html")
    assert "default-src 'none'" in resp.getheader("Content-Security-Policy")
    assert resp.getheader("X-Content-Type-Options") == "nosniff"
    status, resp, _ = live.request("GET", "/static/js/main.js")
    assert status == 200 and resp.getheader("Content-Type").startswith("text/javascript")
    status, resp, _ = live.request("GET", "/static/css/styles.css")
    assert status == 200 and resp.getheader("Content-Type").startswith("text/css")


@pytest.mark.parametrize("path", ["/static/../service.py", "/static/%2e%2e/service.py", "/static/..%2fserver.py", "/../README.md",
                                  "/app/service.py", "/static/js", "/static/", "/nothing"])
def test_nothing_outside_the_static_folder_is_served(live, path):
    status, _, raw = live.request("GET", path)
    assert status == 404 and b"class Service" not in raw


def test_search_over_http(live):
    status, body = live.json("GET", "/api/search?q=murder&date=2025-01-10&k=3&config=full")
    assert status == 200 and len(body["results"]) == 3 and body["config"] == "full"
    status, body = live.json("GET", "/api/search?q=")
    assert status == 400 and body["error"]["kind"] == "invalid"
    status, body = live.json("GET", "/api/nothing")
    assert status == 404


def test_a_foreign_host_header_is_refused(live):
    status, body = live.json("GET", "/api/status", headers={"Host": "evil.example"})
    assert status == 403 and body["error"]["kind"] == "host"
    status, _ = live.json("GET", "/api/status", headers={"Host": "localhost:1234"})
    assert status == 200


def test_posts_need_json_the_right_origin_and_a_sane_size(live, round_dir):
    good = {"round": "round1", "judge": "judge1", "qid": "dev1", "doc_id": "A-dev1", "grade": 1}
    status, body = live.json("POST", "/api/judge/grade", good)
    assert status == 200 and body["saved"]
    status, body = live.json("POST", "/api/judge/grade", good, headers={"Origin": "https://evil.example"})
    assert status == 403 and body["error"]["kind"] == "origin"
    status, body = live.json("POST", "/api/judge/grade", json.dumps(good), headers={"Content-Type": "text/plain"})
    assert status == 415
    status, body = live.json("POST", "/api/judge/grade", "not json")
    assert status == 400
    status, body = live.json("POST", "/api/judge/grade", json.dumps([1, 2]))
    assert status == 400
    status, body = live.json("POST", "/api/judge/grade", json.dumps({"note": "x" * 70_000}))
    assert status == 413
    status, body = live.json("POST", "/api/judge/unknown", good)
    assert status == 404
    status, body = live.json("PUT", "/api/judge/grade", good)
    assert status == 405
    status, body = live.json("POST", "/", good)
    assert status == 405


def test_the_server_binds_to_loopback_by_default(service):
    server = make_server(service=service, port=0)
    try:
        assert server.server_address[0] == "127.0.0.1"
    finally:
        server.server_close()


# ----------------------------------------------------------------------------------------------- the shipped page
def _web_files(*suffixes, vendored=False):
    """The page's own files; the vendored libraries (static/vendor) are checked separately, by hash, below."""
    return [p for p in WEB.rglob("*") if p.is_file() and p.suffix in suffixes and (vendored or "vendor" not in p.relative_to(WEB).parts)]


def test_the_page_never_uses_the_banned_wording():
    pattern = re.compile(r"bad[\s-]+law|dead[\s-]+law", re.IGNORECASE)
    offenders = [p.name for p in _web_files(".html", ".js", ".css") if pattern.search(p.read_text(encoding="utf-8"))]
    assert not offenders, f"banned wording in {offenders}: say 'treatment signals' instead"


def test_the_page_loads_nothing_from_the_network_and_has_no_inline_code():
    for path in _web_files(".html", ".js", ".css"):
        text = path.read_text(encoding="utf-8")
        urls = [u for u in re.findall(r"https?://[^\s\"')]+", text) if "www.w3.org" not in u]
        assert not urls, f"{path.name} refers to {urls}"
        assert "@import" not in text and "cdn" not in text.lower()
    html = (WEB / "index.html").read_text(encoding="utf-8")
    assert not re.search(r"<script(?![^>]*\bsrc=)[^>]*>", html), "inline scripts are blocked by the CSP"
    assert "<style" not in html and not re.search(r"\sstyle=", html), "inline styles are blocked by the CSP"
    assert not re.search(r"\son[a-z]+=", html), "inline event handlers are blocked by the CSP"


def test_the_page_states_that_it_is_not_legal_advice_and_marks_stubs():
    html = (WEB / "index.html").read_text(encoding="utf-8").lower()
    assert "not legal advice" in html
    js = " ".join(p.read_text(encoding="utf-8") for p in _web_files(".js")).lower()
    assert "stub" in js


def test_untrusted_text_is_never_inserted_as_html():
    for path in _web_files(".js"):
        text = path.read_text(encoding="utf-8")
        assert "innerHTML" not in text and "outerHTML" not in text and "insertAdjacentHTML" not in text and "document.write" not in text, \
            f"{path.name} would let judgment text become markup"


def test_every_script_parses_when_node_is_available():
    """A syntax slip in a module would blank the whole page, and no Python test would notice."""
    import shutil
    import subprocess

    node = shutil.which("node")
    if not node:
        pytest.skip("node is not installed; the scripts were not parsed")
    for path in _web_files(".js"):
        result = subprocess.run([node, "--check", str(path)], capture_output=True, text=True, timeout=60)
        assert result.returncode == 0, f"{path.name}: {result.stderr.strip()[:300]}"


def test_the_vendored_libraries_are_the_files_the_provenance_note_describes():
    """GSAP and the Outfit and Geist fonts were copied unmodified from their npm packages; the note records each file's SHA-256."""
    import hashlib

    static = WEB / "static"
    note = (static / "vendor" / "README.md").read_text(encoding="utf-8")
    files = ["vendor/gsap/gsap.min.js", "vendor/gsap/ScrollTrigger.min.js", "vendor/gsap/ScrollToPlugin.min.js", "vendor/gsap/Flip.min.js",
             "fonts/outfit-latin-wght-normal.woff2", "fonts/outfit-latin-ext-wght-normal.woff2",
             "fonts/geist-latin-wght-normal.woff2", "fonts/geist-latin-ext-wght-normal.woff2"]
    for rel in files:
        path = static / rel
        assert path.is_file(), f"{rel} is missing"
        digest = hashlib.sha256(path.read_bytes()).hexdigest()
        assert digest in note, f"{rel} does not match the SHA-256 recorded in static/vendor/README.md (edited or replaced?)"
    for licence in ("OFL.txt", "OFL-Geist.txt"):
        assert "SIL Open Font License" in (static / "fonts" / licence).read_text(encoding="utf-8")
    assert "GSAP 3." in (static / "vendor" / "gsap" / "gsap.min.js").read_text(encoding="utf-8")[:200]


def test_the_vendored_scripts_do_not_touch_the_network():
    for path in (WEB / "static" / "vendor" / "gsap").glob("*.js"):
        text = path.read_text(encoding="utf-8")
        for call in ("fetch(", "XMLHttpRequest", "importScripts", "sendBeacon", "WebSocket"):
            assert call not in text, f"{path.name} contains {call}"


def test_the_page_loads_gsap_before_its_own_code_and_declares_the_font():
    html = (WEB / "index.html").read_text(encoding="utf-8")
    assert html.index("gsap.min.js") < html.index("ScrollTrigger.min.js") < html.index("ScrollToPlugin.min.js") < html.index("Flip.min.js") < html.index("/static/js/main.js")
    css = (WEB / "static" / "css" / "styles.css").read_text(encoding="utf-8")
    assert css.count("@font-face") == 4 and "/static/fonts/geist-latin-wght-normal.woff2" in css and "/static/fonts/outfit-latin-wght-normal.woff2" in css
    assert "font-src 'self'" in __import__("app.server", fromlist=["CSP"]).CSP
    stack = re.search(r"--font:\s*([^;]+);", css).group(1)
    assert stack.index('"Geist"') < stack.index('"Outfit"'), "Geist is the first choice, Outfit the bundled fallback"


def test_the_server_serves_the_vendored_files_with_the_right_types(live):
    for path, ctype in (("/static/vendor/gsap/gsap.min.js", "text/javascript"), ("/static/vendor/gsap/ScrollTrigger.min.js", "text/javascript"),
                        ("/static/vendor/gsap/Flip.min.js", "text/javascript"), ("/static/vendor/gsap/ScrollToPlugin.min.js", "text/javascript"),
                        ("/static/fonts/outfit-latin-wght-normal.woff2", "font/woff2"),
                        ("/static/fonts/geist-latin-wght-normal.woff2", "font/woff2"), ("/static/fonts/geist-latin-ext-wght-normal.woff2", "font/woff2")):
        status, resp, raw = live.request("GET", path)
        assert status == 200 and resp.getheader("Content-Type").startswith(ctype) and len(raw) > 3_000, path


# ----------------------------------------------------------------------------------------------- smoothness regressions
def test_nothing_is_dimmed_with_a_brightness_filter():
    """Stacked cards and fading images were darkened with brightness(): that is what produced black panels. Opacity and scale only."""
    for path in _web_files(".css", ".js"):
        assert "brightness(" not in path.read_text(encoding="utf-8"), f"{path.name} dims with a brightness filter"


def test_scroll_linked_motion_is_always_smoothed():
    source = (WEB / "static" / "js" / "motion.js").read_text(encoding="utf-8")
    assert "scrub: true" not in source, "an unsmoothed scrub steps with every wheel notch; give it a number"
    assert source.count("scrub:") >= 6


def test_the_hero_is_hidden_from_first_paint_with_a_failsafe_and_no_section_clips_its_art():
    html = (WEB / "index.html").read_text(encoding="utf-8")
    css = (WEB / "static" / "css" / "styles.css").read_text(encoding="utf-8")
    assert 'data-intro="pending"' in html
    assert 'html[data-intro="pending"]' in css and "intro-failsafe" in css, "the intro must not flash, and must show itself even if the script never runs"
    hero_rule = re.search(r"\.hero \{[^}]*\}", css).group(0)
    assert "overflow" not in hero_rule, "a hero that clips its own art makes a hard edge"
    assert 'id="progress"' in html and "ambient" in html, "one fixed background and a progress line"


def test_the_page_has_no_remaining_reveal_class_that_hides_content_by_css():
    css = (WEB / "static" / "css" / "styles.css").read_text(encoding="utf-8")
    assert ".reveal" not in css, "content is hidden by the script only, so a script that fails leaves it visible"


def test_a_link_that_carries_a_query_runs_in_the_tab_that_is_already_open():
    """Pasting a shared link (or going back) changes only the hash: it must run that search, not be ignored after the first load."""
    main = (WEB / "static" / "js" / "main.js").read_text(encoding="utf-8")
    search = (WEB / "static" / "js" / "search.js").read_text(encoding="utf-8")
    assert "export function paramsDiffer" in search and "paramsDiffer" in main
    assert "applyParams(params, { scroll: true })" in main
