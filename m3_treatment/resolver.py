"""Resolve a raw citation to a corpus doc_id.

First choice: metadata (reporter_citations). Fallback: Jaccard similarity on party-name tokens plus the year.
IR concept: Jaccard coefficient.

Three steps, most reliable first:
  1. exact reporter key: every citation string in a judgment's `reporter_citations` (and the INSC number in its
     doc_id) is normalised with the same parser as the text, so "[2013] 17 S.C.R. 116" and "[2013] 17 SCR 116" meet;
  2. SCR page range: the dataset's doc_id is "<year>_<volume>_<first page>_<last page>" of the Supreme Court Reports,
     so a pinpoint citation such as "[2013] 17 SCR 120" falls inside exactly one report. Misprinted pages exist, so
     a range match is kept only when the mention also names the case and the names agree;
  3. party names: Jaccard on party-name tokens, restricted to the cited year +/- 1. Tokens that occur in too many
     titles ("state", "india", "singh") form a corpus stop list (document frequency over the titles, as in an inverted
     index); the stop-listed "informative" tokens give the candidate set and a second Jaccard gate. Ties or near-ties
     are left unresolved rather than guessed.
"""

from __future__ import annotations

import re
from bisect import bisect_right
from dataclasses import dataclass
from functools import lru_cache
from typing import Iterable

from m3_treatment.citations import Cite, cite_key, find_cites, find_case_names
from m3_treatment.text import jaccard, party_tokens

# The dataset's file stem is "<year>_<volume>_<first page>_<last page>_<language>" (for example 2025_1_1_11_EN); M1 keeps the
# whole stem as doc_id, so an optional language suffix is allowed.
_PATH_ID = re.compile(r"^(?P<y>\d{4})_(?P<v>\d+)_(?P<a>\d+)_(?P<b>\d+)(?:_[A-Za-z]{2,3})?$")
_YEAR = re.compile(r"\b(1[89]\d\d|20\d\d)\b")


def year_of(date: str | None) -> int | None:
    """The year in a date string of any common shape: 2025-01-02, 02 January 2025, 11-12-2013 (None if there is none)."""
    m = _YEAR.search(date or "")
    return int(m.group(1)) if m else None
DEFAULTS = {
    "name_threshold": 0.5,  # Jaccard needed when the citation year is known
    "name_threshold_no_year": 0.75,  # stricter when it is not (name-only mentions)
    "ambiguity_margin": 0.1,  # best must beat the runner-up by this much
    "year_window": 1,  # report year and decision year differ by up to a year
    "max_token_df": 0.02,  # a title token in more than this share of titles is a stop word ...
    "min_stop_df": 5,  # ... once it occurs in at least this many titles
    "range_name_agreement": 0.3,  # an SCR page-range match is kept only if the cited name (when given) agrees
}


@dataclass(frozen=True)
class DocMeta:
    doc_id: str
    title: str
    year: int | None
    bench: int | None


@dataclass(frozen=True)
class Resolution:
    doc_id: str | None
    method: str  # cite | scr_range | name | none
    score: float = 1.0


# The coram line printed under the title in the Supreme Court Reports:
#   "[MADAN B. LOKUR, S. ABDUL NAZEER AND DEEPAK GUPTA, JJ.]", "[DIPAK MISRA, CJI, R.F. NARIMAN ... AND INDU MALHOTRA, JJ.]"
_CORAM = re.compile(r"\[([^\[\]]{3,500}?),?\s*(?:JJ|J|CJI)\.?\s*\]")
_CORAM_SPLIT = re.compile(r",|\band\b", re.IGNORECASE)
CORAM_HEAD_CHARS = 6000


_AUTHORSHIP_NOTE = re.compile(r"\b(?:for|on\s+behalf\s+of)\s+(?:himself|herself|self|myself|the\s+bench|the\s+court)\b", re.IGNORECASE)


def bench_from_text(text: str) -> int | None:
    """Number of judges on the coram line near the top of the judgment ("CJI" is a title, not another judge).

    Two printed shapes exist: the older all-capitals "[DIPAK MISRA, CJI, R.F. NARIMAN ... AND INDU MALHOTRA, JJ.]" and the
    recent mixed-case "[C.T. Ravikumar* and Sanjay Kumar, JJ.]" (an asterisk marks the author).
    """
    best = None
    for m in _CORAM.finditer(re.sub(r"\s+", " ", text[:CORAM_HEAD_CHARS])):
        body = m.group(1).replace("*", "")
        if _AUTHORSHIP_NOTE.search(body):
            continue  # "[for himself and Khanwilkar, J.]" is an authorship note, not the coram
        names = [n.strip() for n in _CORAM_SPLIT.split(re.sub(r"\bCJI\b", "", body)) if re.search(r"[A-Za-z]{2}", n)]
        if names and (best is None or len(names) > best):
            best = len(names)
    return best


def bench_of(rec: dict) -> int | None:
    """bench_size from M1, else the number of judges listed, else the coram line in the text, else None.

    Never guessed: the coram line is the reporter's own list of the judges on the bench.
    """
    if rec.get("bench_size"):
        return int(rec["bench_size"])
    judges = rec.get("judges") or []
    if len(judges) > 1:
        return len(judges)  # a single name may be only the author (the dataset's `judge` field)
    return bench_from_text(rec.get("text") or "")


def metadata_view(rec: dict) -> dict:
    """The fields the index needs, with only the head of the text (for the coram line), to keep memory small."""
    keep = ("doc_id", "title", "date", "bench_size", "judges", "reporter_citations")
    return {**{k: rec.get(k) for k in keep}, "text": (rec.get("text") or "")[:CORAM_HEAD_CHARS]}


class CorpusIndex:
    """Lookup tables over judgments.jsonl metadata for citation resolution."""

    def __init__(self, judgments: Iterable[dict], **params):
        self.p = {**DEFAULTS, **{k: v for k, v in params.items() if v is not None}}
        self.meta: dict[str, DocMeta] = {}
        self.by_key: dict[str, set[str]] = {}
        self._ranges: dict[tuple[int, str], list[tuple[int, int, str]]] = {}
        titles: dict[str, set[str]] = {}
        for rec in judgments:
            doc_id = rec["doc_id"]
            year = year_of(rec.get("date"))
            self.meta[doc_id] = DocMeta(doc_id, rec.get("title", ""), year, bench_of(rec))
            for raw in rec.get("reporter_citations") or []:
                for c in find_cites(raw):
                    self.by_key.setdefault(c.key, set()).add(doc_id)
            m = _PATH_ID.match(doc_id)
            if m:
                y, v, a, b = int(m["y"]), m["v"], int(m["a"]), int(m["b"])
                self.by_key.setdefault(cite_key("SCR", y, v, str(a), False), set()).add(doc_id)
                self._ranges.setdefault((y, str(int(v))), []).append((a, b, doc_id))
            titles[doc_id] = party_tokens(rec.get("title", ""))
        for spans in self._ranges.values():
            spans.sort()
        n = max(1, len(titles))
        df: dict[str, int] = {}
        for toks in titles.values():
            for t in toks:
                df[t] = df.get(t, 0) + 1
        self.stopwords = frozenset(t for t, c in df.items() if c >= self.p["min_stop_df"] and c / n > self.p["max_token_df"])
        self.full_tokens = titles
        self.title_tokens = {d: toks - self.stopwords for d, toks in titles.items()}
        self.postings: dict[str, list[str]] = {}
        for d, toks in self.title_tokens.items():
            for t in toks:
                self.postings.setdefault(t, []).append(d)

    def __contains__(self, doc_id: str) -> bool:
        return doc_id in self.meta

    # -- step 1 and 2 --------------------------------------------------------------------------------------------
    def resolve_cites(self, cites: list[Cite]) -> Resolution:
        votes: dict[str, str] = {}
        for c in cites:
            docs = self.by_key.get(c.key, set())
            if len(docs) == 1:
                votes.setdefault(next(iter(docs)), "cite")
        if not votes:
            for c in cites:
                d = self._in_scr_range(c)
                if d:
                    votes.setdefault(d, "scr_range")
        if len(votes) == 1:
            doc_id, method = next(iter(votes.items()))
            return Resolution(doc_id, method)
        return Resolution(None, "none")  # nothing, or parallel citations that disagree

    def _in_scr_range(self, c: Cite) -> str | None:
        if c.reporter != "SCR" or c.suppl or not c.volume:
            return None
        spans = self._ranges.get((c.year, str(int(c.volume))), [])
        page = int(c.page)
        i = bisect_right(spans, (page, float("inf"), "")) - 1
        if i >= 0 and spans[i][0] <= page <= spans[i][1]:
            return spans[i][2]
        return None

    # -- step 3 -------------------------------------------------------------------------------------------------
    def resolve_name(self, name: str, year: int | None = None) -> Resolution:
        """Both the full party tokens and the informative ones (corpus stop words removed) must agree.

        The full-token Jaccard is the score; the informative-token Jaccard is a second gate, so a shared common word
        cannot carry a match ("Ram Singh v. State of Haryana" vs "Ram Kumar v. State of Haryana"), and a lone rare word
        cannot either ("Sushil Kumar v. State of Punjab" vs "Sushil Sharma v. State of NCT of Delhi").
        """
        full = party_tokens(name)
        want = full - self.stopwords
        if not want:
            return Resolution(None, "none", 0.0)
        cands = {d for t in want for d in self.postings.get(t, ())}
        if year is not None:
            w = self.p["year_window"]
            cands = {d for d in cands if self.meta[d].year is not None and abs(self.meta[d].year - year) <= w}
        need = self.p["name_threshold"] if year is not None else self.p["name_threshold_no_year"]
        scored = sorted(
            ((jaccard(full, self.full_tokens[d]), d) for d in cands if jaccard(want, self.title_tokens[d]) >= need),
            reverse=True,
        )
        if not scored:
            return Resolution(None, "none", 0.0)
        best, doc_id = scored[0]
        runner = scored[1][0] if len(scored) > 1 else 0.0
        if best >= need and best - runner >= self.p["ambiguity_margin"]:
            return Resolution(doc_id, "name", round(best, 4))
        return Resolution(None, "none", round(best, 4))

    def resolve(self, cites: list[Cite], name: str = "", year: int | None = None) -> Resolution:
        r = self.resolve_cites(cites) if cites else Resolution(None, "none")
        if r.method == "scr_range" and not (name and self._names_agree(name, r.doc_id)):
            # A page range catches pinpoint cites but also misprinted pages (the SCR prints Koushal as both
            # "[2013] 17 SCR 116" and "[2013] 17 SCR 1019"), so a range match needs a cited name that agrees.
            r = Resolution(None, "none")
        if r.doc_id is None and name:
            r = self.resolve_name(name, year)
        return r

    def _names_agree(self, name: str, doc_id: str) -> bool:
        return jaccard(party_tokens(name), self.full_tokens[doc_id]) >= self.p["range_name_agreement"]


@lru_cache(maxsize=1)
def default_index() -> CorpusIndex:
    """CorpusIndex over data/processed/judgments.jsonl (metadata only), built once per process."""
    from common.config import load_config, resolve_path
    from common.io import read_jsonl

    cfg = load_config().get("m3_treatment", {}).get("resolver", {})
    recs = (metadata_view(r) for r in read_jsonl(resolve_path("judgments")))
    return CorpusIndex(recs, **cfg)


def resolve(cited_raw: str, year: int | None = None) -> str | None:
    """doc_id, or None if unresolved."""
    cites = find_cites(cited_raw)
    names = find_case_names(cited_raw)
    name = names[0].name if names else cited_raw
    year = year if year is not None else min((c.year for c in cites), default=None)
    return default_index().resolve(cites, name, year).doc_id
