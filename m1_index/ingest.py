"""M1 ingestion: from the Supreme Court Judgments dataset to data/processed/judgments.jsonl.

    python -m m1_index.ingest catalog                    # the dataset's metadata and PDF listing (about 50 MB, once)
    python -m m1_index.ingest fetch --years 2025-2015    # download the PDFs of those years (criminal-looking titles) and the named cases, read their text
    python -m m1_index.ingest build                      # text cache + catalog -> data/processed/judgments.jsonl (criminal-law judgments and the named cases)
    python -m m1_index.ingest status                     # what has been read, by year
    python -m m1_index.ingest download                   # the default plan end to end: catalog if missing, fetch, build
    python -m m1_index.ingest pack / unpack              # judgments.jsonl <-> data/corpus/judgments.jsonl.xz, the copy that is tracked in git (a fresh clone runs unpack)

What is chosen and why: m1_index/selection.py. The source is the public AWS Open Data bucket (CC-BY-4.0); every PDF is fetched one by one with an exact size check, read
with PyMuPDF, and deleted after its text is saved (data/raw/text keeps the text, so a rebuild needs no network). `build` writes beside the target and replaces it only
when the result is complete.
"""

from __future__ import annotations

import datetime as dt
import json
import re
import shutil
import sys
import time
from concurrent.futures import ProcessPoolExecutor, ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Any, Callable

from common.schema import Judgment
from m1_index.catalog import BASE, CATALOG_FILE, Entry, build as build_catalog, http_get, load as load_catalog
from m1_index.selection import CRIMINAL_TITLE, candidates, is_criminal_text, named_matches
from m1_index.zones import split_zones

ROOT = Path(__file__).resolve().parents[1]
DATA_DIR = ROOT / "data"
RAW_DIR = DATA_DIR / "raw"
PROCESSED_DIR = DATA_DIR / "processed"
JUDGMENTS_FILE = PROCESSED_DIR / "judgments.jsonl"


_CLOSING = re.compile(r",?\s*\*?\s*\.?J{1,3}[.,~!'lI1]{0,2}(?:\s*[\]\)]|[jJIl1|!](?=[\s'’.,]|$))", re.IGNORECASE)  # ", JJ.]" and what OCR makes of the closing bracket: ", JJ.)", ", JJ,I", ", JJ.J"
_OPENING = re.compile(r"[\[\(]")
_YEAR_LINE = re.compile(r"\b(1[89]\d\d|20\d\d)\b")
_NOT_A_NAME = re.compile(r"\d{2,}|\b(?:appeal|court|criminal|petition|referred|relied|jurisdiction|order|judgment|para)\b", re.IGNORECASE)  # a digit alone is OCR for an initial ("MADAN 8. LOKUR")
_CHIEF = re.compile(r"C\.?\s?[JjIl1]{1,2}\.?(?:\s?I\.?)?", re.IGNORECASE)  # "CJI", "C.J." and the OCR'd "C.1." after a name mark the Chief Justice, not another judge


def _split_judges(raw: str) -> list[str]:
    """'A, B AND C' -> ['A', 'B', 'C'], undoing the ways OCR glues the word AND to a name ('EQBALAND C.', 'LOKUR ANDS. A.', 'JOSEPH AND.A.M.')."""
    raw = raw.replace("*", "")
    raw = re.sub(r"\s+", " ", raw).strip()
    raw = re.sub(r"(?<=[A-Z]{3})AND(?=\s+[A-Z])", " and ", raw)  # EQBALAND C. NAGAPPAN, THAKKERAND ALTAMAS KABIR
    raw = re.sub(r"(?<=[A-Z]{3})AND(?=[A-Z]\.)", " and ", raw)  # THAKKERANDP.SATHASIVAM
    raw = re.sub(r"(?<=[A-Z]{4})AND(?=[A-Z]{5,})", " and ", raw)  # EQBALANDAMITAVA ROY
    raw = re.sub(r"\bAN\.D\b|\bAND\.\s+", " and ", raw)  # AN.D J.M. PANCHAL, AND. P.P. NAOLEKAR
    raw = re.sub(r"\bANO(?=[A-Z]\.|\s*[A-Z]\.)", " and ", raw)  # ANOP. SATHASIVAM
    raw = re.sub(r"\s*&\s*", " and ", raw)  # K.S. RADHAKRISHNAN & DIPAK MISRA
    raw = re.sub(r"(?<=\s)AND(?=[A-Z]{2,}|[A-Z]\.)", "and ", raw)  # ANDLOKESHWAR SINGH, ANDC.K. THAKKER: AND glued to the next name
    raw = re.sub(r"\bANDS\.", " and S.", raw)  # LOKUR ANDS. A. BOBDE
    raw = re.sub(r"\bAND\.(?=[A-Z]\.)", " and ", raw)  # AND.A.M. KHANWILKAR
    raw = re.sub(r"\b(?:ANU|ANO|AN0|ANDI)\b", " and ", raw)  # OCR of AND
    names: list[str] = []
    for part in re.split(r"\s+and\s+|,\s*", raw, flags=re.IGNORECASE):
        name = re.sub(r"\b(?:Hon'?ble|Mr\.?|Mrs\.?|Ms\.?|Justice)\b", "", part, flags=re.IGNORECASE).strip()
        name = re.sub(r"(?<=\s)[A-H](?=\s|$)", " ", name)  # the reporter's margin letters (A to H) that fall inside a name
        name = re.sub(r"^[Il1|](?=[A-Z]{1,2}\.)", "", name)  # an opening bracket read as a letter ("IM.P. THAKKAR", "lDR. ARIJIT PASAYAT")
        name = re.sub(r"(?<![\w])8(?=\.)", "B", re.sub(r"(?<![\w])5(?=\.)", "S", name))  # initials read as digits ("MADAN 8. LOKUR", "T. 5. THAKUR")
        name = re.sub(r"[^\w.)]+$", "", re.sub(r"\s+", " ", name)).strip()
        if name and not _CHIEF.fullmatch(name) and not re.fullmatch(r"\.?JJ?[.,~!']*", name, flags=re.IGNORECASE):  # "JJ." is the title of the bench, not a judge
            names.append(name)
    return list(dict.fromkeys(names))


def _plausible(names: list[str]) -> bool:
    """A coram is a handful of short names: not a list of cited cases or a paragraph that happens to end in ', J.'"""
    return 1 <= len(names) <= 13 and all(3 <= len(n) <= 45 and len(n.split()) <= 6 and not _NOT_A_NAME.search(n) for n in names)


def _coram_candidates(text: str) -> list[str]:
    """Candidate coram strings: those with a bracket around the names (real or OCR-damaged) in the order they occur, then the ones where the bracket was lost."""
    bracketed: list[tuple[int, str]] = []
    lost: list[str] = []
    for m in _CLOSING.finditer(text):
        before = text[max(0, m.start() - 300): m.start()]
        opens = list(_OPENING.finditer(before))
        for o in opens:  # [A, B and C, JJ.] or (A and B, JJ.): farthest opening bracket first (a nearer one can be an OCR'd "(" inside the list); the first that reads as names wins
            bracketed.append((m.start(), before[o.end():]))
        years = list(_YEAR_LINE.finditer(before))
        if years:  # the OCR lost the bracket: the names follow the line that carries the date
            tail = before[years[-1].end():]
            lost.append(tail.split("\n", 1)[1] if "\n" in tail else tail)
    for m in re.finditer(r"\b(?:1[89]\d\d|20\d\d)\s*\n\s*[\[(]([^\[\]()]{8,200}?)[\])]", text):  # "[A and B]" under the date, no "JJ." (newer volumes)
        bracketed.append((m.start(), m.group(1)))
    for m in re.finditer(r"[\[(]([^\[\]()]{4,200}?,\s*JJ\.\s+(?:and|AND)\s[^\[\]()]{4,100}?)[\])]", text):  # "[A, JJ. and B]": the title written after the first names
        bracketed.append((m.start(), m.group(1)))
    bare: list[str] = []
    for line in text.splitlines():  # a bare line "A, B, JJ."
        line = line.strip()
        if re.search(r",\s*JJ?\.?\s*$", line, re.IGNORECASE):
            bare.append(re.sub(r",\s*JJ?\.?\s*$", "", line, flags=re.IGNORECASE))
    return [c for _, c in sorted(bracketed, key=lambda t: t[0])] + lost + bare


def parse_coram_bench_size(text: str) -> tuple[int | None, list[str]]:
    """The bench of a judgment from its coram line, as (number of judges, names); (None, []) when no plausible line is found.

    Handles [A, B and C, JJ.], [A, B and C,* JJ.], [A, CJI and B,* JJ.], (A and B, JJ.), a bare "A, B, JJ." line, and the way OCR damages the older
    volumes (a lost bracket, a closing J, AND glued to a name). A candidate that does not look like a list of names is rejected, so the bench size is
    either right or missing, not a number read off a list of cited cases.
    """
    for raw in _coram_candidates(text):
        names = _split_judges(raw)
        if _plausible(names):
            return len(names), names
    return None, []


def parse_iso_date(raw_date: Any, text: str = "") -> str:
    """Parse raw date or extract from text, returning strict YYYY-MM-DD."""
    if raw_date:
        s = str(raw_date).strip()
        # Direct ISO match
        iso_m = re.search(r"(\d{4})[-/](\d{1,2})[-/](\d{1,2})", s)
        if iso_m:
            y, m, d = iso_m.groups()
            return f"{int(y):04d}-{int(m):02d}-{int(d):02d}"

        # Standard Indian dates e.g. "12 January 2018" or "12-01-2018"
        for fmt in ("%d %B, %Y", "%d %B %Y", "%B %d, %Y", "%d-%m-%Y", "%d/%m/%Y"):
            try:
                return dt.datetime.strptime(s, fmt).date().isoformat()
            except ValueError:
                pass

    # Fallback to searching text for date patterns
    m = re.search(r"\b(\d{1,2})(?:st|nd|rd|th)?\s+(January|February|March|April|May|June|July|August|September|October|November|December),?\s+(\d{4})\b", text, re.IGNORECASE)
    if m:
        day, month, year = m.groups()
        try:
            return dt.datetime.strptime(f"{day} {month} {year}", "%d %B %Y").date().isoformat()
        except ValueError:
            pass

    return "2020-01-01"


# ---------------------------------------------------------------------------------------------------------------------- titles, dates, benches
_SMALL = {"of", "the", "and", "for", "by", "through", "in", "on", "at", "to", "vs.", "etc.", "a", "an"}
_ACRONYMS = {"CBI", "NCT", "NIA", "UOI", "UP", "MP", "AP", "HP", "NCB", "DRI", "CJI", "UT", "IAS", "IPS", "NDPS", "UAPA", "LIC", "SEBI", "RBI", "BSNL", "CRPF", "BSF", "CISF",
             "NHAI", "MCD", "DDA", "UPSC", "PSC", "HC", "SIT", "CID", "ECGC", "DMRC", "AIIMS", "IIT", "CAG", "TADA", "POTA", "MCOCA", "FIR", "SC", "ST", "OBC", "NEET"}
_INITIALS = re.compile(r"^(?:[A-Za-z]\.){1,6}[A-Za-z]?\.?$")  # K.S., U.P., N.C.T., V.
_FIXED = {"ORS.": "Ors.", "ORS": "Ors.", "ANR.": "Anr.", "ANR": "Anr.", "&": "&", "@": "@", "(D)": "(D)", "LRS.": "LRs.", "LRS": "LRs.", "M/S.": "M/s.", "M/S": "M/s"}


def _cap(word: str) -> str:
    return re.sub(r"[A-Za-z]+", lambda m: m.group(0).capitalize(), word.lower())


def smart_title(raw: str) -> str:
    """'V. RAVI KUMAR versus STATE, REP. BY INSPECTOR OF POLICE & ORS.' -> 'V. Ravi Kumar v. State, Rep. by Inspector of Police & Ors.'"""
    text = re.sub(r"\s+", " ", (raw or "").strip())
    return " v. ".join(_case_side(side) for side in re.split(r"\s+versus\s+", text, flags=re.I))  # only the catalog's "versus" becomes "v.": "V." in a name is an initial


def _case_side(text: str) -> str:
    words: list[str] = []
    for i, tok in enumerate(text.split(" ")):
        m = re.match(r"^([^\w&@/]*)(.*?)([^\w.)/]*)$", tok)
        pre, core, post = (m.group(1), m.group(2), m.group(3)) if m else ("", tok, "")
        bare = core.rstrip(".")
        if core.upper() in _FIXED:
            out = _FIXED[core.upper()]
        elif core.lower() in _SMALL and i > 0:
            out = core.lower()
        elif bare.upper() in _ACRONYMS or _INITIALS.match(core):
            out = core.upper()
        else:
            out = _cap(core)
        words.append(pre + out + post)
    return " ".join(words)


def catalog_date(raw: str) -> str | None:
    """The catalog writes 14-12-2018; a Judgment wants 2018-12-14."""
    m = re.fullmatch(r"\s*(\d{1,2})-(\d{1,2})-(\d{4})\s*", raw or "")
    if not m:
        return None
    day, month, year = int(m.group(1)), int(m.group(2)), int(m.group(3))
    try:
        return dt.date(year, month, day).isoformat()
    except ValueError:
        return None


def clean_text(text: str) -> str:
    """Text as the reader and the tokenizer should see it: no control characters, no form feeds, no soft hyphens, line structure kept."""
    text = text.replace("\x0c", "\n").replace("­", "").replace(" ", " ")
    text = re.sub(r"[\x00-\x08\x0b\x0e-\x1f\x7f]", "", text)
    text = re.sub(r"[ \t]+\n", "\n", text)
    text = re.sub(r"\n{4,}", "\n\n\n", text)
    return text.strip()


# ---------------------------------------------------------------------------------------------------------------------- download and extract
PDF_DIR = RAW_DIR / "pdf"
TEXT_DIR = RAW_DIR / "text"
FAILURES = RAW_DIR / "failures.tsv"
MIN_TEXT_CHARS = 1500  # a judgment with less text than this is a scan without a text layer (or a stub): not usable by a text index


def text_path(entry: Entry) -> Path:
    return TEXT_DIR / str(entry.year) / f"{entry.path}_EN.txt"


def pdf_path(entry: Entry) -> Path:
    return PDF_DIR / str(entry.year) / f"{entry.path}_EN.pdf"


def extract_text(pdf: bytes) -> tuple[str, int]:
    """(text, pages) of a PDF, read with PyMuPDF (a library: it turns the PDF into text, nothing more; all the IR is ours)."""
    try:
        import pymupdf
    except ImportError:  # older releases name the module fitz
        import fitz as pymupdf  # type: ignore[no-redef]
    with pymupdf.open(stream=pdf, filetype="pdf") as doc:
        pages = [page.get_text("text") for page in doc]
    return clean_text("\n".join(pages)), len(pages)


def _extract_file(args: tuple[str, str, bool]) -> tuple[str, int, int, str]:
    """Worker process: PDF file -> text file. Returns (doc_id, chars, pages, error)."""
    pdf_file, text_file, keep_pdf = args
    pdf = Path(pdf_file)
    try:
        text, pages = extract_text(pdf.read_bytes())
        out = Path(text_file)
        out.parent.mkdir(parents=True, exist_ok=True)
        tmp = out.with_suffix(".tmp")
        tmp.write_text(text, encoding="utf-8", newline="\n")
        tmp.replace(out)
        if not keep_pdf:
            pdf.unlink(missing_ok=True)
        return pdf.stem, len(text), pages, ""
    except Exception as exc:  # noqa: BLE001 - a damaged PDF must not stop the other thousand
        return pdf.stem, 0, 0, f"{type(exc).__name__}: {exc}"[:200]


def download_pdf(entry: Entry) -> tuple[Path | None, int, str]:
    """Download one PDF into data/raw/pdf (skipped if present); (path, bytes, error)."""
    target = pdf_path(entry)
    if target.exists():
        return target, 0, ""
    try:
        data = http_get(f"{BASE}/{entry.pdf_key}")
    except Exception as exc:  # noqa: BLE001
        return None, 0, f"{type(exc).__name__}: {exc}"[:200]
    if entry.pdf_bytes and len(data) != entry.pdf_bytes:
        return None, 0, f"size {len(data)} differs from the listed {entry.pdf_bytes}"
    target.parent.mkdir(parents=True, exist_ok=True)
    tmp = target.with_suffix(".part")
    tmp.write_bytes(data)
    tmp.replace(target)
    return target, len(data), ""


def fetch(entries: list[Entry], workers: int = 6, processes: int = 8, keep_pdf: bool = False, log: Callable[[str], None] = print) -> dict[str, int]:
    """Download the PDFs of `entries` that are not yet read, extract their text, delete the PDFs. Safe to stop and start again."""
    todo = [e for e in entries if not text_path(e).exists()]
    log(f"fetch: {len(entries)} judgments asked for, {len(entries) - len(todo)} already read, {len(todo)} to download "
        f"({sum(e.pdf_bytes or 0 for e in todo) / 1e6:.0f} MB)")
    stats = {"done": 0, "failed": 0, "short": 0, "bytes": 0}
    started = time.time()
    failures: list[str] = []
    TEXT_DIR.mkdir(parents=True, exist_ok=True)
    with ThreadPoolExecutor(workers) as downloads, ProcessPoolExecutor(processes) as readers:
        pending = {downloads.submit(download_pdf, e): e for e in todo}
        extracting: dict[Any, Entry] = {}
        for fut in as_completed(list(pending)):
            entry = pending[fut]
            pdf, nbytes, err = fut.result()
            stats["bytes"] += nbytes
            if pdf is None:
                stats["failed"] += 1
                failures.append(f"{entry.doc_id}\tdownload\t{err}")
                continue
            extracting[readers.submit(_extract_file, (str(pdf), str(text_path(entry)), keep_pdf))] = entry
            if len(extracting) >= processes * 2:  # keep the readers busy but do not pile up PDFs on disk
                done = next(as_completed(list(extracting)))
                _collect(done, extracting.pop(done), stats, failures)
            if (stats["done"] + stats["failed"]) % 50 == 0 and stats["done"] + stats["failed"]:
                _progress(stats, len(todo), started, log)
        for done in as_completed(list(extracting)):
            _collect(done, extracting[done], stats, failures)
    if failures:
        with FAILURES.open("a", encoding="utf-8", newline="\n") as fh:
            fh.write("\n".join(failures) + "\n")
    _progress(stats, len(todo), started, log)
    return stats


def _collect(fut: Any, entry: Entry, stats: dict[str, int], failures: list[str]) -> None:
    doc_id, chars, pages, err = fut.result()
    if err:
        stats["failed"] += 1
        failures.append(f"{entry.doc_id}\textract\t{err}")
    else:
        stats["done"] += 1
        stats["short"] += chars < MIN_TEXT_CHARS


def _progress(stats: dict[str, int], total: int, started: float, log: Callable[[str], None]) -> None:
    elapsed = max(1.0, time.time() - started)
    seen = stats["done"] + stats["failed"]
    rate = stats["bytes"] / elapsed / 1e6
    eta = (total - seen) / (seen / elapsed) / 60 if seen else float("inf")
    log(f"fetch: {seen}/{total} ({stats['failed']} failed, {stats['short']} with almost no text), {stats['bytes'] / 1e6:.0f} MB at {rate:.2f} MB/s, about {eta:.0f} min left")


# ---------------------------------------------------------------------------------------------------------------------- build the corpus
def judgment_from(entry: Entry, text: str) -> Judgment:
    bench, judges = parse_coram_bench_size(text[:4000])
    date = catalog_date(entry.decision_date)
    if date is None:  # parse_iso_date would answer 2020-01-01 for a date it cannot find: a judgment without a date is skipped (and reported), never given one
        raise ValueError(f"no usable decision date in the catalog ({entry.decision_date!r})")
    cites = [f"{entry.citation} : {entry.case_id}".strip(" :")] if entry.citation or entry.case_id else []
    j = Judgment(doc_id=entry.doc_id, title=smart_title(entry.title), date=date, bench_size=bench, judges=judges, reporter_citations=cites, zones=split_zones(text), text=text)
    j.validate()
    return j


def build(out: Path = JUDGMENTS_FILE, force: bool = False, log: Callable[[str], None] = print) -> int:
    """Read the text cache and write judgments.jsonl: the named cases plus every judgment whose text mentions a criminal code.

    The file is written beside the target and moved into place only when it is complete, and an empty or much smaller result never replaces a corpus (the
    old build step opened the target for writing first and emptied it when there was nothing to read).
    """
    entries = {e.path: e for e in load_catalog()}
    named = {e.path: n for n, e in named_matches(entries.values())}
    records: list[Judgment] = []
    skipped = {"no text": 0, "scan": 0, "not criminal": 0, "bad record": 0}
    for path, entry in sorted(entries.items(), key=lambda kv: (kv[1].year, kv[0])):
        tfile = text_path(entry)
        if not tfile.exists():
            skipped["no text"] += 1
            continue
        text = tfile.read_text(encoding="utf-8")
        if len(text) < MIN_TEXT_CHARS:
            skipped["scan"] += 1
            continue
        if path not in named and not is_criminal_text(text):
            skipped["not criminal"] += 1
            continue
        try:
            records.append(judgment_from(entry, text))
        except Exception as exc:  # noqa: BLE001 - one malformed record is reported, not fatal
            skipped["bad record"] += 1
            log(f"build: {entry.doc_id}: {exc}")
    if not records:
        log("build: nothing to write (no text in data/raw/text matches the catalog): judgments.jsonl was left alone. Run `python -m m1_index.ingest fetch` first.")
        return 0
    previous = sum(1 for _ in out.open(encoding="utf-8")) if out.exists() else 0
    if previous and len(records) < 0.5 * previous and not force:
        log(f"build: {len(records)} records would replace {previous}: refusing (pass --force if that is what you want)")
        return 0
    out.parent.mkdir(parents=True, exist_ok=True)
    tmp = out.with_suffix(".tmp")
    with tmp.open("w", encoding="utf-8", newline="\n") as fh:
        for j in records:
            fh.write(json.dumps(j.to_dict(), ensure_ascii=False) + "\n")
    _replace(tmp, out)
    if out == JUDGMENTS_FILE:  # a trial written elsewhere must not rewrite the tracked manifest
        write_manifest(records, named)
    log(f"build: wrote {len(records)} judgments to {out} (skipped: {skipped})")
    return len(records)


def _replace(tmp: Path, out: Path) -> None:
    """Move a finished file into place. On Windows another process reading the old file (a running server, an index build) blocks it for a moment."""
    for attempt in range(40):
        try:
            tmp.replace(out)
            return
        except PermissionError:
            time.sleep(1.5)
    # still locked (a virus scanner or a search indexer can hold a freshly written file for a minute): copy over it instead, and say so
    print(f"note: could not rename {tmp.name} over {out.name} (locked); copying instead", file=sys.stderr)
    shutil.copyfile(tmp, out)
    tmp.unlink()


CORPUS_DIR = DATA_DIR / "corpus"
PACKED = CORPUS_DIR / "judgments.jsonl.xz"
PACKED_SHA = CORPUS_DIR / "judgments.jsonl.sha256"


def pack(src: Path = JUDGMENTS_FILE, dst: Path = PACKED, log: Callable[[str], None] = print) -> int:
    """judgments.jsonl -> data/corpus/judgments.jsonl.xz, the copy that is tracked in git (a tenth of the size); `unpack` restores the file byte for byte."""
    import hashlib
    import lzma

    data = src.read_bytes()
    dst.parent.mkdir(parents=True, exist_ok=True)
    tmp = dst.with_suffix(".tmp")
    with lzma.open(tmp, "wb", preset=6) as fh:
        fh.write(data)
    _replace(tmp, dst)
    sha = hashlib.sha256(data).hexdigest()
    dst.with_name(PACKED_SHA.name).write_text(f"{sha}  judgments.jsonl\n", encoding="utf-8", newline="\n")
    n = data.count(b"\n")
    log(f"pack: {src.name} ({len(data) / 1e6:.0f} MB, {n} judgments) -> {dst} ({dst.stat().st_size / 1e6:.1f} MB)")
    return n


def unpack(src: Path = PACKED, dst: Path = JUDGMENTS_FILE, log: Callable[[str], None] = print) -> int:
    """data/corpus/judgments.jsonl.xz -> data/processed/judgments.jsonl, checked against the recorded SHA-256 (a clone needs this, not the download)."""
    import hashlib
    import lzma

    if not src.exists():
        raise FileNotFoundError(f"{src} does not exist: run `python -m m1_index.ingest download` to build the corpus from the public bucket instead")
    with lzma.open(src, "rb") as fh:
        data = fh.read()
    sha_file = src.with_name(PACKED_SHA.name)
    if sha_file.exists():
        want = sha_file.read_text(encoding="utf-8").split()[0]
        if hashlib.sha256(data).hexdigest() != want:
            raise ValueError(f"{src}: the unpacked corpus does not match {sha_file.name}")
    dst.parent.mkdir(parents=True, exist_ok=True)
    tmp = dst.with_suffix(".tmp")
    tmp.write_bytes(data)
    _replace(tmp, dst)
    n = data.count(b"\n")
    log(f"unpack: {dst} ({len(data) / 1e6:.0f} MB, {n} judgments)")
    return n


MANIFEST = DATA_DIR / "corpus_manifest.csv"


def write_manifest(records: list[Judgment], named: dict[str, Any]) -> None:
    """data/corpus_manifest.csv (tracked): which judgments the corpus holds and why, so it can be rebuilt without anyone's judgments.jsonl."""
    import csv

    with MANIFEST.open("w", encoding="utf-8", newline="") as fh:
        w = csv.writer(fh, lineterminator="\n")
        w.writerow(["doc_id", "date", "title", "chars", "named_case", "doctrine", "role"])
        for j in records:
            path = j.doc_id[: -len("_EN")]
            n = named.get(path)
            w.writerow([j.doc_id, j.date, j.title, len(j.text), n.label if n else "", n.doctrine if n else "", n.role if n else ""])


def status(log: Callable[[str], None] = print) -> None:
    entries = load_catalog()
    have = {e.path for e in entries if text_path(e).exists()}
    by_year: dict[int, list[int]] = {}
    for e in entries:
        if e.pdf_bytes is not None:
            row = by_year.setdefault(e.year, [0, 0, 0])
            row[0] += 1
            row[1] += CRIMINAL_TITLE.search(e.title) is not None
            row[2] += e.path in have
    log("year  english  criminal-title  read")
    for y in sorted(by_year, reverse=True)[:30]:
        log(f"{y}  {by_year[y][0]:>7}  {by_year[y][1]:>14}  {by_year[y][2]:>4}")
    log(f"text cache: {len(have)} judgments")


def parse_years(spec: str) -> list[int]:
    out: list[int] = []
    for part in spec.split(","):
        if "-" in part:
            a, b = (int(x) for x in part.split("-"))
            out += range(a, b + 1) if a <= b else range(a, b - 1, -1)
        elif part.strip():
            out.append(int(part))
    return out


def plan(years: list[int], tier: str, with_named: bool) -> list[Entry]:
    entries = load_catalog()
    chosen = {e.path: e for e in candidates(entries, years, tier)}
    if with_named:
        for _, e in named_matches(entries):
            chosen.setdefault(e.path, e)
    return sorted(chosen.values(), key=lambda e: (-e.year, e.path))


DEFAULT_YEARS = "2025-2015"


def main(argv: list[str] | None = None) -> int:
    import argparse

    ap = argparse.ArgumentParser(prog="python -m m1_index.ingest", description=__doc__.split("\n\n")[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("catalog", help="download the dataset's metadata and PDF listing (about 50 MB)")
    f = sub.add_parser("fetch", help="download PDFs, read their text, delete the PDFs")
    f.add_argument("--years", default=DEFAULT_YEARS, help="years, newest first, e.g. 2025-2015 or 2024,2023 (default %(default)s)")
    f.add_argument("--tier", choices=("criminal-title", "all"), default="criminal-title", help="which titles: criminal-looking ones (default) or all")
    f.add_argument("--no-named", action="store_true", help="do not add the named cases")
    f.add_argument("--only-named", action="store_true", help="only the named cases")
    f.add_argument("--limit", type=int, default=0, help="stop after this many judgments (a trial run)")
    f.add_argument("--workers", type=int, default=6)
    f.add_argument("--keep-pdf", action="store_true")
    b = sub.add_parser("build", help="text cache -> data/processed/judgments.jsonl (never empties an existing corpus)")
    b.add_argument("--out", type=Path, default=JUDGMENTS_FILE)
    b.add_argument("--force", action="store_true")
    sub.add_parser("status", help="what has been read, by year")
    sub.add_parser("pack", help="judgments.jsonl -> data/corpus/judgments.jsonl.xz (the copy tracked in git)")
    sub.add_parser("unpack", help="data/corpus/judgments.jsonl.xz -> judgments.jsonl (what a fresh clone runs; no network)")
    d = sub.add_parser("download", help="the default plan: fetch then build")
    d.add_argument("--years", default=DEFAULT_YEARS)
    args = ap.parse_args(argv)
    if args.cmd == "catalog":
        build_catalog()
    elif args.cmd == "fetch":
        todo = plan([] if args.only_named else parse_years(args.years), args.tier, not args.no_named)
        fetch(todo[: args.limit] if args.limit else todo, workers=args.workers, keep_pdf=args.keep_pdf)
    elif args.cmd == "build":
        return 0 if build(args.out, args.force) else 1
    elif args.cmd == "status":
        status()
    elif args.cmd == "pack":
        pack()
    elif args.cmd == "unpack":
        unpack()
    elif args.cmd == "download":
        if not CATALOG_FILE.exists():
            build_catalog()
        fetch(plan(parse_years(args.years), "criminal-title", True))
        return 0 if build() else 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
