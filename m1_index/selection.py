"""Which judgments of the dataset go into the LexShift corpus, and why. Corpus construction, never labelling.

The whole dataset is 43,327 English judgments and 22.6 GB. LexShift cannot hold or index all of it on a laptop (the live demo is offline and the index sits in
memory), and downloading it would take many hours on the connection this was built on, so the corpus is chosen from the catalog by rules that are written
down here and recorded in DECISIONS.md:

1. **Named cases.** Both ends of every doctrine the judged queries are about (an overruled case and the judgment that overruled it), read off the grading
   criteria (eval/examples/query_grade_criteria.example.md), and a few judgments the queries obviously touch. Matched on the catalog's title and year.
2. **A criminal-law base, newest first.** Every English judgment of the chosen years whose title looks like a criminal matter (the State, the CBI, a
   narcotics or enforcement body, the police) is downloaded and its text read; it stays in the corpus only if the text itself mentions the criminal codes
   (IPC, BNS, CrPC, BNSS, NDPS, ...). A second tier (all other titles) can be added when the coverage check says a query still has too little.

Nothing here looks at a relevance judgment: there are none, and none is ever used to choose a document.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Iterable

from m1_index.catalog import Entry


@dataclass(frozen=True)
class Named:
    label: str  # what it is
    doctrine: str  # the judged query it belongs to
    role: str  # overruled | overruling | related
    years: frozenset[int]
    title: re.Pattern[str]


def _n(label: str, doctrine: str, role: str, years: Iterable[int], pattern: str) -> Named:
    return Named(label, doctrine, role, frozenset(years), re.compile(pattern, re.I))


NAMED: tuple[Named, ...] = (
    _n("Suresh Kumar Koushal v. Naz Foundation", "section 377", "overruled", [2013], r"KOUSHAL"),
    _n("Navtej Singh Johar v. Union of India", "section 377", "overruling", [2018], r"NAVTEJ SINGH JOHAR"),
    _n("Sowmithri Vishnu v. Union of India", "adultery", "overruled", [1985], r"SOWMITHRI"),
    _n("V. Revathi v. Union of India", "adultery", "overruled", [1988], r"\bREVATHI\b.*UNION OF INDIA|^V\.? ?REVATHI"),
    _n("Joseph Shine v. Union of India", "adultery", "overruling", [2018], r"JOSEPH SHINE"),
    _n("ADM Jabalpur v. Shivkant Shukla", "privacy", "overruled", [1976], r"ADDITIONAL DISTRICT MAGISTRATE, JABALPUR"),
    _n("K.S. Puttaswamy v. Union of India", "privacy", "overruling", [2017], r"PUTTASWAMY"),
    _n("Salauddin Abdulsamad Shaikh v. State of Maharashtra", "anticipatory bail", "overruled", [1995, 1996], r"SALAUDDIN ABDULSAMAD"),
    _n("Siddharam Satlingappa Mhetre v. State of Maharashtra", "anticipatory bail", "overruled", [2010], r"SIDDHARAM SATLINGAPPA"),
    _n("Sushila Aggarwal v. State (NCT of Delhi)", "anticipatory bail", "overruling", [2018, 2020], r"SUSHILA AGGARWAL"),
    _n("Rajesh Sharma v. State of U.P.", "section 498A", "overruled", [2017], r"RAJESH SHARMA & ORS|RAJESH SHARMA AND ORS"),
    _n("Social Action Forum for Manav Adhikar v. Union of India", "section 498A", "overruling", [2018], r"SOCIAL ACTION FORUM FOR MANAV"),
    _n("Navjot Sandhu (Parliament attack case)", "electronic evidence", "overruled", [2005], r"NAVJOT SANDHU"),
    _n("Anvar P.V. v. P.K. Basheer", "electronic evidence", "overruling", [2014], r"ANVAR P"),
    _n("Shafhi Mohammad v. State of Himachal Pradesh", "electronic evidence", "overruled", [2018], r"SHAFHI MOHAMMAD"),
    _n("Tomaso Bruno v. State of U.P.", "electronic evidence", "overruled", [2015], r"TOMASO BRUNO"),
    _n("Arjun Panditrao Khotkar v. Kailash Kushanrao Gorantyal", "electronic evidence", "overruling", [2020], r"PANDITRAO"),
    _n("Kanhaiyalal v. Union of India", "NDPS section 67", "overruled", [2008], r"KANHAIYALAL"),
    _n("Raj Kumar Karwal v. Union of India", "NDPS section 67", "overruled", [1990], r"RAJ KUMAR KARWAL"),
    _n("Tofan Singh v. State of Tamil Nadu", "NDPS section 67", "overruling", [2013, 2020], r"TOFAN SINGH"),
    _n("Mohan Lal v. State of Punjab", "informant and investigator", "overruled", [2018], r"^MOHAN LAL versus"),
    _n("Mukesh Singh v. State (Narcotic Branch of Delhi)", "informant and investigator", "overruling", [2020], r"MUKESH SINGH versus STATE \(NARCOTIC"),
    _n("Asian Resurfacing of Road Agency v. CBI", "stay after six months", "overruled", [2018], r"ASIAN RESURFACING"),
    _n("High Court Bar Association, Allahabad v. State of U.P.", "stay after six months", "overruling", [2024], r"HIGH COURT BAR ASSOCIATION, ALLAHABAD"),
    _n("P. Rathinam v. Union of India", "attempt to commit suicide", "overruled", [1994], r"RATHINAM/NABHUSAN|P\. RATHINAM"),
    _n("Gian Kaur v. State of Punjab", "attempt to commit suicide", "overruling", [1996], r"GIAN KAUR ETC"),
    # not overruling pairs, but the judged queries are about them (sedition, mob lynching, arrest guidelines, bail)
    _n("Kedar Nath Singh v. State of Bihar", "sedition", "related", [1962], r"KEDAR NATH SINGH"),
    _n("Vinod Dua v. Union of India", "sedition", "related", [2021], r"VINOD DUA"),
    _n("Tehseen S. Poonawalla v. Union of India", "mob lynching", "related", [2018], r"TEHSEEN"),
    _n("Arnesh Kumar v. State of Bihar", "section 498A", "related", [2014], r"ARNESH KUMAR versus"),
    _n("Satender Kumar Antil v. CBI", "anticipatory bail", "related", [2022, 2024, 2025], r"SATENDER KUMAR ANTIL"),
)

# a title that looks like a criminal matter: the State, the CBI, a narcotics or enforcement body, the police
CRIMINAL_TITLE = re.compile(
    r"\bSTATE\b|CENTRAL BUREAU|\bC\.?B\.?I\b|NARCOTIC|ENFORCEMENT|POLICE|UNION TERRITORY|\bN\.?C\.?T\b|SPECIAL CELL|INTELLIGENCE|CUSTOMS|"
    r"NATIONAL INVESTIGATION|\bN\.?I\.?A\b|DIRECTORATE|CRIMINAL|GOVT\. OF|GOVERNMENT OF",
    re.I,
)

# the text itself: a criminal-law judgment mentions one of the criminal codes or statutes
CRIMINAL_TEXT = re.compile(
    # lookarounds, not \b: a name that ends in a full stop (Cr.P.C.) has no word boundary after it
    r"(?<!\w)(?:IPC|I\.P\.C\.|Indian\s+Penal\s+Code|Penal\s+Code|BNS|Bharatiya\s+Nyaya\s+Sanhita|CrPC|Cr\.\s?P\.\s?C\.|Code\s+of\s+Criminal\s+Procedure|"
    r"BNSS|Bharatiya\s+Nagarik\s+Suraksha\s+Sanhita|NDPS|Narcotic\s+Drugs|Prevention\s+of\s+Corruption|UAPA|Unlawful\s+Activities|"
    r"POCSO|Protection\s+of\s+Children\s+from\s+Sexual|Arms\s+Act|Dowry\s+Prohibition)(?!\w)",
    re.I,
)


def named_matches(entries: Iterable[Entry]) -> list[tuple[Named, Entry]]:
    out: list[tuple[Named, Entry]] = []
    for entry in entries:
        if entry.pdf_bytes is None:
            continue
        for n in NAMED:
            if entry.year in n.years and n.title.search(entry.title):
                out.append((n, entry))
    return out


def candidates(entries: Iterable[Entry], years: Iterable[int], tier: str = "criminal-title") -> list[Entry]:
    """English judgments of the given years: the criminal-looking titles (tier 'criminal-title') or every title (tier 'all')."""
    wanted = set(years)
    out = [e for e in entries if e.year in wanted and e.pdf_bytes is not None and (tier == "all" or CRIMINAL_TITLE.search(e.title))]
    return sorted(out, key=lambda e: (-e.year, e.path))


def is_criminal_text(text: str) -> bool:
    return bool(CRIMINAL_TEXT.search(text))
