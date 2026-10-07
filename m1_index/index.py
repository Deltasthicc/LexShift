"""Inverted and positional index with zone and parametric support, stored compactly.

Layout (a compressed-row layout, "CSR"): the vocabulary is a sorted list of terms and every other per-term fact lives in a few flat
`array` objects shared by all terms, so the index holds numbers, not Python objects:

    terms[t]                    the t-th term (sorted, so a term is found by binary search)
    t_start[t] .. t_start[t+1]  the postings of term t, a slice of the posting arrays below (document frequency = the slice length)
    p_doc[i]                    document number of posting i (documents are numbered 0, 1, 2, ... in the order they were added, and a
                                term's postings are in increasing document number, which is what makes merging and probing cheap)
    p_zc[i]                     the term's frequency in each zone of that document, four 16-bit lanes in ZONES order (a lane that
                                saturates at 65535 is looked up exactly in `zc_overflow`)
    p_off[i] .. p_off[i+1]      the posting's positions, a slice of `pos`; the term frequency is the slice length
    pos[...]                    positions, numbered from 0 inside each zone and appended zone by zone in the document's zone order

`InvertedIndex.postings_map` still answers like the old dict of dicts (`postings_map[term][doc_id] == {"positions": [...], "zones":
{zone: tf}, "tf": n}`) but it is a read-only view that decodes a posting only when it is asked for. Document ids are interned to the
document numbers above; `doc_meta` and `doc_lengths` keep their old shape (keyed by document id).

On disk (`index.pkl.gz`, written to a temporary file and moved into place): one gzip stream holding a pickled header (terms,
document tables, statistics, array lengths) followed by the raw bytes of each array. Loading reads the arrays in chunks straight
into place, so the peak is about the final size, not a multiple of it.
"""

from __future__ import annotations

import contextlib
import gzip
import heapq
import json
import math
import os
import pickle
import sys
from array import array
from bisect import bisect_left
from collections.abc import Iterator, Mapping
from pathlib import Path
from typing import Any, Iterable

from common.schema import ZONES, Judgment
from m1_index import tokenizer as tokenizer_module
from m1_index.tokenizer import tokenize

ROOT = Path(__file__).resolve().parents[1]  # the repository root, so defaults do not depend on the working directory
INDEX_DIR = ROOT / "data" / "processed" / "index"
JUDGMENTS_PATH = ROOT / "data" / "processed" / "judgments.jsonl"
INDEX_FILE = "index.pkl.gz"
FORMAT_VERSION = 2  # 1 was the pickled dict of dicts

ZONE_INDEX = {zone: i for i, zone in enumerate(ZONES)}
_LANE_BITS = 16
_LANE_MAX = (1 << _LANE_BITS) - 1
_NOT_IN_INDEX = "{!r} is not a term of the index"
_CHUNK = 1 << 24  # bytes read or written at a time when moving an array to or from the file

if array("I").itemsize != 4 or array("Q").itemsize != 8:  # pragma: no cover - every supported platform
    raise RuntimeError("the compact index needs 4-byte 'I' and 8-byte 'Q' arrays")


# --------------------------------------------------------------------------------------------------
# Building
# --------------------------------------------------------------------------------------------------
class _MemoStemmer:
    """A cache in front of the Porter stemmer. Stemming a word depends on nothing but the word, so a cache cannot change a result;
    it makes a build several times faster because a corpus has far fewer distinct words than words."""

    def __init__(self, inner: Any) -> None:
        self._inner = inner
        self._cache: dict[str, str] = {}

    def stem(self, word: str) -> str:
        try:
            return self._cache[word]
        except KeyError:
            stem = self._cache[word] = self._inner.stem(word)
            return stem

    def __getattr__(self, name: str) -> Any:
        return getattr(self._inner, name)


def _memoised(function: Any) -> Any:
    cache: dict[str, Any] = {}

    def wrapper(token: str) -> Any:
        try:
            return cache[token]
        except KeyError:
            value = cache[token] = function(token)
            return value

    return wrapper


@contextlib.contextmanager
def memoised_tokenizer() -> Iterator[None]:
    """Inside the block `tokenizer.tokenize` looks up the stem and the "is this a legal token" decision of a word in a cache. Both
    depend on nothing but the word, so the tokens it returns are exactly the same; a build is several times faster because a
    corpus has far fewer distinct words than words."""
    stemmer, is_legal = tokenizer_module.STEMMER, tokenizer_module.is_legal_token
    tokenizer_module.STEMMER = _MemoStemmer(stemmer)
    tokenizer_module.is_legal_token = _memoised(is_legal)
    try:
        yield
    finally:
        tokenizer_module.STEMMER, tokenizer_module.is_legal_token = stemmer, is_legal


class _TermBuf:
    """One term's postings while the index is being built: parallel arrays, appended to once per document."""

    __slots__ = ("docs", "zc", "cnt", "pos", "over")

    def __init__(self) -> None:
        self.docs = array("I")
        self.zc = array("Q")
        self.cnt = array("I")
        self.pos = array("I")
        self.over: dict[int, tuple[int, ...]] | None = None  # posting number within the term -> exact per-zone frequencies


class IndexBuilder:
    """Adds documents one at a time and produces an InvertedIndex; nothing but the compact arrays is kept per term."""

    def __init__(self) -> None:
        self.doc_ids: list[str] = []
        self.doc_meta: dict[str, dict[str, Any]] = {}
        self.doc_lengths: dict[str, dict[str, int]] = {}
        self.doc_norms = array("d")
        self._terms: dict[str, _TermBuf] = {}
        self._zone_tokens = {zone: 0 for zone in ZONES}
        self._seen: set[str] = set()

    def add(self, judgment: Judgment) -> None:
        """Tokenise the judgment's zones and index them."""
        j = judgment
        year = int(j.date[:4]) if (j.date and len(j.date) >= 4) else None
        meta = {"year": year, "bench_size": j.bench_size, "title": j.title, "date": j.date}
        self.add_tokens(j.doc_id, meta, {zone: tokenize(text) for zone, text in j.zones.items()})

    def add_tokens(self, doc_id: str, meta: dict[str, Any], zone_tokens: dict[str, list[str]]) -> None:
        """Index a document given as {zone: tokens}. The order of the zones is kept: positions are appended zone by zone."""
        if doc_id in self._seen:
            raise ValueError(f"duplicate doc_id {doc_id!r}: every document must be added once")
        unknown = [zone for zone in zone_tokens if zone not in ZONE_INDEX]
        if unknown:
            raise ValueError(f"unknown zone(s) {unknown} in {doc_id!r}; allowed {ZONES}")
        self._seen.add(doc_id)
        num = len(self.doc_ids)
        self.doc_ids.append(doc_id)
        self.doc_meta[doc_id] = dict(meta)
        lengths: dict[str, int] = {}
        local: dict[str, list] = {}  # term -> [positions, [frequency in each zone]]
        for zone, tokens in zone_tokens.items():
            lengths[zone] = len(tokens)
            self._zone_tokens[zone] += len(tokens)
            zi = ZONE_INDEX[zone]
            for pos, token in enumerate(tokens):
                entry = local.get(token)
                if entry is None:
                    entry = local[token] = [[], [0] * len(ZONES)]
                entry[0].append(pos)
                entry[1][zi] += 1
        self.doc_lengths[doc_id] = lengths
        norm = 0.0
        terms = self._terms
        for term, (positions, per_zone) in local.items():
            buf = terms.get(term)
            if buf is None:
                buf = terms[term] = _TermBuf()
            packed = 0
            exact = False
            for zi, n in enumerate(per_zone):
                if n >= _LANE_MAX:
                    exact = True
                packed |= min(n, _LANE_MAX) << (_LANE_BITS * zi)
            if exact:
                if buf.over is None:
                    buf.over = {}
                buf.over[len(buf.docs)] = tuple(per_zone)
            buf.docs.append(num)
            buf.zc.append(packed)
            buf.cnt.append(len(positions))
            buf.pos.extend(positions)
            norm += (1.0 + math.log10(len(positions))) ** 2
        self.doc_norms.append(math.sqrt(norm))

    def finish(self) -> "InvertedIndex":
        """Pack the per-term buffers into the shared arrays (consuming them, so memory does not double) and return the index."""
        total_positions = sum(self._zone_tokens.values())
        off_code = "I" if total_positions < (1 << 32) else "Q"
        terms = sorted(self._terms)
        t_start = array("I", [0])
        p_doc, p_zc = array("I"), array("Q")
        p_off, pos = array(off_code, [0]), array("I")
        overflow: dict[int, tuple[int, ...]] = {}
        running = 0
        for term in terms:
            buf = self._terms.pop(term)
            base = len(p_doc)
            p_doc.extend(buf.docs)
            p_zc.extend(buf.zc)
            pos.extend(buf.pos)
            for c in buf.cnt:
                running += c
                p_off.append(running)
            if buf.over:
                for local_i, exact in buf.over.items():
                    overflow[base + local_i] = exact
            t_start.append(len(p_doc))
        idx = InvertedIndex()
        idx._adopt(
            terms=terms, t_start=t_start, p_doc=p_doc, p_zc=p_zc, p_off=p_off, pos=pos, zc_overflow=overflow,
            doc_ids=self.doc_ids, doc_meta=self.doc_meta, doc_lengths=self.doc_lengths, doc_norms=self.doc_norms,
            stats={"docs": len(self.doc_ids), "terms": len(terms), "postings": len(p_doc), "positions": len(pos),
                   "tokens": total_positions, "zone_tokens": dict(self._zone_tokens)},
        )
        return idx


# --------------------------------------------------------------------------------------------------
# Reading
# --------------------------------------------------------------------------------------------------
class TermPostings:
    """One term's postings, as indices into the shared arrays. Nothing is decoded until it is asked for."""

    __slots__ = ("_ix", "lo", "hi")

    def __init__(self, index: "InvertedIndex", lo: int, hi: int) -> None:
        self._ix, self.lo, self.hi = index, lo, hi

    @property
    def df(self) -> int:
        return self.hi - self.lo

    def docs(self) -> array:
        """Document numbers, increasing."""
        return self._ix.p_doc[self.lo:self.hi]

    def find(self, doc_num: int) -> int:
        """The index of the posting of that document, or -1 (binary search)."""
        p_doc = self._ix.p_doc
        i = bisect_left(p_doc, doc_num, self.lo, self.hi)
        return i if i < self.hi and p_doc[i] == doc_num else -1

    def tf(self, i: int) -> int:
        p_off = self._ix.p_off
        return p_off[i + 1] - p_off[i]

    def zone_tfs(self, i: int) -> tuple[int, ...]:
        """Frequency in each zone, in ZONES order."""
        packed = self._ix.p_zc[i]
        lanes = tuple((packed >> (_LANE_BITS * z)) & _LANE_MAX for z in range(len(ZONES)))
        if _LANE_MAX in lanes:
            return self._ix.zc_overflow[i]
        return lanes

    def positions(self, i: int) -> list[int]:
        """The posting's positions in the order the old index stored them (zone by zone, each zone numbered from 0)."""
        ix = self._ix
        return ix.pos[ix.p_off[i]:ix.p_off[i + 1]].tolist()


class PostingList(Mapping):
    """doc_id -> {"positions": [...], "zones": {zone: tf}, "tf": n} for one term, decoded one document at a time."""

    __slots__ = ("_ix", "_tp")

    def __init__(self, index: "InvertedIndex", tp: TermPostings) -> None:
        self._ix, self._tp = index, tp

    def __getitem__(self, doc_id: str) -> dict[str, Any]:
        num = self._ix.doc_num_of.get(doc_id) if isinstance(doc_id, str) else None
        i = -1 if num is None else self._tp.find(num)
        if i < 0:
            raise KeyError(doc_id)
        return self._ix._entry(self._tp, i, num)

    def __iter__(self) -> Iterator[str]:
        ids, p_doc = self._ix.doc_ids, self._ix.p_doc
        for i in range(self._tp.lo, self._tp.hi):
            yield ids[p_doc[i]]

    def __len__(self) -> int:
        return self._tp.df

    def __contains__(self, doc_id: object) -> bool:
        num = self._ix.doc_num_of.get(doc_id) if isinstance(doc_id, str) else None
        return num is not None and self._tp.find(num) >= 0


class PostingsMap(Mapping):
    """term -> PostingList; a read-only view over the compact arrays that behaves like the old dict of dicts."""

    __slots__ = ("_ix",)

    def __init__(self, index: "InvertedIndex") -> None:
        self._ix = index

    def __getitem__(self, term: str) -> PostingList:
        tp = self._ix.term_postings(term) if isinstance(term, str) else None
        if tp is None:
            raise KeyError(term)
        return PostingList(self._ix, tp)

    def __iter__(self) -> Iterator[str]:
        return iter(self._ix.terms)

    def __len__(self) -> int:
        return len(self._ix.terms)

    def __contains__(self, term: object) -> bool:
        return isinstance(term, str) and self._ix.term_postings(term) is not None


class InvertedIndex:
    """term -> postings {doc_id: {'positions': [...], 'zones': {zone: tf}, 'tf': n}}, plus parametric metadata, in compact arrays."""

    def __init__(self) -> None:
        self._adopt(
            terms=[], t_start=array("I", [0]), p_doc=array("I"), p_zc=array("Q"), p_off=array("I", [0]), pos=array("I"),
            zc_overflow={}, doc_ids=[], doc_meta={}, doc_lengths={}, doc_norms=array("d"),
            stats={"docs": 0, "terms": 0, "postings": 0, "positions": 0, "tokens": 0, "zone_tokens": {zone: 0 for zone in ZONES}},
        )

    def _adopt(self, *, terms, t_start, p_doc, p_zc, p_off, pos, zc_overflow, doc_ids, doc_meta, doc_lengths, doc_norms, stats) -> None:
        self.terms: list[str] = terms
        self.t_start, self.p_doc, self.p_zc, self.p_off, self.pos = t_start, p_doc, p_zc, p_off, pos
        self.zc_overflow: dict[int, tuple[int, ...]] = zc_overflow
        self.doc_ids: list[str] = doc_ids
        self.doc_meta: dict[str, dict[str, Any]] = doc_meta
        self.doc_lengths: dict[str, dict[str, int]] = doc_lengths
        self.doc_norms = doc_norms  # lnc document-vector lengths, by document number (the cosine normaliser)
        self.stats: dict[str, Any] = stats
        self.doc_num_of: dict[str, int] = {doc_id: n for n, doc_id in enumerate(doc_ids)}
        self.doc_total_length = array("I", (sum(doc_lengths[d].values()) for d in doc_ids))  # tokens per document, all zones
        self.postings_map = PostingsMap(self)

    # ---------------------------------------------------------------- building
    @classmethod
    def build(cls, judgments: Iterable[Judgment]) -> "InvertedIndex":
        builder = IndexBuilder()
        with memoised_tokenizer():
            for j in judgments:
                builder.add(j)
        return builder.finish()

    # ---------------------------------------------------------------- saving and loading
    def save(self, directory: Path | str = INDEX_DIR) -> None:
        p = Path(directory)
        p.mkdir(parents=True, exist_ok=True)
        out_file = p / INDEX_FILE
        tmp_file = p / f"{INDEX_FILE}.tmp{os.getpid()}"
        arrays = [("t_start", self.t_start), ("p_doc", self.p_doc), ("p_zc", self.p_zc), ("p_off", self.p_off), ("pos", self.pos),
                  ("doc_norms", self.doc_norms)]
        header = {
            "format": FORMAT_VERSION, "byteorder": sys.byteorder, "terms": self.terms, "doc_ids": self.doc_ids, "doc_meta": self.doc_meta,
            "doc_lengths": self.doc_lengths, "stats": self.stats, "zc_overflow": self.zc_overflow,
            "arrays": [(name, a.typecode, len(a)) for name, a in arrays],
        }
        try:
            with gzip.open(tmp_file, "wb", compresslevel=3) as f:
                pickle.dump(header, f, protocol=5)
                for _, a in arrays:
                    raw = memoryview(a).cast("B")
                    for start in range(0, len(raw), _CHUNK):
                        f.write(raw[start:start + _CHUNK])
            os.replace(tmp_file, out_file)
        finally:
            if tmp_file.exists():
                tmp_file.unlink()
        print(f"Saved compact index ({out_file.stat().st_size / (1024 * 1024):.2f} MB) to {out_file}")

    @classmethod
    def load(cls, directory: Path | str = INDEX_DIR) -> "InvertedIndex":
        in_file = Path(directory) / INDEX_FILE
        if not in_file.exists():
            raise FileNotFoundError(f"Index file {in_file} not found. Run 'python -m m1_index.index build' first.")
        with open(in_file, "rb") as probe:
            magic = probe.read(2)
        if magic != b"\x1f\x8b":
            raise RuntimeError(f"{in_file} is in an older index format. Rebuild it with 'python -m m1_index.index build'.")
        with gzip.open(in_file, "rb") as f:
            header = pickle.load(f)
            if not isinstance(header, dict) or header.get("format") != FORMAT_VERSION:
                raise RuntimeError(f"{in_file} is in an older index format. Rebuild it with 'python -m m1_index.index build'.")
            loaded: dict[str, array] = {}
            for name, typecode, length in header["arrays"]:
                a = array(typecode)
                remaining = length * a.itemsize
                while remaining:
                    chunk = f.read(min(remaining, _CHUNK))
                    if not chunk:
                        raise RuntimeError(f"{in_file} is truncated. Rebuild it with 'python -m m1_index.index build'.")
                    a.frombytes(chunk)
                    remaining -= len(chunk)
                if header["byteorder"] != sys.byteorder:
                    a.byteswap()
                loaded[name] = a
        idx = cls()
        idx._adopt(terms=header["terms"], zc_overflow=header["zc_overflow"], doc_ids=header["doc_ids"], doc_meta=header["doc_meta"],
                   doc_lengths=header["doc_lengths"], stats=header["stats"], **loaded)
        return idx

    # ---------------------------------------------------------------- reading
    @property
    def num_docs(self) -> int:
        return len(self.doc_ids)

    @property
    def avg_doc_length(self) -> float:
        return (sum(self.doc_total_length) / len(self.doc_total_length)) if self.doc_total_length else 0.0

    def term_postings(self, term: str) -> TermPostings | None:
        """The term's postings, or None when the term is not in the index."""
        terms = self.terms
        t = bisect_left(terms, term)
        if t == len(terms) or terms[t] != term:
            return None
        return TermPostings(self, self.t_start[t], self.t_start[t + 1])

    def _entry(self, tp: TermPostings, i: int, num: int) -> dict[str, Any]:
        tfs = tp.zone_tfs(i)
        zones = {}
        for zone in self.doc_lengths[self.doc_ids[num]]:  # the document's own zone order, as the old index kept it
            n = tfs[ZONE_INDEX[zone]]
            if n:
                zones[zone] = n
        positions = tp.positions(i)
        return {"positions": positions, "zones": zones, "tf": len(positions)}

    def postings(self, term: str, zone: str | None = None) -> list[tuple[str, list[int]]]:
        tp = self.term_postings(term)
        if tp is None:
            return []
        zone_lane = None if zone is None else ZONE_INDEX.get(zone)
        if zone is not None and zone_lane is None:
            return []
        res = []
        for i in range(tp.lo, tp.hi):
            if zone_lane is not None and not tp.zone_tfs(i)[zone_lane]:
                continue
            res.append((self.doc_ids[self.p_doc[i]], tp.positions(i)))
        return res

    def df(self, term: str) -> int:
        tp = self.term_postings(term)
        return 0 if tp is None else tp.df

    def top_terms(self, n: int) -> list[tuple[str, int]]:
        """The n terms with the highest document frequency, as (term, df); ties in alphabetical order."""
        t_start = self.t_start
        best = heapq.nsmallest(n, range(len(self.terms)), key=lambda t: (-(t_start[t + 1] - t_start[t]), t))
        return [(self.terms[t], t_start[t + 1] - t_start[t]) for t in best]

    def memory_bytes(self) -> int:
        """Bytes held by the flat arrays (the term strings and the document tables are small next to them)."""
        return sum(a.itemsize * len(a) for a in (self.t_start, self.p_doc, self.p_zc, self.p_off, self.pos, self.doc_norms))


# --------------------------------------------------------------------------------------------------
# Command line
# --------------------------------------------------------------------------------------------------
def _read_judgments(path: Path) -> Iterator[Judgment]:
    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            if line.strip():
                yield Judgment.from_dict(json.loads(line))


def build_from_processed(judgments_path: Path | str | None = None, index_dir: Path | str | None = None) -> int:
    """Build the index from judgments.jsonl (read as a stream, so memory does not grow with the corpus) and save it."""
    jpath = Path(judgments_path) if judgments_path else JUDGMENTS_PATH
    if not jpath.exists():
        print(f"Error: {jpath} does not exist.")
        return 1
    with open(jpath, "r", encoding="utf-8") as f:
        total = sum(1 for line in f if line.strip())
    print(f"Building index over {total} judgments...")
    idx = InvertedIndex.build(_read_judgments(jpath))
    s = idx.stats
    print(f"{s['docs']} documents, {s['terms']} terms, {s['postings']} postings, {s['positions']} positions "
          f"({idx.memory_bytes() / (1024 * 1024):.1f} MB of arrays in memory)")
    idx.save(Path(index_dir) if index_dir else INDEX_DIR)
    return 0


def main(argv: list[str] | None = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    cmd = args[0] if args else "build"
    if cmd == "build":
        rest = args[1:]
        jpath = rest[rest.index("--judgments") + 1] if "--judgments" in rest else None
        out = rest[rest.index("--out") + 1] if "--out" in rest else None
        return build_from_processed(jpath, out)
    if cmd == "stats":
        print(json.dumps(InvertedIndex.load().stats, indent=2))
        return 0
    print("usage: python -m m1_index.index [build [--judgments FILE] [--out DIR] | stats]")
    return 2


if __name__ == "__main__":
    sys.exit(main())
