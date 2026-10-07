"""Inverted and positional index with zone and parametric support."""

from __future__ import annotations

import pickle
import sys
import zlib
from pathlib import Path
from typing import Any, Iterable

from common.schema import Judgment
from m1_index.tokenizer import tokenize

INDEX_DIR = Path("data/processed/index")


class InvertedIndex:
    """term -> postings {doc_id: {'positions': [...], 'zones': {zone: tf}}}, plus parametric metadata."""

    def __init__(self):
        self.postings_map: dict[str, dict[str, dict[str, Any]]] = {}
        self.doc_meta: dict[str, dict[str, Any]] = {}
        self.doc_lengths: dict[str, dict[str, int]] = {}

    @classmethod
    def build(cls, judgments: Iterable[Judgment]) -> "InvertedIndex":
        idx = cls()
        for j in judgments:
            doc_id = j.doc_id
            year = int(j.date[:4]) if (j.date and len(j.date) >= 4) else None
            idx.doc_meta[doc_id] = {
                "year": year,
                "bench_size": j.bench_size,
                "title": j.title,
                "date": j.date,
            }
            idx.doc_lengths[doc_id] = {}

            # Index across zones
            for zone, zone_text in j.zones.items():
                tokens = tokenize(zone_text)
                idx.doc_lengths[doc_id][zone] = len(tokens)

                for pos, token in enumerate(tokens):
                    if token not in idx.postings_map:
                        idx.postings_map[token] = {}
                    if doc_id not in idx.postings_map[token]:
                        idx.postings_map[token][doc_id] = {
                            "positions": [],
                            "zones": {},
                            "tf": 0,
                        }
                    idx.postings_map[token][doc_id]["positions"].append(pos)
                    idx.postings_map[token][doc_id]["zones"][zone] = (
                        idx.postings_map[token][doc_id]["zones"].get(zone, 0) + 1
                    )
                    idx.postings_map[token][doc_id]["tf"] += 1

        return idx

    def save(self, directory: Path | str = INDEX_DIR) -> None:
        p = Path(directory)
        p.mkdir(parents=True, exist_ok=True)
        out_file = p / "index.pkl.gz"
        payload = {
            "postings": self.postings_map,
            "doc_meta": self.doc_meta,
            "doc_lengths": self.doc_lengths,
        }
        compressed = zlib.compress(pickle.dumps(payload, protocol=5))
        with open(out_file, "wb") as f:
            f.write(compressed)
        print(f"Saved compact index ({len(compressed) / (1024*1024):.2f} MB) to {out_file}")

    @classmethod
    def load(cls, directory: Path | str = INDEX_DIR) -> "InvertedIndex":
        p = Path(directory)
        in_file = p / "index.pkl.gz"
        if not in_file.exists():
            raise FileNotFoundError(f"Index file {in_file} not found. Run 'make build-index' first.")
        with open(in_file, "rb") as f:
            raw = zlib.decompress(f.read())
            data = pickle.loads(raw)

        idx = cls()
        idx.postings_map = data["postings"]
        idx.doc_meta = data["doc_meta"]
        idx.doc_lengths = data["doc_lengths"]
        return idx

    def postings(self, term: str, zone: str | None = None) -> list[tuple[str, list[int]]]:
        if term not in self.postings_map:
            return []
        res = []
        for doc_id, p_data in self.postings_map[term].items():
            if zone is None or zone in p_data["zones"]:
                res.append((doc_id, p_data["positions"]))
        return res

    def df(self, term: str) -> int:
        return len(self.postings_map.get(term, {}))


def build_from_processed():
    import json
    from common.schema import Judgment

    jpath = Path("data/processed/judgments.jsonl")
    if not jpath.exists():
        print(f"Error: {jpath} does not exist.")
        return 1

    judgments = []
    with open(jpath, "r", encoding="utf-8") as f:
        for line in f:
            if line.strip():
                judgments.append(Judgment.from_dict(json.loads(line)))

    print(f"Building index over {len(judgments)} judgments...")
    idx = InvertedIndex.build(judgments)
    idx.save(INDEX_DIR)
    return 0


def main(argv: list[str] | None = None) -> int:
    args = argv or sys.argv[1:]
    cmd = args[0] if args else "build"
    if cmd == "build":
        return build_from_processed()
    return 0


if __name__ == "__main__":
    sys.exit(main())