"""The application service behind the web interface: every call is a plain method that returns JSON-able data.

It adds no logic of its own to the ranking. Search, comparison and explanation come from `m4_rank`; judging files, qrels and
the data checks come from `eval`; documents come from M1's `judgments.jsonl`. What is new here is only presentation data
(titles, rank movement, file inventory) and the judging workbench, which writes the two judges' sheets.

Rules the service keeps, because the interface shows them to people:

* Nothing is faked. A stub signal is reported as a stub on every result, and a missing artefact is reported as missing.
* The judging workbench is blind: it reads only the pooled sheet, never `provenance.csv`, system scores or ranks, and it never
  proposes a grade. A grade exists only because a person typed it.
* Everything read from a judgment is untrusted text: control characters are stripped here and the page inserts it as text.
"""

from __future__ import annotations

import json
import os
import re
import threading
import time
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any, Callable, Iterable

from app.docmeta import describe
from common.config import ROOT, STUB_GROUPS, load_config, resolve_path
from common.io import read_jsonl
from common.providers import Providers, load_providers, stub_flags
from common.schema import Result
from eval.check_data import PLAN, check as check_data_files, corpus_ids
from eval.loaders import (
    EvalDataError, judging_root, load_overruled, load_qrels, load_queries, read_table, valid_round_name, write_table,
)
from m4_rank.explain import split_explanation, strip_controls
from m4_rank.rank import ArtefactError, ContractViolation, collect, fuse_collected, load_checked
from m4_rank.weights import SIGNALS, WeightsError, active_signals, canonical_config, load_weights, weights_source

NOTE = (
    "These are treatment signals with evidence, produced by automated analysis of later judgments. They are not legal advice. "
    "A signal can be wrong, can apply to one point of a judgment only, or can be superseded by a pending reference to a larger "
    "bench: read the cited sentences and the judgments before relying on any of it."
)
CONFIG_NAMES = ("b0", "b1", "full")
JUDGES = ("judge1", "judge2")
GRADES = (0, 1, 2)
MAX_K = 50
MAX_QUERY_CHARS = 500
MAX_NOTE_CHARS = 1000
SMALL_CORPUS_BYTES = 300 * 1024 * 1024  # titles and years are read from the corpus itself below this size
MAX_DOC_CHARS = 400_000
EXAMPLES_PATH = ROOT / "eval" / "examples" / "queries.example.jsonl"
_WHITESPACE = re.compile(r"\s+")
_FORMULA_LEAD = ("=", "+", "-", "@", "\t", "\r")


class ServiceError(Exception):
    """A failure the interface can show: an HTTP status, a short machine-readable kind and a human message."""

    def __init__(self, status: int, kind: str, message: str) -> None:
        super().__init__(message)
        self.status, self.kind, self.message = status, kind, message


def _clean(text: Any) -> str:
    return _WHITESPACE.sub(" ", strip_controls(text or "")).strip()


def _count_lines(path: Path, limit_bytes: int = 64 * 1024 * 1024) -> int | None:
    """Number of newline-terminated lines, or None for a file too large to be worth counting here."""
    try:
        if path.stat().st_size > limit_bytes:
            return None
        with open(path, "rb") as fh:
            return sum(chunk.count(b"\n") for chunk in iter(lambda: fh.read(1 << 20), b""))
    except OSError:
        return None


# --------------------------------------------------------------------------------------------------- documents
class DocStore:
    """Title, date and bench of every judgment plus random access to the text, from M1's judgments.jsonl.

    Built on first use, once. Above SMALL_CORPUS_BYTES the file is not scanned for metadata (the optional doc_meta.jsonl is
    used instead) and text is found by a resumable linear scan, so the first page load is never a multi-minute wait.
    """

    def __init__(self, judgments: Path, doc_meta: Path | None = None) -> None:
        self.path = judgments
        self.meta_path = doc_meta
        self._lock = threading.Lock()
        self._meta: dict[str, dict[str, Any]] | None = None
        self._offsets: dict[str, int] = {}
        self._scanned_to = 0
        self.scanned_all = False

    @property
    def exists(self) -> bool:
        return self.path.exists()

    def _load_meta(self) -> dict[str, dict[str, Any]]:
        with self._lock:
            if self._meta is not None:
                return self._meta
            meta: dict[str, dict[str, Any]] = {}
            small = self.exists and self.path.stat().st_size <= SMALL_CORPUS_BYTES
            if small:
                with open(self.path, "rb") as fh:
                    while True:
                        pos = fh.tell()
                        line = fh.readline()
                        if not line:
                            break
                        if not line.strip():
                            continue
                        try:
                            rec = json.loads(line)
                        except ValueError:
                            continue
                        doc_id = rec.get("doc_id")
                        if not doc_id:
                            continue
                        self._offsets[doc_id] = pos
                        meta[doc_id] = {k: rec.get(k) for k in ("doc_id", "title", "date", "bench_size")}
                    self._scanned_to = fh.tell()
                self.scanned_all = True
            elif self.meta_path is not None and self.meta_path.exists():
                meta = {rec["doc_id"]: rec for rec in read_jsonl(self.meta_path) if rec.get("doc_id")}
            self._meta = meta
            return meta

    def meta(self, doc_id: str) -> dict[str, Any] | None:
        return self._load_meta().get(doc_id)

    def all_meta(self) -> dict[str, dict[str, Any]]:
        return self._load_meta()

    def record(self, doc_id: str) -> dict[str, Any] | None:
        """The full judgment record, or None when the corpus does not contain it."""
        if not self.exists:
            return None
        self._load_meta()
        with self._lock:
            with open(self.path, "rb") as fh:
                if doc_id in self._offsets:
                    fh.seek(self._offsets[doc_id])
                    return json.loads(fh.readline())
                if self.scanned_all:
                    return None
                fh.seek(self._scanned_to)  # resume the scan where the last one stopped
                while True:
                    pos = fh.tell()
                    line = fh.readline()
                    if not line:
                        self.scanned_all = True
                        return None
                    try:
                        rec = json.loads(line)
                    except ValueError:
                        continue
                    if rec.get("doc_id"):
                        self._offsets[rec["doc_id"]] = pos
                    self._scanned_to = fh.tell()
                    if rec.get("doc_id") == doc_id:
                        return rec

    def summary(self) -> dict[str, Any]:
        meta = self._load_meta()
        years: Counter[str] = Counter()
        benches: Counter[str] = Counter()
        dates = []
        for m in meta.values():
            match = re.search(r"(19|20)\d{2}", str(m.get("date") or ""))
            years[match.group(0) if match else "unknown"] += 1
            benches[str(m.get("bench_size") or "unknown")] += 1
            if match:
                dates.append(match.group(0))
        return {
            "documents": len(meta),
            "years": dict(sorted(years.items())),
            "benches": dict(sorted(benches.items())),
            "first_year": min(dates) if dates else None,
            "last_year": max(dates) if dates else None,
            "from": "judgments.jsonl" if self.scanned_all else ("doc_meta.jsonl" if meta else None),
        }

    def titles(self, n: int) -> list[dict[str, Any]]:
        rows = [m for m in self._load_meta().values() if _clean(m.get("title"))]
        rows.sort(key=lambda m: (str(m.get("date") or ""), m["doc_id"]), reverse=True)
        return [{"doc_id": m["doc_id"], "title": _clean(m["title"]), "date": m.get("date")} for m in rows[:n]]


# --------------------------------------------------------------------------------------------------- service
class Service:
    """Everything the web interface can ask for. One instance serves all requests; provider calls are serialised."""

    def __init__(self, providers: Providers | None = None, loader: Callable[..., Providers] = load_providers) -> None:
        self._providers = providers
        self._loader = loader
        self._lock = threading.RLock()  # M1's engine is not documented as thread-safe: one search at a time
        self._write_lock = threading.Lock()
        self._docs: DocStore | None = None
        self._docs_key: tuple[str, str] | None = None

    # -- plumbing ----------------------------------------------------------------------------------
    def providers(self) -> Providers:
        with self._lock:
            if self._providers is None:
                try:
                    self._providers = load_checked(self._loader, load_config())
                except ArtefactError as exc:
                    raise ServiceError(503, "artefact", str(exc)) from exc
            return self._providers

    def docs(self) -> DocStore:
        cfg = load_config()
        key = (str(resolve_path("judgments", cfg)), str(resolve_path("doc_meta", cfg)))
        if self._docs is None or self._docs_key != key:
            self._docs = DocStore(Path(key[0]), Path(key[1]))
            self._docs_key = key
        return self._docs

    def _rank_errors(self, fn: Callable[[], Any]) -> Any:
        try:
            return fn()
        except ServiceError:
            raise
        except NotImplementedError as exc:
            raise ServiceError(501, "not_built", f"{exc}. That function is not built yet; keep its switch under `stubs:` true.") from exc
        except ContractViolation as exc:
            raise ServiceError(502, "contract", f"A module returned data that breaks its contract: {exc}") from exc
        except ArtefactError as exc:
            raise ServiceError(503, "artefact", f"A module could not find its data: {exc}") from exc
        except (ValueError, WeightsError) as exc:
            raise ServiceError(400, "invalid", str(exc)) from exc
        except Exception as exc:  # noqa: BLE001 - a bug in any module reads as one clear message
            raise ServiceError(500, "internal", f"Unexpected error in a module ({type(exc).__name__}): {exc}") from exc

    @staticmethod
    def _inputs(query: Any, date: Any, k: Any) -> tuple[str, str | None, int]:
        query = _clean(query)
        if not query:
            raise ServiceError(400, "invalid", "Enter a query: free text, a section such as 'BNS 103', or a Boolean/proximity query.")
        if len(query) > MAX_QUERY_CHARS:
            raise ServiceError(400, "invalid", f"The query is longer than {MAX_QUERY_CHARS} characters.")
        date = (str(date).strip() if date else "") or None
        try:
            k = int(k) if k not in (None, "") else 10
        except (TypeError, ValueError) as exc:
            raise ServiceError(400, "invalid", "k must be a whole number.") from exc
        return query, date, max(1, min(MAX_K, k))

    # -- presentation helpers ------------------------------------------------------------------------
    def _result(self, r: Result, rank: int, meta: dict[str, dict[str, Any]], ranks: dict[str, int] | None = None) -> dict[str, Any]:
        d = r.to_dict()
        m = meta.get(r.doc_id) or {}
        d["rank"] = rank
        d["title"] = _clean(m.get("title")) or None
        d["date"] = m.get("date")
        d["bench_size"] = m.get("bench_size")
        d["label"] = _clean(describe(m)) or None
        d["parts"] = [_clean(p) for p in split_explanation(r.explanation)]
        d["evidence"] = [
            {**{k: v for k, v in ev.items() if k != "sentence"}, "sentence": _clean(ev.get("sentence"))} for ev in (r.evidence or [])
        ]
        d["normalised"] = {"rel": r.rel, "cont": r.cont, "health": r.health, "auth": r.auth}
        if ranks is not None:
            d["ranks"] = ranks
        d["explanation"] = _clean(r.explanation)
        return d

    @staticmethod
    def _statutes(prov: Providers, query: str, date: str | None, used: Iterable[str]) -> dict[str, Any]:
        if "cont" not in used and "health" not in used:
            return {"used": False}
        try:
            qs = prov.parse_query(query, date)
        except NotImplementedError as exc:
            return {"used": True, "error": str(exc)}
        except (KeyError, FileNotFoundError, ValueError) as exc:
            return {"used": True, "error": f"{type(exc).__name__}: {exc}"}
        return {
            "used": True,
            "governing_act": qs.governing_act,
            "offence_date": qs.offence_date,
            "refs": [{"act": r.act, "section": r.section, "offence_id": r.offence_id} for r in qs.refs],
            "offence_ids": list(qs.offence_ids),
            "notes": [_clean(n) for n in qs.notes],
        }

    # -- endpoints ---------------------------------------------------------------------------------
    def status(self) -> dict[str, Any]:
        cfg = load_config()
        flags = stub_flags(cfg)
        load_error = None
        try:
            prov = self.providers()
            groups = {g: ("stub" if g in prov.stubbed else "real") for g in STUB_GROUPS}
        except ServiceError as exc:
            groups = {g: ("stub" if flags[g] else "real") for g in STUB_GROUPS}
            load_error = exc.message
        configs = {}
        for name in CONFIG_NAMES:
            if name in cfg["ranking"]["configs"]:
                configs[name] = {"weights": load_weights(name, cfg), "source": weights_source(name, cfg)}
        artefacts = []
        for key in ("judgments", "doc_statutes", "citations", "doc_health", "doc_meta", "statute_map", "treatment_gold",
                    "queries", "qrels", "gold_overrulings"):
            path = resolve_path(key, cfg)
            exists = path.exists()
            row: dict[str, Any] = {"key": key, "exists": exists, "size": path.stat().st_size if exists else None}
            if exists and path.suffix in (".jsonl", ".csv", ".tsv"):
                lines = _count_lines(path)
                row["rows"] = None if lines is None else max(0, lines - (0 if path.suffix == ".jsonl" else 1))
            artefacts.append(row)
        index_dir = resolve_path("index_dir", cfg)
        artefacts.append({"key": "index_dir", "exists": index_dir.is_dir(), "size": None})
        stubbed = sorted(g for g, v in groups.items() if v == "stub")
        return {
            "providers": groups,
            "stubbed": stubbed,
            "stub_mode": bool(stubbed),
            "load_error": load_error,
            "env_override": os.environ.get("LEXSHIFT_STUBS") or None,
            "candidates": int(cfg["ranking"]["candidates"]),
            "configs": configs,
            "artefacts": artefacts,
            "corpus": self.docs().summary() if self.docs().exists else None,
            "note": NOTE,
        }

    def search(self, query: Any, offence_date: Any = None, k: Any = 10, config: Any = "full") -> dict[str, Any]:
        query, date, k = self._inputs(query, offence_date, k)
        cfg = load_config()

        def run() -> dict[str, Any]:
            name = canonical_config(str(config or "full"), cfg)
            weights = load_weights(name, cfg)
            prov = self.providers()
            started = time.perf_counter()
            used = [s for s in SIGNALS if s in active_signals(weights)]
            with self._lock:
                collected = collect(query, date, active_signals(weights), providers=prov, cfg=cfg)
                results = fuse_collected(collected, weights, k, cfg)
                statutes = self._statutes(prov, query, date, used)
            meta = self.docs().all_meta()
            return {
                "query": query, "offence_date": date, "config": name, "k": k,
                "weights": weights, "weights_source": weights_source(name, cfg), "signals_used": used,
                "stubbed": [s for s in collected.stubbed if s in used],
                "candidates": len(collected.rows),
                "statutes": statutes,
                "results": [self._result(r, i, meta) for i, r in enumerate(results, start=1)],
                "elapsed_ms": round((time.perf_counter() - started) * 1000),
                "note": NOTE,
            }

        return self._rank_errors(run)

    def compare(self, query: Any, offence_date: Any = None, k: Any = 10) -> dict[str, Any]:
        """B0, B1 and the full system over ONE collection of signals, with each document's rank under every config."""
        query, date, k = self._inputs(query, offence_date, k)
        cfg = load_config()

        def run() -> dict[str, Any]:
            prov = self.providers()
            started = time.perf_counter()
            names = [n for n in CONFIG_NAMES if n in cfg["ranking"]["configs"]]
            weights = {n: load_weights(n, cfg) for n in names}
            with self._lock:
                collected = collect(query, date, SIGNALS, providers=prov, cfg=cfg)
                depth = max(1, len(collected.rows))
                full_rankings = {n: fuse_collected(collected, weights[n], depth, cfg) for n in names}
                statutes = self._statutes(prov, query, date, SIGNALS)
            position = {n: {r.doc_id: i for i, r in enumerate(rs, start=1)} for n, rs in full_rankings.items()}
            meta = self.docs().all_meta()
            out: dict[str, Any] = {}
            for n in names:
                used = [s for s in SIGNALS if s in active_signals(weights[n])]
                out[n] = {
                    "weights": weights[n], "source": weights_source(n, cfg), "signals_used": used,
                    "stubbed": [s for s in collected.stubbed if s in used],
                    "results": [
                        self._result(r, i, meta, {m: position[m].get(r.doc_id) for m in names})
                        for i, r in enumerate(full_rankings[n][:k], start=1)
                    ],
                }
            return {
                "query": query, "offence_date": date, "k": k, "candidates": len(collected.rows),
                "configs": out, "statutes": statutes,
                "elapsed_ms": round((time.perf_counter() - started) * 1000), "note": NOTE,
            }

        return self._rank_errors(run)

    def document(self, doc_id: Any, max_chars: Any = 60_000) -> dict[str, Any]:
        doc_id = str(doc_id or "").strip()
        if not doc_id:
            raise ServiceError(400, "invalid", "doc_id is required.")
        try:
            limit = max(1_000, min(MAX_DOC_CHARS, int(max_chars)))
        except (TypeError, ValueError):
            limit = 60_000
        store = self.docs()
        if not store.exists:
            raise ServiceError(404, "no_corpus", "The corpus (judgments.jsonl) has not been built, so there is no text to show.")
        rec = store.record(doc_id)
        if rec is None:
            kind = "a stand-in id, not a real judgment" if doc_id.startswith("STUB-") else "not in the corpus"
            raise ServiceError(404, "not_found", f"{doc_id} is {kind}.")
        text = strip_controls(rec.get("text") or "")
        zones = rec.get("zones") or {}
        return {
            "doc_id": doc_id,
            "title": _clean(rec.get("title")) or None,
            "date": rec.get("date"),
            "bench_size": rec.get("bench_size"),
            "judges": [_clean(j) for j in (rec.get("judges") or [])],
            "reporter_citations": [_clean(c) for c in (rec.get("reporter_citations") or [])],
            "zones": {k: len(strip_controls(v or "")) for k, v in zones.items()} if isinstance(zones, dict) else {},
            "characters": len(text),
            "text": text[:limit],
            "truncated": len(text) > limit,
        }

    def examples(self) -> dict[str, Any]:
        """The suggested example queries (AI-drafted inputs, not the judged set): see eval/JUDGING_GUIDE.md."""
        if not EXAMPLES_PATH.exists():
            return {"suggested": True, "queries": []}
        keep = ("qid", "text", "offence_date", "split", "type")
        return {"suggested": True, "queries": [{k: rec.get(k) for k in keep} for rec in read_jsonl(EXAMPLES_PATH)]}

    def corpus(self, n: Any = 40) -> dict[str, Any]:
        try:
            n = max(1, min(200, int(n)))
        except (TypeError, ValueError):
            n = 40
        store = self.docs()
        return {"available": store.exists, "titles": store.titles(n) if store.exists else []}

    # -- evaluation ----------------------------------------------------------------------------------
    def evaluation(self) -> dict[str, Any]:
        cfg = load_config()
        data: dict[str, Any] = {"plan": dict(PLAN), "errors": []}
        try:
            queries = load_queries()
            known = {q.qid for q in queries}
            qrels = load_qrels(known_qids=known)
            overruled = load_overruled()
        except EvalDataError as exc:
            data["errors"].append(str(exc))
            queries, qrels, overruled = [], {}, set()
        by_split = Counter(q.split for q in queries)
        grades = Counter(g for docs in qrels.values() for g in docs.values())
        data["queries"] = {
            "total": len(queries), "dev": by_split["dev"], "test": by_split["test"],
            "types": dict(sorted(Counter(q.type for q in queries).items())),
        }
        data["qrels"] = {"rows": sum(grades.values()), "queries": len(qrels), "grades": {str(g): grades[g] for g in GRADES}}
        data["gold_overrulings"] = len(overruled)
        findings = None
        try:
            needed = {d for docs in qrels.values() for d in docs} | overruled
            findings = check_data_files(queries, qrels, overruled, corpus_ids(needed) if needed else set())
        except Exception as exc:  # noqa: BLE001 - the checker must never take the page down
            data["errors"].append(f"data checks failed: {type(exc).__name__}: {exc}")
        data["checks"] = (
            {"errors": findings.errors, "warnings": findings.warnings, "info": findings.info} if findings else None
        )
        return {"data": data, "runs": self._ablation_runs(Path(resolve_path("results_dir", cfg))), "rounds": self._round_names()}

    @staticmethod
    def _ablation_runs(results_dir: Path) -> list[dict[str, Any]]:
        runs: list[dict[str, Any]] = []
        if not results_dir.is_dir():
            return runs
        for path in sorted(results_dir.glob("*ablation_*.csv")):
            stem = path.stem
            split = stem.rsplit("_", 1)[-1]
            stub = stem.startswith("stub_")
            try:
                rows = read_table(path)
            except (OSError, ValueError):
                continue
            parsed = []
            for row in rows:
                item: dict[str, Any] = {}
                for key, value in row.items():
                    if key == "config":
                        item[key] = value
                    else:
                        try:
                            item[key] = float(value) if value != "" else None
                        except ValueError:
                            item[key] = None
                parsed.append(item)
            per_type: dict[str, dict[str, list[float]]] = defaultdict(lambda: defaultdict(list))
            per_query = results_dir / path.name.replace("ablation_", "per_query_")
            if per_query.exists():
                for row in read_table(per_query):
                    try:
                        per_type[row["type"]][row["config"]].append(float(row["nDCG@10"]))
                    except (KeyError, ValueError):
                        continue
            runs.append({
                "file": path.name, "split": split, "stub": stub, "rows": parsed,
                "ndcg_by_type": {t: {c: round(sum(v) / len(v), 4) for c, v in cs.items() if v} for t, cs in sorted(per_type.items())},
                "modified": time.strftime("%Y-%m-%d %H:%M", time.localtime(path.stat().st_mtime)),
            })
        return runs

    # -- judging workbench -----------------------------------------------------------------------------
    def _round_names(self) -> list[str]:
        root = judging_root()
        if not root.is_dir():
            return []
        return sorted(p.name for p in root.iterdir() if p.is_dir() and valid_round_name(p.name) and (p / "sheet_template.csv").exists())

    def _round(self, name: Any) -> tuple[Path, list[dict[str, str]]]:
        name = str(name or "")
        if not valid_round_name(name):
            raise ServiceError(400, "invalid", "Not a valid round name.")
        directory = judging_root() / name
        template = directory / "sheet_template.csv"
        if not directory.is_dir() or not template.exists():
            raise ServiceError(404, "not_found", f"There is no judging round {name!r} with a sheet_template.csv.")
        return directory, read_table(template)

    @staticmethod
    def _judge(name: Any) -> str:
        if name not in JUDGES:
            raise ServiceError(400, "invalid", f"judge must be one of {', '.join(JUDGES)}.")
        return str(name)

    @staticmethod
    def _graded(directory: Path, judge: str) -> dict[tuple[str, str], tuple[str, str]]:
        path = directory / f"{judge}.csv"
        if not path.exists():
            return {}
        out: dict[tuple[str, str], tuple[str, str]] = {}
        for row in read_table(path):
            note = row.get("note", "")
            if note[:1] == "'" and note[1:2] in _FORMULA_LEAD:
                note = note[1:]  # undo the spreadsheet-formula guard added on write
            out[(row.get("qid", "").strip(), row.get("doc_id", "").strip())] = (row.get("grade", "").strip(), note)
        return out

    def judge_rounds(self) -> dict[str, Any]:
        rounds = []
        for name in self._round_names():
            directory, rows = self._round(name)
            entry: dict[str, Any] = {"round": name, "rows": len(rows), "queries": len({r["qid"] for r in rows}), "judges": {}}
            for judge in JUDGES:
                graded = self._graded(directory, judge)
                entry["judges"][judge] = {
                    "started": (directory / f"{judge}.csv").exists(),
                    "graded": sum(1 for r in rows if graded.get((r["qid"], r["doc_id"]), ("", ""))[0] != ""),
                }
            rounds.append(entry)
        return {"rounds": rounds, "judging_dir": os.path.relpath(judging_root(), ROOT) if judging_root().is_relative_to(ROOT) else str(judging_root())}

    def judge_sheet(self, round_name: Any, judge: Any) -> dict[str, Any]:
        directory, rows = self._round(round_name)
        judge = self._judge(judge)
        graded = self._graded(directory, judge)
        grouped: dict[str, dict[str, Any]] = {}
        done = 0
        for r in rows:
            grade, note = graded.get((r["qid"], r["doc_id"]), ("", ""))
            done += grade != ""
            group = grouped.setdefault(r["qid"], {
                "qid": r["qid"], "query": _clean(r["query"]), "type": r.get("type", ""),
                "offence_date": r.get("offence_date") or None, "docs": [],
            })
            group["docs"].append({
                "doc_id": r["doc_id"], "title": _clean(r.get("title")), "date": r.get("date"),
                "bench_size": r.get("bench_size") or None, "excerpt": _clean(r.get("excerpt")),
                "grade": int(grade) if grade in ("0", "1", "2") else None, "note": _clean(note),
            })
        return {
            "round": str(round_name), "judge": judge, "queries": list(grouped.values()),
            "progress": {"graded": done, "total": len(rows)},
        }

    def judge_grade(self, round_name: Any, judge: Any, qid: Any, doc_id: Any, grade: Any, note: Any = "") -> dict[str, Any]:
        directory, rows = self._round(round_name)
        judge = self._judge(judge)
        qid, doc_id = str(qid or ""), str(doc_id or "")
        if (qid, doc_id) not in {(r["qid"], r["doc_id"]) for r in rows}:
            raise ServiceError(404, "not_found", "That query and document are not in this round's sheet.")
        if grade is None or grade == "":
            value = ""
        elif isinstance(grade, bool) or grade not in GRADES:
            raise ServiceError(400, "invalid", "grade must be 0, 1 or 2 (or empty to clear it).")
        else:
            value = str(int(grade))
        note = _clean(note)[:MAX_NOTE_CHARS]
        cell = "'" + note if note[:1] in _FORMULA_LEAD else note  # judges open these files in a spreadsheet
        columns = list(rows[0].keys()) if rows else []
        target = directory / f"{judge}.csv"
        with self._write_lock:
            current = read_table(target) if target.exists() else [dict(r, grade="", note="") for r in rows]
            by_key = {(r["qid"], r["doc_id"]): r for r in current}
            if set(by_key) != {(r["qid"], r["doc_id"]) for r in rows}:  # a hand-edited file that no longer matches the template
                raise ServiceError(409, "conflict", f"{target.name} no longer matches sheet_template.csv; fix or remove it first.")
            by_key[(qid, doc_id)]["grade"] = value
            by_key[(qid, doc_id)]["note"] = cell
            write_table(target, columns, [{c: r.get(c, "") for c in columns} for r in current])
        done = sum(1 for r in current if (r.get("grade") or "").strip() != "")
        return {"saved": True, "qid": qid, "doc_id": doc_id, "grade": int(value) if value else None, "progress": {"graded": done, "total": len(rows)}}
