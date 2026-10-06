"""Case-citation extraction; writes data/processed/citations.jsonl together with resolver, windows and the classifier.

Formats: SCC, AIR, SCR, neutral citations (INSC), and "X v. Y" case names. Unresolved citations are kept with
cited_doc = null and counted, never silently dropped: report the resolution rate.

A *mention* is one place where a judgment refers to an earlier case. It has one of four kinds:
  full    a case name followed by one or more parallel reporter citations   "Bachan Singh v. State of Punjab (1980) 2 SCC 684"
  cite    reporter citation(s) with no name in front                        "(2014) 1 SCC 1 : [2013] 17 SCR 116"
  name    a case name with no citation                                     "Suresh Kumar Koushal & Anr. v. Naz Foundation & Ors."
  supra   a back-reference to a case named earlier in the same judgment    "Koushal (supra)"
  alias   a later short-form use of a case named earlier                   "The decision in Koushal stands overruled."
`supra` and `alias` mentions point at their antecedent mention and inherit its resolution. Treatment sentences in
Indian judgments mostly use these short forms, so without them most overrulings would never be seen.

All offsets refer to the cleaned text (m3_treatment.text.clean_text).
"""

from __future__ import annotations

import re
import sys
from bisect import bisect_right, insort
from dataclasses import dataclass, field

from m3_treatment.text import party_tokens, split_parties

# ----------------------------------------------------------------------------------------------------------------
# Reporter citations
# ----------------------------------------------------------------------------------------------------------------
_YEAR_BR = r"[\(\[]\s*(?P<y>1[89]\d\d|20\d\d)\s*[\)\]]"  # (2014) or [2014]
_YEAR_VOLP = r"(?P<y2>1[89]\d\d|20\d\d)\s*\(\s*(?P<v2>\d{1,2})\s*\)"  # 2010 (11)
_SUPPL = r"(?P<s>Supp(?:l)?\.?\s*(?:\(\s*\d\s*\)\s*)?)?"
_SCC = r"S\.?\s?C\.?\s?C\.?(?:\s*\((?:Cri|L\s*&\s*S|Civ)\))?"
_SCR = r"S\.?\s?C\.?\s?R\.?"
_PAGE = r"\s*(?P<p>\d{1,4})\b"

CITE_PATTERNS: list[tuple[str, re.Pattern[str]]] = [
    ("SCC_ONLINE", re.compile(r"[\(\[]?\s*(?P<y>20\d\d)\s*[\)\]]?\s*SCC\s*On\s*Line\s*(?P<c>SC|[A-Z][A-Za-z]{1,6})\s*(?P<p>\d{1,5})\b")),
    ("SCC", re.compile(_YEAR_BR + r"\s*(?P<v>\d{1,2})?\s*" + _SUPPL + _SCC + _PAGE)),
    ("SCC", re.compile(_YEAR_VOLP + r"\s*" + _SUPPL + _SCC + _PAGE)),
    ("SCR", re.compile(_YEAR_BR + r"\s*(?P<v>\d{1,2})?\s*" + _SUPPL + _SCR + _PAGE)),
    ("SCR", re.compile(_YEAR_VOLP + r"\s*" + _SUPPL + _SCR + _PAGE)),
    ("SCR", re.compile(r"(?<![\d\]\)])(?P<y>19[5-9]\d)\s+" + _SUPPL + _SCR + _PAGE)),  # older "1955 SCR 1"
    ("AIR", re.compile(r"A\.?\s?I\.?\s?R\.?\s*(?P<y>1[89]\d\d|20\d\d)\s*(?P<c>S\.\s?C\.|SC|Supreme\s+Court|[A-Z][A-Za-z]{1,10}\.?)\s*(?P<p>\d{1,5})\b")),
    ("INSC", re.compile(r"(?P<y>19\d\d|20\d\d)\s*:?\s*INSC\s*:?\s*(?P<p>\d{1,5})\b")),
    ("SCALE", re.compile(r"(?:" + _YEAR_VOLP + r"|" + _YEAR_BR + r"\s*(?P<v>\d{1,2}))\s*SCALE" + _PAGE)),
    ("JT", re.compile(r"JT\s*(?P<y>1[89]\d\d|20\d\d)\s*\(\s*(?P<v>\d{1,2})\s*\)\s*(?P<c>SC)?" + _PAGE)),
    ("CRILJ", re.compile(r"(?P<y>1[89]\d\d|20\d\d)\s*Cr(?:i|l)\.?\s*L\.?\s*J\.?" + _PAGE + r"(?:\s*\((?P<c>SC)\))?")),
]
# Reporters whose every citation is a Supreme Court decision.
SC_REPORTERS = frozenset({"SCC", "SCR", "INSC", "SCALE", "JT"})


@dataclass(frozen=True)
class Cite:
    """One reporter citation, normalised so the same report always yields the same key."""

    reporter: str  # SCC | SCR | AIR | INSC | SCC_ONLINE | SCALE | JT | CRILJ
    year: int
    volume: str  # "" when the format has none
    page: str
    suppl: bool
    court: str  # "SC" for this Court, else the reporter's court abbreviation ("Bom", "All"), "" if unknown
    start: int
    end: int

    @property
    def key(self) -> str:
        return cite_key(self.reporter, self.year, self.volume, self.page, self.suppl, self.court)

    @property
    def is_sc(self) -> bool:
        return self.reporter in SC_REPORTERS or self.court == "SC"


def cite_key(reporter: str, year: int, volume: str, page: str, suppl: bool, court: str = "") -> str:
    vol = str(int(volume)) if volume and volume.isdigit() else volume
    parts = [reporter, str(year), vol, "S" if suppl else "", str(int(page))]
    if reporter in ("AIR", "SCC_ONLINE"):
        parts[2] = court
    return "|".join(parts)


def _norm_court(raw: str | None, reporter: str) -> str:
    if reporter in SC_REPORTERS:
        return "SC"
    if not raw:
        return ""
    c = re.sub(r"[\s.]", "", raw)
    return "SC" if c.upper() in ("SC", "SUPREMECOURT") else c


def find_cites(text: str) -> list[Cite]:
    """Every reporter citation in `text`, left to right, without overlaps (the longest match wins)."""
    found: list[Cite] = []
    for reporter, pat in CITE_PATTERNS:
        for m in pat.finditer(text):
            g = m.groupdict()
            year = int(g.get("y") or g.get("y2"))
            volume = g.get("v") or g.get("v2") or ""
            found.append(
                Cite(
                    reporter=reporter,
                    year=year,
                    volume=volume,
                    page=g["p"],
                    suppl=bool(g.get("s")),
                    court=_norm_court(g.get("c"), reporter),
                    start=m.start(),
                    end=m.end(),
                )
            )
    found.sort(key=lambda c: (c.start, -(c.end - c.start)))
    out: list[Cite] = []
    for c in found:
        if out and c.start < out[-1].end:
            continue
        out.append(c)
    return out


def parse_cite(raw: str) -> Cite | None:
    """The first citation in a metadata string such as "[2018] 10 S.C.R. 1005" (None if there is none)."""
    cites = find_cites(raw)
    return cites[0] if cites else None


# ----------------------------------------------------------------------------------------------------------------
# Case names
# ----------------------------------------------------------------------------------------------------------------
# "V." is left out on purpose: in "Manoj V. George" it is an initial, not a separator.
_SEPARATOR = re.compile(r"\s(?:v\.|vs\.?|v/s\.?|versus|Vs\.?|VS\.?|VERSUS)\s")
_TOKEN = re.compile(r"\S+")
_FOOTNOTE_DIGITS = re.compile(r"(?<=[A-Za-z.)])\d{1,3}$")
CONNECTORS = frozenset("of and the alias @ & through thr. thr by for in re: de da bin d/o s/o w/o rep. etc. since others another".split())
# Abbreviations that end with a full stop inside a party name ("Mohd. Arif", "& Ors.", "Pvt. Ltd.").
NAME_ABBREVIATIONS = frozenset(
    "ors anr ltd pvt co corpn smt shri sh thr govt dist distt mohd md bros dr mr mrs ms jr sr retd sqn ldr col capt lt maj gen prof km st".split()
)
# Capitalised words that follow a name in running text but are not part of it ("... State of Maharashtra Decided on").
TRAIL_WORDS = frozenset(
    "decided held reported dated para paras judgment order supra referred relied followed overruled distinguished approved also where which wherein that this the it he she they we".split()
)
# Capitalised words that start a sentence or name a court rather than a party; stripped from the left edge.
LEAD_WORDS = frozenset(
    """in see also vide cf. cf the further similarly this that thus then hence as where recently followed relying
    reliance court judgment decision case bench supreme apex hon'ble learned para paras per however but although
    while when if accordingly therefore moreover after before since on at by and of re: re""".split()
)
MAX_LEFT, MAX_RIGHT = 9, 12


def _clean_tok(tok: str) -> str:
    return _FOOTNOTE_DIGITS.sub("", tok)


def _is_name_word(tok: str) -> bool:
    t = tok.strip("\"'“”‘’")
    if not t:
        return False
    if t.lower() in CONNECTORS:
        return True
    return t[0].isupper() or t.startswith(("M/s", "@", "(Dead", "(D)"))


def _left_name(text: str, sep_start: int) -> int | None:
    """Start offset of the petitioner side ending just before `sep_start`, or None."""
    toks = list(_TOKEN.finditer(text, max(0, sep_start - 200), sep_start))
    start = None
    for m in reversed(toks[-MAX_LEFT:]):
        tok = _clean_tok(m.group())
        if tok.endswith((",", ";", ":", "]")) or tok[:1] in "([" or tok[:1].isdigit() or not _is_name_word(tok):
            break
        if tok.endswith(".") and start is not None:
            # A full stop before the name, unless it is an abbreviation or an initial, ends the previous sentence.
            word = tok.rstrip(".").lower()
            if len(word) > 3 and word not in NAME_ABBREVIATIONS:
                break
        start = m.start()
    if start is None:
        return None
    # strip sentence-initial words and connectors from the left edge
    while True:
        m = _TOKEN.match(text, start)
        if not m or m.end() >= sep_start:
            break
        if m.group().lower() in LEAD_WORDS or m.group().lower() in CONNECTORS:
            nxt = _TOKEN.search(text, m.end(), sep_start)
            if not nxt:
                return None
            start = nxt.start()
            continue
        break
    return start if any(c.isupper() for c in text[start:sep_start]) else None


def _right_name(text: str, sep_end: int) -> int | None:
    """End offset of the respondent side starting at `sep_end`, or None."""
    end = None
    for i, m in enumerate(_TOKEN.finditer(text, sep_end, min(len(text), sep_end + 250))):
        if i >= MAX_RIGHT:
            break
        raw = m.group()
        tok = _clean_tok(raw)
        if tok[:1] in "([" or tok[:1].isdigit() or not _is_name_word(tok):
            break
        end = m.start() + len(tok.rstrip(",;:")) if tok != raw or tok.endswith((",", ";", ":")) else m.end()
        if tok.endswith((",", ";", ":")) or tok != raw:
            break
        if tok.endswith(".") and tok.rstrip(".").lower() not in NAME_ABBREVIATIONS and len(tok) > 4:
            end -= 1  # the full stop ends the sentence, it is not part of the name
            break
    if end is None:
        return None
    # strip trailing connectors ("State of Punjab in which" -> "State of Punjab")
    while True:
        last = list(_TOKEN.finditer(text, sep_end, end))
        word = last[-1].group().lower().rstrip(",;:.") if last else ""
        if last and (word in CONNECTORS - {"&", "@", "others", "another"} or word in TRAIL_WORDS):
            end = last[-2].end() if len(last) > 1 else None
            if end is None:
                return None
            continue
        break
    return end


@dataclass
class NameSpan:
    start: int
    end: int
    name: str


def find_case_names(text: str) -> list[NameSpan]:
    """"X v. Y" case names (also "vs.", "versus") with both sides bounded by capitalised party words."""
    out: list[NameSpan] = []
    for m in _SEPARATOR.finditer(text):
        lo = _left_name(text, m.start())
        hi = _right_name(text, m.end())
        if lo is None or hi is None or hi <= m.end():
            continue
        if out and lo < out[-1].end:
            continue
        out.append(NameSpan(lo, hi, text[lo:hi].strip()))
    return out


_SUPRA = re.compile(r"\(?\s*supra\s*\)?", re.IGNORECASE)


def find_supra(text: str) -> list[NameSpan]:
    """"Koushal (supra)", "Tika Ram (supra)", "Re: Cauvery Water Disputes Tribunal(supra)": the name before "supra"."""
    out: list[NameSpan] = []
    for m in _SUPRA.finditer(text):
        if "supra" not in m.group().lower():
            continue
        name_end = m.start()
        while name_end > 0 and text[name_end - 1] in " ,":
            name_end -= 1
        lo = _left_name(text, name_end)
        if lo is None or lo >= name_end:
            continue
        name = text[lo:name_end].strip(" ,")
        if not party_tokens(name):
            continue
        out.append(NameSpan(lo, m.end(), name))
    return out


# ----------------------------------------------------------------------------------------------------------------
# Mentions
# ----------------------------------------------------------------------------------------------------------------
@dataclass
class Mention:
    start: int
    end: int
    kind: str  # full | cite | name | supra | alias
    name: str = ""
    cites: list[Cite] = field(default_factory=list)
    antecedent: int | None = None  # index of the mention a supra/alias refers back to

    @property
    def year(self) -> int | None:
        return min((c.year for c in self.cites), default=None)

    def raw(self, text: str) -> str:
        return text[self.start : self.end]


_ATTACH_GAP = re.compile(r"^[\s,:]{0,4}$")
_PARALLEL_GAP = re.compile(r"^[\s:=,]{0,5}$")
# Common given names and surnames: too ambiguous to stand alone as a short form of a case name.
COMMON_NAME_WORDS = frozenset(
    """singh kumar lal ram devi prasad das khan ali ahmed ahmad mohd mohammad mohammed sharma gupta verma yadav reddy rao
    nair pillai patel shah jain mishra tiwari pandey chand nath bai begum bibi sahu babu raj kumari rani shri sri
    state union india court high supreme government board commissioner corporation bank company municipal council
    limited private public society trust india's""".split()
)
_GOV_WORDS = frozenset("state union india government govt commissioner collector director secretary cbi".split())


def _attach_cites(text: str, start: int, cites: list[Cite], i: int) -> tuple[list[Cite], int]:
    """Cites beginning right after offset `start` (index i onward), chained through parallel-citation separators."""
    got: list[Cite] = []
    pos = start
    while i < len(cites) and cites[i].start >= pos:
        gap = text[pos : cites[i].start]
        if not (_ATTACH_GAP if not got else _PARALLEL_GAP).match(gap):
            break
        got.append(cites[i])
        pos = cites[i].end
        i += 1
    return got, i


def alias_phrases(name: str) -> list[str]:
    """Short forms a judgment may use for a case after first naming it in full.

    The petitioner side (or the respondent side when the petitioner is the government) without "& Ors.", and its last
    word when that word is distinctive (five letters or more, not a common given name or surname).
    """
    pet, resp = split_parties(name)
    side = resp if party_tokens(pet) & {"state", "union", "government", "govt"} else pet
    side = re.sub(r"\s*(?:&|and)\s*(?:Ors|Anr|Others|Another)\.?\s*$", "", side.strip(), flags=re.IGNORECASE).strip(" .,")
    words = [w for w in re.findall(r"[A-Za-z][A-Za-z'\-]+", side)]
    toks = party_tokens(side)
    phrases: list[str] = []
    if len(toks) >= 2 and not toks & _GOV_WORDS:
        phrases.append(side)
    informative = [w for w in words if w.lower() in toks]
    if informative:
        last = informative[-1]
        if len(last) >= 5 and last.lower() not in COMMON_NAME_WORDS and last.lower() not in _GOV_WORDS:
            phrases.append(last)
    return phrases


class _Taken:
    """Non-overlapping character spans already claimed by a mention, with O(log n) overlap tests."""

    def __init__(self, spans: list[tuple[int, int]]):
        self.spans = sorted(spans)

    def overlaps(self, lo: int, hi: int) -> bool:
        i = bisect_right(self.spans, (lo, float("inf")))
        if i > 0 and self.spans[i - 1][1] > lo:
            return True
        return i < len(self.spans) and self.spans[i][0] < hi

    def add(self, lo: int, hi: int) -> None:
        insort(self.spans, (lo, hi))


_WORD_TOKEN = re.compile(r"[A-Za-z][A-Za-z'\-]*")


def _phrase_occurrences(text: str, phrases: set[str]) -> dict[str, list[tuple[int, int]]]:
    """Capitalised occurrences of each phrase (Title Case or UPPER CASE words), found through a word-position index."""
    toks = [(m.start(), m.end(), m.group()) for m in _WORD_TOKEN.finditer(text)]
    where: dict[str, list[int]] = {}
    for i, (_, _, w) in enumerate(toks):
        where.setdefault(w.lower(), []).append(i)
    out: dict[str, list[tuple[int, int]]] = {}
    for phrase in phrases:
        words = [w.lower() for w in _WORD_TOKEN.findall(phrase)]
        if not words:
            continue
        hits = []
        for i in where.get(words[0], []):
            seq = toks[i : i + len(words)]
            if len(seq) == len(words) and all(t[2].lower() == w and t[2][0].isupper() for t, w in zip(seq, words)):
                hits.append((seq[0][0], seq[-1][1]))
        out[phrase] = hits
    return out


def _latest_before(cands: list[Mention], pos: int) -> Mention | None:
    """The latest candidate ending before `pos`, preferring one that carries a reporter citation."""
    before = [m for m in cands if m.end <= pos]
    if not before:
        return None
    cited = [m for m in before if m.cites]
    return (cited or before)[-1]


def extract_mentions(text: str) -> list[Mention]:
    """All mentions in `text` (already cleaned), left to right, with supra/alias mentions linked to their antecedent."""
    cites = find_cites(text)
    mentions: list[Mention] = []
    used = [False] * len(cites)

    # full and name mentions
    ci = 0
    for n in find_case_names(text):
        while ci < len(cites) and cites[ci].start < n.end:
            ci += 1
        attached, nxt = _attach_cites(text, n.end, cites, ci)
        for k in range(ci, nxt):
            used[k] = True
        end = attached[-1].end if attached else n.end
        mentions.append(Mention(n.start, end, "full" if attached else "name", n.name, attached))
        ci = nxt

    # cites with no name in front, grouped into parallel chains
    i = 0
    while i < len(cites):
        if used[i]:
            i += 1
            continue
        chain, _ = _attach_cites(text, cites[i].start, cites, i)
        chain = chain or [cites[i]]
        for k in range(i, i + len(chain)):
            used[k] = True
        mentions.append(Mention(chain[0].start, chain[-1].end, "cite", "", chain))
        i += len(chain)
    mentions.sort(key=lambda m: m.start)
    named = [m for m in mentions if m.kind in ("full", "name") and m.name]

    # Back-references are linked by object first and turned into indices once the final order is known.
    links: dict[int, Mention] = {}
    taken = _Taken([(m.start, m.end) for m in mentions])
    new: list[Mention] = []

    # supra: linked to the latest earlier named mention containing all of their tokens
    tokens_of = {id(m): party_tokens(m.name) for m in named}
    for s in find_supra(text):
        if taken.overlaps(s.start, s.end):
            continue
        want = party_tokens(s.name)
        ante = _latest_before([m for m in named if want <= tokens_of[id(m)]], s.start) if want else None
        m = Mention(s.start, s.end, "supra", s.name)
        if ante is not None:
            links[id(m)] = ante
        new.append(m)
        taken.add(s.start, s.end)

    # alias: later short-form uses of a case named earlier ("in Koushal", "Bachan Singh held")
    by_phrase: dict[str, list[Mention]] = {}
    for m in named:
        for phrase in alias_phrases(m.name):
            by_phrase.setdefault(phrase, []).append(m)
    occurrences = _phrase_occurrences(text, set(by_phrase))
    for phrase in sorted(by_phrase, key=len, reverse=True):  # "Suresh Kumar Koushal" before "Koushal"
        for lo, hi in occurrences.get(phrase, []):
            if taken.overlaps(lo, hi):
                continue
            ante = _latest_before(by_phrase[phrase], lo)
            if ante is None:
                continue
            m = Mention(lo, hi, "alias", phrase)
            links[id(m)] = ante
            new.append(m)
            taken.add(lo, hi)

    mentions = sorted(mentions + new, key=lambda m: m.start)
    index = {id(m): i for i, m in enumerate(mentions)}
    for m in mentions:
        if id(m) in links:
            m.antecedent = index[id(links[id(m)])]
    return mentions


def extract_citations(text: str) -> list[dict]:
    """Raw citation mentions with their character spans, before resolution and classification.

    `text` must already be cleaned with m3_treatment.text.clean_text; offsets refer to it.
    """
    return [
        {
            "start": m.start,
            "end": m.end,
            "kind": m.kind,
            "name": m.name,
            "cited_raw": m.raw(text),
            "cites": [c.key for c in m.cites],
            "year": m.year,
            "antecedent": m.antecedent,
        }
        for m in extract_mentions(text)
    ]


def main(argv: list[str] | None = None) -> int:
    """`python -m m3_treatment.citations build`: extract mentions, then write citations.jsonl from the labels."""
    from m3_treatment.pipeline import main as pipeline_main

    args = list(argv if argv is not None else sys.argv[1:])
    if not args or args[0] != "build":
        print("usage: python -m m3_treatment.citations build [--labels llm|baseline]")
        return 2
    return pipeline_main(["extract"]) or pipeline_main(["citations", *args[1:]])


if __name__ == "__main__":
    sys.exit(main())
