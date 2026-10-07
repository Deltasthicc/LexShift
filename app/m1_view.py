"""Read-only views of M1's index for the interface's Index page: the corpus, the text processing, the postings, the query parser and BM25.

Everything here is read from M1's real artefacts and functions (`m1_index`); nothing is a stored example. The page explains the
pipeline with numbers from the index that is on disk, and says so when a piece the owner listed is not in the pushed code.

The engine is built from the repository's own index folder (not the working directory), once, and only read afterwards. Building
the index is M1's command: `python -m m1_index.index build` (it needs `data/processed/judgments.jsonl`).
"""

from __future__ import annotations

import json
import re
import statistics
import threading
import time
from collections import Counter
from pathlib import Path
from typing import Any, Callable

from common.config import ROOT, load_config, resolve_path
from common.schema import ZONES

MAX_TEXT_CHARS = 2000
MAX_QUERY_CHARS = 300
MAX_K = 20
BENCH_QUERIES = (
    ("one term", "murder"),
    ("plain text", "punishment for murder under section 103 BNS"),
    ("Boolean", "murder AND intention"),
    ("phrase", '"common intention"'),
    ("proximity", "murder /10 intention"),
)
BENCH_RUNS = 15
RAW_TOKEN = re.compile(r"[a-z]+(?:-[a-z0-9]+)*|\d+[a-z]*(?:-[a-z0-9]+)*")  # the pattern tokenize() applies after case folding


class ExplorerError(Exception):
    """A failure the page can show: HTTP status, short kind, human message (the service turns it into a ServiceError)."""

    def __init__(self, status: int, kind: str, message: str) -> None:
        super().__init__(message)
        self.status, self.kind, self.message = status, kind, message


def ast_to_dict(node: Any) -> dict[str, Any]:
    """The parsed query as plain data, for drawing the tree."""
    from m1_index.query_parser import BooleanNode, NotNode, PhraseNode, ProximityNode, TermNode

    if isinstance(node, TermNode):
        return {"type": "term", "term": node.term}
    if isinstance(node, PhraseNode):
        return {"type": "phrase", "terms": list(node.terms)}
    if isinstance(node, ProximityNode):
        return {"type": "proximity", "op": node.operator, "left": ast_to_dict(node.left), "right": ast_to_dict(node.right)}
    if isinstance(node, BooleanNode):
        return {"type": node.operator.lower(), "left": ast_to_dict(node.left), "right": ast_to_dict(node.right)}
    if isinstance(node, NotNode):
        return {"type": "not", "child": ast_to_dict(node.child)}
    return {"type": "unknown"}


class IndexExplorer:
    """One instance serves all requests. `engine_factory` exists so tests can hand in a small engine."""

    def __init__(self, engine_factory: Callable[[], Any] | None = None, judgments: Path | None = None) -> None:
        self._factory = engine_factory
        self._judgments = judgments
        self._engine: Any = None
        self._load_ms: float | None = None
        self._lock = threading.RLock()
        self._zone_tokens: dict[str, dict[str, list[str]]] | None = None
        self._warm_started = False

    # -- plumbing ----------------------------------------------------------------------------------
    def _index_dir(self) -> Path:
        return ROOT / "data" / "processed" / "index"

    def engine(self) -> Any:
        with self._lock:
            if self._engine is None:
                started = time.perf_counter()
                try:
                    if self._factory is not None:
                        self._engine = self._factory()
                    else:
                        from m1_index.searcher import RankedSearchEngine

                        self._engine = RankedSearchEngine(index_dir=self._index_dir())
                except FileNotFoundError as exc:
                    raise ExplorerError(503, "index_missing", "M1's index is not built here. Build it once with: python -m m1_index.index build") from exc
                except (LookupError, RuntimeError, ImportError) as exc:
                    raise ExplorerError(503, "m1_unavailable", f"M1's code cannot be loaded here: {exc}") from exc
                self._load_ms = (time.perf_counter() - started) * 1000
            return self._engine

    @staticmethod
    def _text(value: Any, limit: int) -> str:
        if not isinstance(value, str):
            raise ExplorerError(400, "bad_input", "A text value is required.")
        text = value.strip()
        if not text:
            raise ExplorerError(400, "bad_input", "The text is empty.")
        return text[:limit]

    def warm(self) -> None:
        """Tokenise the corpus in the background so the first brute-force check is not a long wait (about 13 s on a laptop)."""
        with self._lock:
            if self._warm_started:
                return
            self._warm_started = True

        def work() -> None:
            try:
                self._tokens_by_zone()
            except Exception:  # noqa: BLE001 - a failed warm-up only means the first check does the work itself
                self._warm_started = False

        threading.Thread(target=work, daemon=True, name="m1-scan-warmup").start()

    # -- the corpus and the index -------------------------------------------------------------------
    def overview(self) -> dict[str, Any]:
        from m1_index import searcher, tokenizer

        eng = self.engine()
        self.warm()
        index = eng.index
        meta = index.doc_meta
        years = Counter(m.get("year") for m in meta.values())
        benches = Counter(m.get("bench_size") for m in meta.values())
        zones = tuple(ZONES)
        zone_tokens = {z: sum(lens.get(z, 0) for lens in index.doc_lengths.values()) for z in zones}
        postings = index.postings_map
        df_top = sorted(((t, len(p)) for t, p in postings.items()), key=lambda x: (-x[1], x[0]))[:14]
        size = None
        try:
            size = (self._index_dir() / "index.pkl.gz").stat().st_size
        except OSError:
            pass
        sample = sorted(meta.items(), key=lambda kv: kv[0])[:6]
        return {
            "docs": len(meta),
            "years": {str(k): v for k, v in sorted(years.items(), key=lambda kv: (kv[0] is None, kv[0]))},
            "bench": {("unknown" if k is None else str(k)): v for k, v in sorted(benches.items(), key=lambda kv: (kv[0] is None, kv[0] or 0))},
            "terms": len(postings),
            "postings": sum(len(p) for p in postings.values()),
            "positions": sum(len(e["positions"]) for p in postings.values() for e in p.values()),
            "tokens": sum(zone_tokens.values()),
            "zone_tokens": zone_tokens,
            "zone_weights": dict(searcher.ZONE_WEIGHTS),
            "avg_zone_length": {z: round(v, 1) for z, v in eng.avg_zone_length.items()},
            "bm25": {"k1": searcher.K1, "b": searcher.B},
            "index_bytes": size,
            "load_ms": None if self._load_ms is None else round(self._load_ms),
            "top_terms": [{"term": t, "df": d} for t, d in df_top],
            "sample": [{"doc_id": d, "title": m.get("title"), "date": m.get("date"), "bench_size": m.get("bench_size")} for d, m in sample],
            "stopwords": len(tokenizer.STOPWORDS),
            "capabilities": self._capabilities(),
        }

    @staticmethod
    def _capabilities() -> dict[str, Any]:
        """What the pushed code does and does not contain, probed from the code itself where that is possible."""
        from m1_index import scoring

        try:
            scoring.lnc_ltc_scores(["probe"], None)
            lnc = "implemented"
        except NotImplementedError:
            lnc = "not implemented"
        except Exception:  # noqa: BLE001 - any other failure means the function exists and ran
            lnc = "implemented"
        import importlib.util

        return {
            "lnc_ltc": lnc,
            "library_bm25_comparison": "available" if importlib.util.find_spec("rank_bm25") else "not installed",
        }

    # -- text processing ----------------------------------------------------------------------------
    def analyze(self, text: Any) -> dict[str, Any]:
        from m1_index import tokenizer as T

        text = self._text(text, MAX_TEXT_CHARS)
        normalised = T.normalize_citations(text)
        steps = []
        final = []
        for raw in RAW_TOKEN.findall(normalised.lower()):
            if T.is_legal_token(raw):
                steps.append({"raw": raw, "fate": "kept", "out": raw, "why": "legal token: a section, a citation or a number is never stemmed or dropped"})
                final.append(raw)
            elif raw in T.STOPWORDS:
                steps.append({"raw": raw, "fate": "stopword", "out": None, "why": "English stop word, removed"})
            else:
                stem = T.STEMMER.stem(raw)
                steps.append({"raw": raw, "fate": "stemmed" if stem != raw else "unchanged", "out": stem, "why": "Porter stem"})
                final.append(stem)
        return {
            "input": text,
            "normalised": normalised,
            "steps": steps,
            "tokens": final,
            "consistent": final == T.tokenize(text),  # this page's walk-through must give exactly M1's tokenize()
        }

    # -- postings -----------------------------------------------------------------------------------
    def term(self, word: Any) -> dict[str, Any]:
        from m1_index.query_parser import normalize_term

        word = self._text(word, 80)
        eng = self.engine()
        try:
            term = normalize_term(word)
        except ValueError as exc:
            raise ExplorerError(400, "bad_input", str(exc)) from exc
        entries = eng.index.postings_map.get(term, {})
        rows = []
        for doc_id, entry in sorted(entries.items(), key=lambda kv: (-kv[1]["tf"], kv[0]))[:12]:
            m = eng.doc_meta.get(doc_id, {})
            rows.append({
                "doc_id": doc_id, "title": m.get("title"), "date": m.get("date"), "tf": entry["tf"], "zones": dict(entry["zones"]),
                "positions": entry["positions"][:10], "n_positions": len(entry["positions"]),
            })
        return {"word": word, "term": term, "df": len(entries), "docs": eng.doc_count, "idf": round(eng._idf(term), 4), "postings": rows}

    # -- queries ------------------------------------------------------------------------------------
    def _parse(self, query: str) -> tuple[str, Any, list[str]]:
        """('boolean', ast, terms) when the query parses, else ('plain', None, terms) exactly as M1's search() falls back."""
        from m1_index.query_parser import parse_query
        from m1_index.tokenizer import tokenize

        eng = self.engine()
        try:
            ast = parse_query(query)
            terms = list(dict.fromkeys(eng._collect_terms(ast)))
            return "boolean", ast, terms
        except ValueError:
            return "plain", None, list(dict.fromkeys(tokenize(query)))

    def query(self, query: Any, k: Any = 5) -> dict[str, Any]:
        from m1_index import searcher

        query = self._text(query, MAX_QUERY_CHARS)
        try:
            k = max(1, min(MAX_K, int(k)))
        except (TypeError, ValueError):
            k = 5
        eng = self.engine()
        with self._lock:
            mode, ast, terms = self._parse(query)
            if ast is not None:
                candidates = eng._eval_ast(ast)
            else:
                candidates = set()
                for t in terms:
                    candidates.update(eng.index.postings_map.get(t, {}).keys())
            started = time.perf_counter()
            hits = eng.search(query, k=k)
            elapsed = (time.perf_counter() - started) * 1000
        weights = searcher.ZONE_WEIGHTS
        out_hits = []
        for h in hits:
            m = eng.doc_meta.get(h.doc_id, {})
            out_hits.append({
                "doc_id": h.doc_id, "title": m.get("title"), "date": m.get("date"), "bench_size": m.get("bench_size"), "rel": round(h.rel, 4),
                "zones": {z: {"score": round(h.zone_scores.get(z, 0.0), 4), "weight": weights[z], "part": round(h.zone_scores.get(z, 0.0) * weights[z], 4)} for z in weights},
            })
        return {
            "query": query, "mode": mode, "tree": ast_to_dict(ast) if ast is not None else None, "terms": terms,
            "candidates": len(candidates), "docs": eng.doc_count, "k": k, "ms": round(elapsed, 2), "hits": out_hits,
            "worked": self._worked_example(eng, hits, terms) if hits and terms else None,
        }

    @staticmethod
    def _worked_example(eng: Any, hits: list[Any], terms: list[str]) -> dict[str, Any] | None:
        """BM25 arithmetic for the top hit: the term and zone that contribute most, with every number the formula uses."""
        from m1_index import searcher

        top = hits[0]
        best: tuple[float, str, str] | None = None
        for z, w in searcher.ZONE_WEIGHTS.items():
            for t in terms:
                part = w * eng._zone_bm25(t, top.doc_id, z)
                if best is None or part > best[0]:
                    best = (part, t, z)
        if best is None or best[0] <= 0:
            return None
        _, term, zone = best
        entry = eng.index.postings_map.get(term, {}).get(top.doc_id, {})
        tf = entry.get("zones", {}).get(zone, 0)
        dl = eng.index.doc_lengths.get(top.doc_id, {}).get(zone, 0)
        avgdl = eng.avg_zone_length.get(zone, 1.0)
        idf = eng._idf(term)
        return {
            "doc_id": top.doc_id, "term": term, "zone": zone, "tf": tf, "dl": dl, "avgdl": round(avgdl, 2), "idf": round(idf, 4),
            "k1": searcher.K1, "b": searcher.B, "weight": searcher.ZONE_WEIGHTS[zone], "bm25": round(eng._zone_bm25(term, top.doc_id, zone), 4),
        }

    # -- checking the engine against a plain scan ----------------------------------------------------
    def _tokens_by_zone(self) -> dict[str, dict[str, list[str]]]:
        from m1_index.tokenizer import tokenize

        if self._zone_tokens is None:
            path = self._judgments or resolve_path("judgments", load_config())
            if not Path(path).exists():
                raise ExplorerError(503, "corpus_missing", "data/processed/judgments.jsonl is missing, so there is nothing to scan.")
            built: dict[str, dict[str, list[str]]] = {}
            with open(path, encoding="utf-8") as fh:
                for line in fh:
                    if not line.strip():
                        continue
                    rec = json.loads(line)
                    built[rec["doc_id"]] = {z: tokenize(t) for z, t in (rec.get("zones") or {}).items()}
            self._zone_tokens = built
        return self._zone_tokens

    def _scan(self, node: Any, docs: dict[str, dict[str, list[str]]]) -> set[str] | None:
        """The documents a query should match, found by reading every token of every zone (no index). None for proximity."""
        t = node["type"]
        if t == "term":
            return {d for d, zs in docs.items() if any(node["term"] in toks for toks in zs.values())}
        if t == "phrase":
            want = node["terms"]
            n = len(want)
            return {d for d, zs in docs.items() if any(toks[i:i + n] == want for toks in zs.values() for i in range(len(toks) - n + 1))}
        if t in ("and", "or"):
            a, b = self._scan(node["left"], docs), self._scan(node["right"], docs)
            if a is None or b is None:
                return None
            return a & b if t == "and" else a | b
        if t == "not":
            inner = self._scan(node["child"], docs)
            return None if inner is None else set(docs) - inner
        return None

    def verify(self, query: Any) -> dict[str, Any]:
        query = self._text(query, MAX_QUERY_CHARS)
        eng = self.engine()
        with self._lock:
            mode, ast, _ = self._parse(query)
            if ast is None:
                return {"query": query, "checked": False, "reason": "plain text is a bag of words (any term matches), so there is no Boolean structure to check"}
            tree = ast_to_dict(ast)
            expected = self._scan(tree, self._tokens_by_zone())
            if expected is None:
                return {"query": query, "checked": False, "reason": "proximity is not checked by this scan"}
            got = set(eng._eval_ast(ast))
        only_engine, only_scan = sorted(got - expected), sorted(expected - got)
        return {"query": query, "checked": True, "agree": not only_engine and not only_scan, "engine": len(got), "scan": len(expected),
                "only_engine": only_engine[:5], "only_scan": only_scan[:5], "n_only_engine": len(only_engine), "n_only_scan": len(only_scan)}

    # -- latency ------------------------------------------------------------------------------------
    def bench(self) -> dict[str, Any]:
        eng = self.engine()
        rows = []
        with self._lock:
            for label, q in BENCH_QUERIES:
                eng.search(q, k=100)  # warm-up, not counted
                times = []
                for _ in range(BENCH_RUNS):
                    started = time.perf_counter()
                    n = len(eng.search(q, k=100))
                    times.append((time.perf_counter() - started) * 1000)
                times.sort()
                rows.append({"label": label, "query": q, "hits": n, "median_ms": round(statistics.median(times), 2),
                             "p95_ms": round(times[min(len(times) - 1, int(len(times) * 0.95))], 2), "min_ms": round(times[0], 2)})
        return {"runs": BENCH_RUNS, "k": 100, "rows": rows, "load_ms": None if self._load_ms is None else round(self._load_ms)}
