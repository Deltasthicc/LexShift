"""Can the corpus answer a query at all? A counting tool for the person writing the judged queries. It never grades anything.

    python -m eval.feasibility                       # the queries in eval/queries.jsonl, else the 30 suggested candidates
    python -m eval.feasibility --queries my.jsonl    # any file in the queries.jsonl format
    python -m eval.feasibility --json

For each query it reports, from the real search and the corpus text:

* candidates   how many judgments the search returns for the query as written (the pool the systems rank);
* all terms    how many judgments contain EVERY content word (a Boolean AND over the stemmed words, through M1's own parser);
* sections     for each section number the query names, how many judgments mention "section N" (a plain regular expression over
               the text, deliberately independent of M2's extractor, whose errors would otherwise hide a gap).

A count says whether a query has anything to find. It does not say whether what is found is relevant or good law: only a person
reading the judgments can say that. The guidance in eval/JUDGING_GUIDE.md says what to do with a thin or empty count.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from collections import Counter
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Iterable, Sequence

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from common.config import load_config, resolve_path  # noqa: E402
from common.io import read_jsonl  # noqa: E402
from common.providers import Providers, load_providers  # noqa: E402
from common.schema import Query  # noqa: E402
from eval.loaders import EvalDataError, load_queries  # noqa: E402
from m4_rank.rank import ArtefactError, load_checked  # noqa: E402

EXAMPLES = ROOT / "eval" / "examples" / "queries.example.jsonl"
THIN = 3  # at most this many judgments: the query may still be usable, but recall will be a handful of documents
# Words that carry no subject matter. The code names matter: a type A query says "BNS 103" while the judgments that answer it were
# written under the IPC and never contain the word BNS, so requiring it would count the very documents the query is meant to reach.
_STOP = frozenset("""a an and are as at by for from in into is it of on or not the to under with who what which that this
                     section sections bns bnss ipc crpc code indian penal""".split())
_NUMBER = re.compile(r"(?<![A-Za-z0-9])(\d{1,3}[A-Za-z]?(?:\(\d+\))*)(?![A-Za-z0-9])")
_YEAR = re.compile(r"(?:19|20)\d{2}")


@dataclass
class Row:
    qid: str
    type: str
    split: str
    text: str
    offence_date: str | None
    candidates: int | None
    all_terms: int | None
    sections: dict[str, int] = field(default_factory=dict)
    verdict: str = ""
    note: str = ""


# ---------------------------------------------------------------------------------------------------------- pure logic
def content_terms(text: str, limit: int = 6) -> list[str]:
    """The query's content words, in order, without stop words, query operators or section numbers; at most `limit`."""
    seen: list[str] = []
    for word in re.findall(r"[A-Za-z]+", text.lower()):
        if word not in _STOP and len(word) > 1 and word not in seen:
            seen.append(word)
    return seen[:limit]


def section_numbers(text: str) -> list[str]:
    """Section numbers named in the query ("BNS 103", "section 80", "3(5)", "498A"), without duplicates."""
    out: list[str] = []
    for m in _NUMBER.finditer(text):
        number = m.group(1).upper()
        if number not in out and not _YEAR.fullmatch(number):
            out.append(number)
    return out


def mention_pattern(number: str) -> re.Pattern[str]:
    """`section 103`, `Sections 100, 103 and 105`, `s. 103`, `u/s 103`: the number as a section reference, not as a paragraph."""
    n = re.escape(number)
    lead = r"(?:sections?|secs?\.?|s\.|u/s\.?)\s*"
    more = r"(?:\d+[A-Za-z]?(?:\(\d+\))*\s*(?:,|and|&|/|to|-)\s*)*"
    return re.compile(rf"(?<![A-Za-z0-9]){lead}{more}{n}(?![A-Za-z0-9])", re.IGNORECASE)


def verdict(row: Row, corpus_years: Sequence[str]) -> tuple[str, str]:
    """A short reading of the counts. Counts only: never a statement about relevance."""
    notes: list[str] = []
    level = "ok"

    def worse(to: str) -> None:
        nonlocal level
        order = ("ok", "thin", "empty")
        if order.index(to) > order.index(level):
            level = to

    if row.candidates == 0:
        worse("empty")
        notes.append("the search returns nothing for this query as written")
    if row.all_terms is not None:
        if row.all_terms == 0:
            worse("empty")
            notes.append("no judgment contains every content word")
        elif row.all_terms <= THIN:
            worse("thin")
            notes.append(f"only {row.all_terms} judgment(s) contain every content word")
    for number, count in row.sections.items():
        if count == 0:
            worse("empty")
            notes.append(f"no judgment mentions section {number}")
        elif count <= THIN:
            worse("thin")
            notes.append(f"only {count} judgment(s) mention section {number}")
    if row.type == "C" and corpus_years and len(set(corpus_years)) == 1:
        worse("thin")
        notes.append(f"type C needs the overruled and the overruling judgment, and the corpus holds one year only ({corpus_years[0]})")
    return level, "; ".join(notes)


# ---------------------------------------------------------------------------------------------------------- corpus pass
def scan_corpus(path: Path, numbers: Iterable[str]) -> tuple[dict[str, int], Counter[str], int]:
    """One streaming pass: judgments mentioning each section number, judgments per year, and the number of judgments."""
    patterns = {n: mention_pattern(n) for n in set(numbers)}
    counts = {n: 0 for n in patterns}
    years: Counter[str] = Counter()
    total = 0
    for rec in read_jsonl(path):
        total += 1
        m = _YEAR.search(str(rec.get("date") or ""))
        years[m.group(0) if m else "unknown"] += 1
        text = rec.get("text") or ""
        for n, pattern in patterns.items():
            if pattern.search(text):
                counts[n] += 1
    return counts, years, total


def _count(providers: Providers, query: str, k: int) -> int | None:
    try:
        return len(providers.search(query, k))
    except (ValueError, IndexError, KeyError, NotImplementedError):
        return None  # a query the parser cannot read is reported as not counted, never as zero


def analyse(
    queries: Sequence[Query], providers: Providers, mention_counts: dict[str, int], years: Counter[str], k: int
) -> list[Row]:
    rows = []
    corpus_years = sorted(y for y in years if y != "unknown")
    for q in queries:
        terms = content_terms(q.text)
        row = Row(q.qid, q.type, q.split, q.text, q.offence_date, _count(providers, q.text, k),
                  _count(providers, " AND ".join(terms), k) if terms else None,
                  {n: mention_counts.get(n, 0) for n in section_numbers(q.text)})
        row.verdict, row.note = verdict(row, corpus_years)
        rows.append(row)
    return rows


def render(rows: Sequence[Row], years: Counter[str], total: int, source: str) -> str:
    year_text = ", ".join(f"{y}: {n}" for y, n in sorted(years.items())) or "none"
    out = [f"Corpus: {total} judgments ({year_text}). Queries from {source}.", "",
           f"{'qid':<7}{'type':<5}{'candidates':>11}{'all terms':>11}  {'verdict':<7} sections / note"]
    for r in rows:
        secs = ", ".join(f"s.{n}: {c}" for n, c in r.sections.items())
        shown = "n/a" if r.candidates is None else str(r.candidates)
        shown_all = "n/a" if r.all_terms is None else str(r.all_terms)
        tail = "; ".join(x for x in (secs, r.note) if x)
        out.append(f"{r.qid:<7}{r.type:<5}{shown:>11}{shown_all:>11}  {r.verdict:<7} {tail}")
    counts = Counter(r.verdict for r in rows)
    out += ["", f"{counts['ok']} ok, {counts['thin']} thin, {counts['empty']} empty.",
            "These are counts, not judgements: a query with plenty of documents can still have none that is relevant, and a thin "
            "one is not necessarily wrong. See eval/JUDGING_GUIDE.md, section 1."]
    return "\n".join(out)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--queries", help="queries file (default: eval/queries.jsonl, else the suggested examples)")
    ap.add_argument("-k", type=int, default=100, help="candidates counted per query (default 100, the re-ranking depth)")
    ap.add_argument("--json", action="store_true", help="print the rows as JSON")
    ap.add_argument("--strict", action="store_true", help="exit 1 when any query is empty")
    args = ap.parse_args(argv)
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(errors="replace")
    cfg = load_config()
    try:
        path = Path(args.queries) if args.queries else resolve_path("queries", cfg)
        source = str(path)
        queries = load_queries(path)
        if not queries and not args.queries:
            path, source = EXAMPLES, "the suggested examples (eval/examples/queries.example.jsonl), because eval/queries.jsonl is empty"
            queries = load_queries(path)
    except EvalDataError as exc:
        print(f"Cannot read the queries: {exc}", file=sys.stderr)
        return 2
    if not queries:
        print("There are no queries to check.", file=sys.stderr)
        return 2
    judgments = resolve_path("judgments", cfg)
    if not judgments.exists():
        print(f"{judgments} does not exist: the corpus has not been built (M1), so there is nothing to count.", file=sys.stderr)
        return 2
    try:
        providers = load_checked(load_providers, cfg)
    except ArtefactError as exc:
        print(f"A module could not be loaded: {exc}", file=sys.stderr)
        return 2
    if "search" in providers.stubbed:
        print("Refusing to run: search is a fixed-value stub, so the counts would describe placeholder documents. Switch the real "
              "search on (stubs.search: false, or LEXSHIFT_STUBS=none).", file=sys.stderr)
        return 2
    numbers = [n for q in queries for n in section_numbers(q.text)]
    mentions, years, total = scan_corpus(judgments, numbers)
    rows = analyse(queries, providers, mentions, years, args.k)
    if args.json:
        print(json.dumps({"corpus": {"documents": total, "years": dict(sorted(years.items()))}, "rows": [asdict(r) for r in rows]}, indent=2))
    else:
        print(render(rows, years, total, source))
    return 1 if args.strict and any(r.verdict == "empty" for r in rows) else 0


if __name__ == "__main__":
    sys.exit(main())
