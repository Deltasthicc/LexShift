# M1: corpus, indexing and search

Branch: `m1-index`. Turns the Supreme Court dump into a corpus file and a search index, and hands everyone `search(query, k=100, filters=None) -> list[Hit]`.
Contract and field list: [../docs/CONTRACTS.md](../docs/CONTRACTS.md). Every number below was measured by the commands shown; none is estimated.

## Status

**Done.** `stubs.search` is `false`. The corpus is **4,819 English Supreme Court judgments** (2005 to 2025, plus 8 named cases from 1962 to 1996), read from the public dataset by `ingest.py`; the
index over it is 52.7 MB on disk and 125 MB in memory, builds in about 140 s and loads in about 2 s; `search()` takes a median of 19.6 ms over the 16 benchmark queries (`python -m m1_index.benchmark`, `reports/benchmark.md`; 7.8 ms in an earlier run on a quieter machine, so read it as 10 to 20 ms).

| Piece | File | State |
|---|---|---|
| Catalog of the dataset (38,152 judgments, 38,147 with an English PDF) | `catalog.py` | done |
| Which judgments go into the corpus, and why | `selection.py` | done, rules below |
| Download, PDF to text, `judgments.jsonl`, pack and unpack | `ingest.py` | done, 42 tests |
| Zones: headnote, facts, arguments, holding | `zones.py` | done (a heuristic, see below) |
| Tokenizer: case folding, stop words, Porter stemming, statute and citation tokens kept whole | `tokenizer.py` | done |
| Inverted + positional + zone + parametric index, compact layout | `index.py` | done |
| Boolean, phrase and proximity parser (`/s`, `/p`, `/k`) | `query_parser.py` | done |
| BM25, lnc.ltc, heap top-K | `scoring.py`, `searcher.py` | done |
| Query optimisation (smallest posting list first, probes, early stop) | `searcher.py` | done, compared with the naive order in tests |
| Sanity check against `rank_bm25` and latency | `benchmark.py`, `reports/benchmark.md` | done |

## The corpus

The dataset is 38,147 English judgments (19.5 GB of PDF). It is not all loaded, and the reason is measured, not assumed: the live demo is offline on a laptop and keeps the index in memory, and
a grader's judgments of "is this good law" only mean something for the criminal-law part of the Court's work that the 30 queries are about. The rules (in `selection.py`, recorded in DECISIONS.md D-036):

1. **Named cases.** Both ends of every doctrine pair the judged queries are about (an overruled case and the judgment that overruled it, read off `eval/examples/query_grade_criteria.example.md`), by title and year.
   Every named case but one is in the corpus; *Mohan Lal v. State of Punjab* (2018) is not in the dataset at all.
2. **A criminal-law base, newest first.** Every English judgment of 2005 to 2025 whose title looks like a criminal matter (the State, the CBI, a narcotics or enforcement body, the police, ...) is downloaded and
   read; it stays only if its text mentions the criminal codes (IPC, BNS, CrPC, BNSS, NDPS, the Prevention of Corruption Act, POCSO, ...). 7,850 were downloaded and read, 4,819 are in the corpus (3,031 left out as not criminal law, 11 scans without a text layer).
   A second tier (`fetch --tier all`: every other title) exists and was **not** used: it is about 5.8 GB more for 2005 to 2025 and the coverage check below says the queries do not need it.

Nothing here looks at a relevance judgment (there are none yet) and none is ever used to choose a document. `data/corpus_manifest.csv` lists every judgment and why it is in.

| Measured on the corpus | |
|---|---|
| Judgments / years | 4,819: 4,811 from 2005 to 2025 (101 to 460 a year) and 8 older named cases (1962 to 1996) |
| Text | median 25,700 characters, mean 38,900, longest 1.8 million (*Puttaswamy*) |
| Zone share of the characters | headnote 17%, facts 18%, arguments 30%, holding 35% (it was 72% holding before the zone splitter was rewritten) |
| Bench size | known for 4,806 of 4,819: 2 judges 4,194, 3 judges 559, 5 judges 26, 9 judges 3, 4 judges 6, 1 judge 18 (a few of these are OCR damage in the older volumes; 13 have none) |
| Titles | reader-friendly (`Navtej Singh Johar v. Union of India`), no `X v. v.` |
| Queries with at least 10 candidate judgments (`python -m eval.feasibility --target 10`) | **26 of 30** (it was 4 of 30 at 468 judgments); `test20` (automatic vacation of a stay) has none containing all its words, `dev06`, `test07` and `test10` are thin |
| Both ends of an overruling pair present | 9 of 10 doctrines (the tenth, informant and investigator, lacks *Mohan Lal*, which is not in the dataset) |

Doc ids are the dataset's own path plus `_EN` (`2018_7_379_746_EN`). A `S_` prefix (`S_1985_1_741_749_EN`, 213 judgments) marks the supplementary SCR volumes.

### How to get it

```bash
make unpack          # a fresh clone: data/corpus/judgments.jsonl.xz (41 MB, tracked, SHA-256 checked) -> data/processed/judgments.jsonl. No network.
make build-index     # python -m m1_index.index build, about 140 s
# or, to rebuild the corpus from the public bucket (3.9 GB of PDFs for 2025-2005, about 1.5 to 2 hours at the 0.3 to 2.5 MB/s measured here):
python -m m1_index.ingest download --years 2025-2005   # catalog, fetch, build; resumable, deletes each PDF after reading it
make corpus          # pack the rebuilt judgments.jsonl into data/corpus/ (what is committed)
```

`ingest build` writes beside the target and moves the result into place only when it is complete; it refuses an empty result and one under half the size of the existing corpus (the old step emptied the file
when `data/raw` was empty).

## How search works (the IR the video explains)

* **Index.** One sorted vocabulary; every term's postings are slices of a few flat arrays (document number, per-zone term frequencies packed in four 16-bit lanes, positions). Positions restart at 0 in each zone, so
  a phrase or a `/k` proximity can be checked inside the merged positions of a document. Parametric fields (year, bench size) sit beside it for filters.
* **Queries.** `AND OR NOT`, `"phrases"`, `/s` and `/p` (within 5 tokens, the sentence and paragraph stand-in) and `/k`; precedence proximity, NOT, AND, OR; anything that does not parse is searched as a bag of words.
  An AND chain is evaluated smallest posting list first and stops when nothing is left; `a AND NOT b` is a difference, not a complement (`searcher.WorkStats` counts the postings read, so the saving is measurable).
* **Ranking.** Zone-weighted BM25 (k1 1.2, b 0.75; zone weights headnote 3.0, holding 2.5, facts 1.0, arguments 0.75) with a heap for the top K; lnc.ltc cosine (SMART notation) is implemented in `scoring.py`
  for comparison. The idf is ln(1 + (N - n + 0.5) / (n + 0.5)), positive for every term; `reports/benchmark.md` shows where `rank_bm25` differs (terms in about half the corpus) and by how much.
* **Libraries.** PyMuPDF turns a PDF into text; pyarrow reads the dataset's metadata parquet; NLTK gives the Porter stemmer and stop-word list; `rank_bm25` is used only in the benchmark. Every IR step is our code.

## Limits, stated

* Zones are a heuristic (headings and position), not an annotation. A headnote longer than 15,000 characters is cut there and the rest counts as facts.
* PDF text of the older volumes is OCR; names in the coram line are sometimes garbled (the count of judges is right, a name may not be). 1 judgment has no bench size.
* The corpus is criminal-law judgments of 2005 to 2025 plus the named cases: a doctrine's precedents from before 2005 that are not named are not in it, so citations to them cannot resolve (M3's resolution rate is
  16% of mentions, most of the rest being High Court and pre-2005 decisions).
* One judgment the bucket lists (`2009_9_810_820_EN`) answers 404 and is missing.
* `/s` and `/p` are within 5 tokens; the index stores no sentence or paragraph boundaries.

## Tests

`python -m pytest tests/test_m1_*.py` (ingest, selection, catalog, tokenizer, parser, scoring, golden queries on real excerpts, and a differential test of the compact index and the optimised engine against
a plain reference on random corpora and queries).
