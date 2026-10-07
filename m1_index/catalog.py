"""The catalog of the Indian Supreme Court Judgments dataset: what exists, before any judgment is downloaded.

Source: the public AWS Open Data bucket `indian-supreme-court-judgments` (region ap-south-1, licence CC-BY-4.0, no account needed),
<https://registry.opendata.aws/indian-supreme-court-judgments/>. Three things are read from it, all small:

* `metadata/parquet/year=YYYY/metadata.parquet`: one row per judgment (title, parties, bench, citation, decision date, disposal), about 48 MB for
  all 76 years;
* a listing of `data/pdf/year=YYYY/english/`: which judgments have an English PDF, and its size;
* later, `ingest.py` downloads the PDFs it needs one by one from `data/pdf/year=YYYY/english/<path>_EN.pdf`.

Verified on 2026-10-07: 43,333 judgments, 43,327 English PDFs, 22.6 GB in all. Nothing here is ever fetched at demo time.

    python -m m1_index.catalog build        # download the metadata and the PDF listing (about 50 MB), write data/raw/catalog/catalog.jsonl
    python -m m1_index.catalog show "navtej" # look a judgment up by words of its title
"""

from __future__ import annotations

import io
import json
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Iterable

ROOT = Path(__file__).resolve().parents[1]
BASE = "https://indian-supreme-court-judgments.s3.amazonaws.com"
CATALOG_DIR = ROOT / "data" / "raw" / "catalog"
CATALOG_FILE = CATALOG_DIR / "catalog.jsonl"
FIRST_YEAR, LAST_YEAR = 1950, 2025
KEEP = ("title", "petitioner", "respondent", "judge", "citation", "case_id", "decision_date", "disposal_nature", "path", "nc_display", "year")
USER_AGENT = "LexShift-course-project/1.0 (CSD358; public dataset, CC-BY-4.0)"


@dataclass(frozen=True)
class Entry:
    path: str  # the dataset's own identifier, e.g. 2018_14_828_839 (year, SCR volume, first page, last page); an S_ prefix marks the supplementary volumes
    year: int
    title: str
    petitioner: str
    respondent: str
    judge: str
    citation: str
    case_id: str
    decision_date: str
    disposal_nature: str
    pdf_bytes: int | None  # size of the English PDF, or None when the bucket holds none

    @property
    def doc_id(self) -> str:
        return f"{self.path}_EN"

    @property
    def pdf_key(self) -> str:
        return f"data/pdf/year={self.year}/english/{self.path}_EN.pdf"


# ---------------------------------------------------------------------------------------------------------------------- HTTP
def http_get(url: str, headers: dict[str, str] | None = None, timeout: int = 120, retries: int = 5) -> bytes:
    """GET with a small exponential backoff; a 404 is not retried."""
    last: Exception | None = None
    for attempt in range(retries):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT, **(headers or {})})
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                return resp.read()
        except urllib.error.HTTPError as exc:
            if exc.code in (403, 404):
                raise
            last = exc
        except (urllib.error.URLError, TimeoutError, ConnectionError, OSError) as exc:
            last = exc
        time.sleep(min(30, 2 ** attempt))
    raise ConnectionError(f"{url}: {last}")


def list_keys(prefix: str) -> list[tuple[str, int]]:
    """Every object under a prefix with its size (the S3 listing API, 1000 keys a page)."""
    out: list[tuple[str, int]] = []
    token: str | None = None
    while True:
        url = f"{BASE}/?list-type=2&prefix={urllib.parse.quote(prefix)}&max-keys=1000" + (f"&continuation-token={urllib.parse.quote(token)}" if token else "")
        text = http_get(url).decode("utf-8")
        out += [(k, int(s)) for k, s in re.findall(r"<Key>([^<]+)</Key>.*?<Size>(\d+)</Size>", text, flags=re.S)]
        nxt = re.search(r"<NextContinuationToken>([^<]+)</NextContinuationToken>", text)
        if not nxt:
            return out
        token = nxt.group(1)


# ---------------------------------------------------------------------------------------------------------------------- building
def _year_metadata(year: int) -> list[dict[str, Any]]:
    import pyarrow.parquet as pq  # only needed to build the catalog; listed in requirements.txt

    cache = CATALOG_DIR / f"{year}.parquet"
    if not cache.exists():
        data = http_get(f"{BASE}/metadata/parquet/year={year}/metadata.parquet")
        cache.write_bytes(data)
    table = pq.read_table(io.BytesIO(cache.read_bytes()), columns=list(KEEP))
    return table.to_pylist()


def _year_listing(year: int) -> dict[str, int]:
    return {k.rsplit("/", 1)[-1][: -len("_EN.pdf")]: size for k, size in list_keys(f"data/pdf/year={year}/english/") if k.endswith("_EN.pdf")}


def build(years: Iterable[int] = range(FIRST_YEAR, LAST_YEAR + 1), workers: int = 6, log: Callable[[str], None] = print) -> int:
    """Download the metadata and the English listing of every year and write catalog.jsonl (one judgment per line). Returns the number of records."""
    CATALOG_DIR.mkdir(parents=True, exist_ok=True)
    years = list(years)
    with ThreadPoolExecutor(workers) as pool:
        metas = list(pool.map(_year_metadata, years))
        listings = list(pool.map(_year_listing, years))
    tmp = CATALOG_FILE.with_suffix(".tmp")
    n = missing = 0
    seen: set[str] = set()
    with tmp.open("w", encoding="utf-8", newline="\n") as fh:
        for year, rows, listing in zip(years, metas, listings):
            for row in rows:
                path = str(row.get("path") or "")
                if not path or path in seen:  # the metadata lists a few judgments twice
                    continue
                seen.add(path)
                rec = {k: ("" if row.get(k) in (None, "None") else str(row.get(k))) for k in KEEP}
                rec["year"] = int(rec["year"] or year)
                rec["pdf_bytes"] = listing.get(path)
                missing += rec["pdf_bytes"] is None
                fh.write(json.dumps(rec, ensure_ascii=False) + "\n")
                n += 1
    tmp.replace(CATALOG_FILE)
    log(f"catalog: {n} judgments, {n - missing} with an English PDF, written to {CATALOG_FILE}")
    return n


def load(path: Path = CATALOG_FILE) -> list[Entry]:
    if not path.exists():
        raise FileNotFoundError(f"{path} does not exist: run `python -m m1_index.catalog build` (downloads about 50 MB of metadata)")
    out: list[Entry] = []
    with path.open(encoding="utf-8") as fh:
        for line in fh:
            if line.strip():
                r = json.loads(line)
                out.append(Entry(path=r["path"], year=int(r["year"]), title=r["title"], petitioner=r["petitioner"], respondent=r["respondent"], judge=r["judge"],
                                 citation=r["citation"], case_id=r["case_id"], decision_date=r["decision_date"], disposal_nature=r["disposal_nature"], pdf_bytes=r.get("pdf_bytes")))
    return out


def find(entries: Iterable[Entry], words: str, years: set[int] | None = None) -> list[Entry]:
    """Entries whose title contains every word (case-insensitive)."""
    needles = [w.lower() for w in words.split()]
    return [e for e in entries if all(n in e.title.lower() for n in needles) and (years is None or e.year in years)]


def main(argv: list[str] | None = None) -> int:
    args = argv if argv is not None else sys.argv[1:]
    cmd = args[0] if args else "build"
    if cmd == "build":
        build()
        return 0
    if cmd == "show" and len(args) > 1:
        for e in find(load(), " ".join(args[1:]))[:30]:
            print(f"{e.year}  {e.path:<22} {e.pdf_bytes or 0:>9} B  {e.title[:100]}")
        return 0
    print(__doc__)
    return 2


if __name__ == "__main__":
    sys.exit(main())
