"""Shared data contracts for LexShift (Team Build Guide, sections 4.2 and 4.3).

Every module reads and writes these shapes and nothing else. If a field has to change, get a yes from the
owners of every module that touches it first (docs/CONTRACTS.md), then change it here and in the docs.

Fields the Guide does not spell out (marked "proposed" below) are v0.1 proposals recorded in DECISIONS.md
(D-004). Owners may amend them early, before their module is merged to main.
"""

from __future__ import annotations

import datetime as _dt
from dataclasses import asdict, dataclass, field, fields
from typing import Any, TypedDict

# --------------------------------------------------------------------------------------------------
# Controlled vocabularies (Guide 4.2 / 4.4)
# --------------------------------------------------------------------------------------------------
ACTS = ("IPC", "BNS", "CRPC", "BNSS")
RELATIONS = (
    "equivalent",
    "modified_punishment",
    "modified_elements",
    "split",
    "merged",
    "omitted",
    "new",
)
TREATMENT_LABELS = ("followed", "distinguished", "doubted", "overruled", "neutral")
NEGATIVE_LABELS = ("doubted", "overruled")  # the labels health() can penalise
ZONES = ("headnote", "facts", "arguments", "holding")
SPLITS = ("dev", "test")
QUERY_TYPES = ("A", "B", "C", "D")  # A BNS->IPC, B changed/omitted, C overruled doctrine, D bare-number collision
GRADES = (0, 1, 2)
OFFENCE_ID_PREFIX = "OFF_"
BNS_COMMENCEMENT = "2024-07-01"  # BNS/BNSS in force from this date; before it the IPC/CrPC govern

# Column orders of the tabular files (Guide 4.2)
STATUTE_MAP_COLUMNS = ("old_act", "old_section", "new_act", "new_section", "relation", "weight", "source", "note")
TREATMENT_GOLD_COLUMNS = ("window_id", "window", "gold_label", "labeller")
QRELS_COLUMNS = ("qid", "doc_id", "grade")  # proposed: header row `qid<TAB>doc_id<TAB>grade`


class SchemaError(ValueError):
    """A record does not satisfy its contract."""


class Evidence(TypedDict):
    """One piece of treatment evidence attached to a health() result (Guide 4.2, doc_health.jsonl)."""

    citing_doc: str
    label: str
    sentence: str


# --------------------------------------------------------------------------------------------------
# Helpers
# --------------------------------------------------------------------------------------------------
def _check_iso_date(value: str | None, name: str, *, optional: bool = False) -> None:
    if value is None:
        if optional:
            return
        raise SchemaError(f"{name} is required (YYYY-MM-DD)")
    try:
        _dt.date.fromisoformat(value)
    except (TypeError, ValueError) as exc:
        raise SchemaError(f"{name} must be an ISO date YYYY-MM-DD, got {value!r}") from exc


def _check_in(value: Any, allowed: tuple, name: str) -> None:
    if value not in allowed:
        raise SchemaError(f"{name} must be one of {allowed}, got {value!r}")


def _check_unit(value: Any, name: str) -> None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise SchemaError(f"{name} must be a number in [0, 1], got {value!r}")
    if not 0.0 <= float(value) <= 1.0:
        raise SchemaError(f"{name} must be in [0, 1], got {value!r}")


class _Record:
    """Mixin: dict round-trip and field-aware construction shared by every record type."""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)  # type: ignore[call-overload]

    @classmethod
    def from_dict(cls, data: dict[str, Any]):
        names = {f.name for f in fields(cls)}  # type: ignore[arg-type]
        unknown = set(data) - names
        if unknown:
            raise SchemaError(f"{cls.__name__}: unknown field(s) {sorted(unknown)}")
        try:
            obj = cls(**data)  # type: ignore[call-arg]
        except TypeError as exc:
            raise SchemaError(f"{cls.__name__}: {exc}") from exc
        obj.validate()
        return obj

    def validate(self) -> None:  # overridden where there is something to check
        return None


# --------------------------------------------------------------------------------------------------
# M1: corpus and search
# --------------------------------------------------------------------------------------------------
@dataclass
class Judgment(_Record):
    """One line of data/processed/judgments.jsonl (owner: M1)."""

    doc_id: str
    title: str
    date: str  # YYYY-MM-DD
    bench_size: int | None  # number of judges; None only if it truly cannot be recovered
    judges: list[str]
    reporter_citations: list[str]
    zones: dict[str, str]  # keys from ZONES; missing zone = absent key
    text: str

    def validate(self) -> None:
        if not self.doc_id:
            raise SchemaError("doc_id must be non-empty")
        _check_iso_date(self.date, "date")
        if self.bench_size is not None and (not isinstance(self.bench_size, int) or self.bench_size < 1):
            raise SchemaError(f"bench_size must be a positive int or None, got {self.bench_size!r}")
        bad = set(self.zones) - set(ZONES)
        if bad:
            raise SchemaError(f"unknown zone(s) {sorted(bad)}; allowed {ZONES}")


@dataclass
class Hit(_Record):
    """One candidate returned by m1_index.search(): relevance only, no other signal (owner: M1)."""

    doc_id: str
    rel: float  # BM25 (or lnc.ltc) score, raw and unbounded; M4 normalises it
    zone_scores: dict[str, float] = field(default_factory=dict)  # per-zone contribution, keys from ZONES

    def validate(self) -> None:
        if not self.doc_id:
            raise SchemaError("doc_id must be non-empty")
        if isinstance(self.rel, bool) or not isinstance(self.rel, (int, float)):
            raise SchemaError(f"rel must be a number, got {self.rel!r}")
        bad = set(self.zone_scores) - set(ZONES)
        if bad:
            raise SchemaError(f"unknown zone(s) {sorted(bad)}; allowed {ZONES}")


# --------------------------------------------------------------------------------------------------
# M2: statutes
# --------------------------------------------------------------------------------------------------
@dataclass
class StatuteRef(_Record):
    """A statute mention: one element of doc_statutes.jsonl `refs` (owner: M2)."""

    act: str  # one of ACTS, or "UNKNOWN" when a bare "Section N" could not be resolved
    section: str  # kept as a string: "302", "3(5)", "498A"
    offence_id: str | None = None  # OFF_<NAME>, e.g. OFF_MURDER; None when unmapped
    count: int = 1
    zone: str | None = None  # zone the mention occurs in

    def validate(self) -> None:
        _check_in(self.act, ACTS + ("UNKNOWN",), "act")
        if not self.section:
            raise SchemaError("section must be non-empty")
        if self.offence_id is not None and not self.offence_id.startswith(OFFENCE_ID_PREFIX):
            raise SchemaError(f"offence_id must start with {OFFENCE_ID_PREFIX!r}, got {self.offence_id!r}")
        if self.zone is not None:
            _check_in(self.zone, ZONES, "zone")


@dataclass
class DocStatutes(_Record):
    """One line of data/processed/doc_statutes.jsonl (owner: M2)."""

    doc_id: str
    refs: list[StatuteRef]

    def to_dict(self) -> dict[str, Any]:
        return {"doc_id": self.doc_id, "refs": [r.to_dict() for r in self.refs]}

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "DocStatutes":
        unknown = set(data) - {"doc_id", "refs"}
        if unknown:
            raise SchemaError(f"DocStatutes: unknown field(s) {sorted(unknown)}")
        return cls(doc_id=data["doc_id"], refs=[StatuteRef.from_dict(r) for r in data["refs"]])


@dataclass
class StatuteMapRow(_Record):
    """One row of data/statute_map.csv (owner: M2). Split/merge are many-to-many: one row per (old, new) pair."""

    old_act: str
    old_section: str
    new_act: str
    new_section: str
    relation: str
    weight: float
    source: str  # two independent sources, recorded
    note: str = ""

    def validate(self) -> None:
        _check_in(self.old_act, ACTS, "old_act")
        _check_in(self.new_act, ACTS, "new_act")
        _check_in(self.relation, RELATIONS, "relation")
        _check_unit(self.weight, "weight")
        if not self.source:
            raise SchemaError("source must be recorded for every mapping row")


@dataclass
class QueryStatutes(_Record):
    """Output of m2_statute.parse_query() (owner: M2). Proposed fields, see DECISIONS.md D-004."""

    query: str
    offence_date: str | None  # as supplied by the user
    governing_act: str | None  # the code that applies to the offence date, or an explicit act; None if unknown
    refs: list[StatuteRef] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)  # e.g. "collision: bare 302 resolved to IPC by offence date"

    @property
    def offence_ids(self) -> list[str]:
        return sorted({r.offence_id for r in self.refs if r.offence_id})

    def validate(self) -> None:
        _check_iso_date(self.offence_date, "offence_date", optional=True)
        if self.governing_act is not None:
            _check_in(self.governing_act, ACTS, "governing_act")

    def to_dict(self) -> dict[str, Any]:
        return {
            "query": self.query,
            "offence_date": self.offence_date,
            "governing_act": self.governing_act,
            "refs": [r.to_dict() for r in self.refs],
            "notes": list(self.notes),
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "QueryStatutes":
        unknown = set(data) - {"query", "offence_date", "governing_act", "refs", "notes"}
        if unknown:
            raise SchemaError(f"QueryStatutes: unknown field(s) {sorted(unknown)}")
        obj = cls(
            query=data["query"],
            offence_date=data.get("offence_date"),
            governing_act=data.get("governing_act"),
            refs=[StatuteRef.from_dict(r) for r in data.get("refs", [])],
            notes=list(data.get("notes", [])),
        )
        obj.validate()
        return obj


# --------------------------------------------------------------------------------------------------
# M3: citations and treatment
# --------------------------------------------------------------------------------------------------
@dataclass
class Citation(_Record):
    """One line of data/processed/citations.jsonl: an edge of the citation graph (owner: M3)."""

    citing_doc: str
    cited_doc: str | None  # None when the citation could not be resolved: never dropped, counted
    cited_raw: str  # the citation string as it appears in the text
    window: str  # the citing sentence +/- 1-2 sentences
    is_appeal_history: bool  # the cited case is the judgment under appeal: a reversal, not an overruling
    label: str  # one of TREATMENT_LABELS
    confidence: float
    citing_bench: int | None
    cited_bench: int | None
    valid_negative: bool  # a negative label that survived the bench check (citing bench >= cited bench)

    def validate(self) -> None:
        _check_in(self.label, TREATMENT_LABELS, "label")
        _check_unit(self.confidence, "confidence")


@dataclass
class DocHealth(_Record):
    """One line of data/processed/doc_health.jsonl (owner: M3)."""

    doc_id: str
    health: float  # [0, 1]; lowered by a valid later negative treatment
    authority: float  # [0, 1]; PageRank over positive/neutral edges x bench strength, normalised
    evidence: list[Evidence] = field(default_factory=list)

    def validate(self) -> None:
        _check_unit(self.health, "health")
        _check_unit(self.authority, "authority")
        for item in self.evidence:
            check_evidence(item)


@dataclass
class GoldWindow(_Record):
    """One row of data/treatment_gold.csv: a hand-labelled citation window (owner: M3)."""

    window_id: str
    window: str
    gold_label: str
    labeller: str  # a handle such as "L1"/"L2"; two labellers on a subset give Cohen's kappa

    def validate(self) -> None:
        _check_in(self.gold_label, TREATMENT_LABELS, "gold_label")


def check_evidence(item: Any) -> None:
    """Validate one Evidence dict (used by DocHealth and by the contract checks)."""
    if not isinstance(item, dict) or set(item) < {"citing_doc", "label", "sentence"}:
        raise SchemaError(f"evidence item needs citing_doc, label, sentence; got {item!r}")
    _check_in(item["label"], TREATMENT_LABELS, "evidence label")


# --------------------------------------------------------------------------------------------------
# M4: ranking and evaluation
# --------------------------------------------------------------------------------------------------
@dataclass
class Query(_Record):
    """One line of eval/queries.jsonl (owner: M4). Written and judged by hand, never generated."""

    qid: str
    text: str
    offence_date: str | None  # ISO date or None
    split: str  # dev | test
    type: str  # A | B | C | D

    def validate(self) -> None:
        if not self.qid or not self.text:
            raise SchemaError("qid and text must be non-empty")
        _check_iso_date(self.offence_date, "offence_date", optional=True)
        _check_in(self.split, SPLITS, "split")
        _check_in(self.type, QUERY_TYPES, "type")


@dataclass
class Qrel(_Record):
    """One row of eval/qrels.tsv: a graded judgement (owner: M4)."""

    qid: str
    doc_id: str
    grade: int  # 2 = relevant and good law; 1 = relevant but law changed / criticised; 0 = irrelevant or overruled on the point

    def validate(self) -> None:
        _check_in(self.grade, GRADES, "grade")


@dataclass
class Result(_Record):
    """One ranked result from m4_rank.rank().

    Guide 4.3 fixes {doc_id, final, rel, cont, health, auth, explanation}. The last four fields are additive
    (they never replace a contract field): `evidence` feeds the demo, `raw` and `contributions` make the
    arithmetic checkable, `stubbed` makes any fixed-value signal visible to every consumer.
    """

    doc_id: str
    final: float
    rel: float  # normalised, [0, 1]
    cont: float
    health: float
    auth: float
    explanation: str
    evidence: list[Evidence] = field(default_factory=list)
    raw: dict[str, float] = field(default_factory=dict)  # signal values before normalisation
    contributions: dict[str, float] = field(default_factory=dict)  # weight x normalised value, sums to `final`
    stubbed: list[str] = field(default_factory=list)  # signals served by fixed-value stubs, [] when all real

    def validate(self) -> None:
        for name in ("final", "rel", "cont", "health", "auth"):
            _check_unit(getattr(self, name), name)
        if not self.explanation:
            raise SchemaError("explanation must be non-empty")
