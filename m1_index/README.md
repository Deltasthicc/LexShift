# M1: corpus, indexing and search

Branch: `m1-index`. Everyone else's work depends on your corpus file first, then on `search()`.

**Goal.** Turn the Supreme Court dump into a searchable index that returns the top candidates with relevance scores.

## What you build

- [ ] Download English Supreme Court judgments from the AWS Open Data bucket (public, no AWS account, CC-BY-4.0), extract
      text from PDFs, keep criminal-law judgments (mentions of IPC, BNS, CrPC or BNSS). `ingest.py`
- [ ] **200-document sample of `judgments.jsonl` by hour 3, the full file by hour 8.** M2 and M3 depend on it
- [ ] Zone splitter: headnote, facts, arguments, holding. A rough heuristic split on headings and position is fine. `zones.py`
- [ ] Text processing: case folding, stop words, Porter stemming. Keep statute and citation tokens (for example `IPC_302`)
      unstemmed. `tokenizer.py`
- [ ] Inverted + positional index; zone fields; parametric fields (year, bench size). `index.py`
- [ ] Query parser: AND / OR / NOT, "phrases", proximity `/s` (sentence), `/p` (paragraph), `/k` (within k words); process
      terms in increasing document frequency. `query_parser.py`
- [ ] BM25 (baseline) and lnc.ltc cosine; heap-based top-K. Stretch: tiered index with larger benches in tier 1. `scoring.py`
- [ ] `search()` ties it together. `searcher.py`
- [ ] Sanity check: compare your BM25 against a library BM25 (for example `rank_bm25`) on the real corpus and explain
      what the library does in IR terms. Library code never enters the live path.

## You hand over

`judgments.jsonl` (sample, then full), the index files, and `search(query, k=100, filters=None) -> list[Hit]`.
Contract and field list: [../docs/CONTRACTS.md](../docs/CONTRACTS.md).

## IR concepts you explain in the video

Tokenisation, normalisation, stemming, inverted and positional indexes, zones, parametric index, Boolean and proximity
queries, query optimisation, tf-idf, BM25, heap top-K, tiered index.

## Done when

A proximity query such as `"common intention" /s murder` returns ranked judgments on the full corpus in under a second,
and you can print the postings and scores for the video.

## Watch out for

PDF noise (page headers, page numbers, line breaks inside words). Do not over-engineer zones.

## Facts to verify first (record the outcome in `DECISIONS.md`)

The AWS registry page confirms the bucket `s3://indian-supreme-court-judgments` (region `ap-south-1`, no AWS account,
CC-BY-4.0, bi-monthly updates, 1950 to 2025, raw JSON metadata, parquet metadata and zip files of judgments). It does
**not** state the folder layout, the parquet schema, the size, or whether the judgments are PDFs or text: inspect a small
sample before building on any of those. Also measure how often BNS/BNSS appear and which citation formats occur, and
decide the corpus subset that keeps ranking meaningful and the index laptop-friendly.

## Hour 0-3 tasks

1. Inspect a small sample; settle the `doc_id` and write the facts into `DECISIONS.md`.
2. Ship the 200-document `judgments.jsonl` and tell the group how it is shared (`DECISIONS.md` OQ-1).
3. Replace the stub with a minimal real `search()` (even BM25 over whole documents); flip `stubs.search` to `false` once
   `python eval/smoke.py` passes.
