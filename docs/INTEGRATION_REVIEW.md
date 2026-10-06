# Integration review: M1, M2, M3 and M4 together (2026-10-06)

What was done when the four branches were merged into `m4-rank`: every module's code was read, its tests and artefacts were
run, the modules were connected and run end to end on **real judgments**, and each module was attacked with random and hostile
input. This is a review of the code as it stood, not of retrieval quality: no hand-made judged queries exist yet, so nothing here
says how well LexShift ranks.

## What was run, and what was real

| Piece | Real or stand-in |
|---|---|
| Corpus | M1's committed 200 judgments (all 2025), plus three older judgments downloaded from the public AWS bucket: Suresh Kumar Koushal (2013), Navtej Singh Johar (2018), Joseph Shine (2018). About 8.5 MB, kept outside the repo |
| M1 search, M2 parser, extractor and continuity, M3 extractor, resolver, windows, bench check, PageRank, `health()`, `authority()`, M4 `rank()`, demo, pooling | real code on that data |
| **Treatment labels** | **a keyword stand-in**, used only to exercise the pipeline. There is no Gemini key and no hand-labelled gold set. The labels, the F1 table and the quality of M3's classifier are untested |
| Judged queries, grades, gold overrulings | do not exist yet (they are made by hand) |

Reproduce: `python -m pytest`, `python eval/smoke.py`, and **`python -m eval.conformance`**, which reads each module's real
artefacts and calls its real functions and prints the findings below grouped by module (it exits 1 on a FAIL). The randomised
and scaling tests are in `tests/test_robustness.py`; the connection tests are in `tests/test_integration_connections.py` and
`tests/test_m4_m3_integration.py`.

## Where each module stands

| Module | Code | Connected to the others as pushed | After the fixes on `m4-rank` | Still open for the owner |
|---|---|---|---|---|
| **M1** | Boolean, phrase, proximity and BM25 ranking are correct (checked against brute force) | **No**: could not be imported on any other machine, returned hits the contract rejects, rejected every multi-word query | Yes | Data contract (dates, benches), zone splitter, build commands, tests, one parser bug, size |
| **M2** | A minimal hour-0 extractor and parser: works for `IPC 302` and `Section 103 of the BNS` only | Switched itself on while its data file was missing, so the shared smoke gate failed | Switch set back to `true` | Most statute forms, bare-number resolution, offence ids, false positives, the mapping table |
| **M3** | Complete against the Build Guide; runs end to end on real text | **No**: crashed on M1's date format; silently skipped exact-key resolution; could not read recent coram lines | Yes | Cache key, evidence choice, gold-set tooling, appeal-history heuristic, checks on M1's output |
| **M4** | Done (see section M4) | Yes | n/a | Hand-made queries and grades |

Legend for the tables: **Fixed** means the fix is on `m4-rank` (the smallest edit that makes the connection work, listed in
DECISIONS.md D-025 so the owner can take it or replace it); **Open** means the owner must act.

---

## M1: corpus, index, search

| # | Severity | Finding | State |
|---|---|---|---|
| 1 | Blocker | `search.py` read its index from `Path.home() / "lexshift" / "data/processed/inverted_index.json"`, a clone folder on one machine, and `searcher.py` read different files (`data/processed/index/`). `import m1_index` failed with `FileNotFoundError` anywhere else | **Fixed** (repository-relative paths) |
| 2 | Blocker | `searcher.py` defined its own `Hit` class instead of `common.schema.Hit`, so every result failed the contract check (`hit[0] is Hit, expected common.schema.Hit`) | **Fixed** (imports the shared class; M4 also accepts a foreign class with the same fields) |
| 3 | Blocker | Any query without explicit operators raised `ValueError: Unexpected token`: `BNS 103`, `punishment for murder under section 103 BNS`, `cheating and dishonestly inducing delivery of property`. Only single words and Boolean syntax worked, so the headline demo query failed | **Fixed** (plain text is ranked as a bag of words; `3(5)` and `u/s` are not treated as operators) |
| 4 | High | Importing the package built a 70 MB engine (11 s) and printed five lines to stdout, which corrupts `--json` | **Fixed** (built on first use, no printing) |
| 5 | High | `parse_atom` raises `IndexError`, not `ValueError`, when a query ends after an operator or an open parenthesis (`murder AND`, `(`). Found by randomised input | **Open** (`tests/test_robustness.py`, marked as a known failure; the demo now reports it as one clear line) |
| 6 | High | `judgments.jsonl` violates the shared `Judgment` contract in **0 of 200** records: `date` is `02 January 2025`, the contract says `2025-01-02`. M1's own year filter returned 0 hits for `year=2025` and raised `TypeError` for `min_year`; M3 crashed | Code **fixed** (year read from either shape). **Open**: the data must be regenerated with ISO dates, in `judgments.jsonl` and the tokenised copy |
| 7 | High | `bench_size` is wrong. 27 records have `0` (invalid; 14 of them print the coram line in the text); records with 3 or more judges are never right (0 of 10: stored as 2 or 0); overall 105 of 122 agree with the printed coram line. M3's bench check needs this: a larger bench can never be recognised | **Open** |
| 8 | Medium | `nltk` was not in `requirements.txt` and the stop-word corpus must be downloaded: a clean clone failed at import with a `LookupError` | **Fixed** (`nltk` declared, clear message, CI downloads it) |
| 9 | Medium | The zone splitter hard-codes paragraph numbers (paragraphs 1-4 facts, 5-6 arguments, 12 and up holding, 7-11 in no zone; a comment says "for this judgment"). Text outside every zone is invisible to BM25: 3 of 66 matches for `murder` score exactly 0. For a long judgment `holding` is nearly the whole text, so zone weights mean little | **Open** |
| 10 | Medium | The corpus cannot be rebuilt from the repo: `ingest.py`, `index.py` and `scoring.py` are still skeletons, so `make download` and `make build-index` print "not implemented". `parser.py` is byte-identical to `query_parser.py`, `text_tokenizer.py` to `tokenizer.py`. 90 MB of derived data (index, tokenised copy) is committed. No tests were committed | **Open** |
| 11 | Medium | The sample is one year (2025). Older citations cannot resolve and no precedent can be overruled inside the corpus, so the treatment signal has nothing to find; the evaluation needs older cases. Control characters (`\x08`, `\x07`) are in all 200 texts (184 headnotes) | **Open**; M4 now strips them for display |
| 12 | Low | Scale: the index is 0.171 MB of JSON per judgment (measured), so about 5 GB at 30,000 judgments (an extrapolation), loaded into memory twice (`RankedSearchEngine` and `SearchEngine` each load it). The laptop-CPU requirement is at risk at full size | **Open** |

**What to send M1**
> Your Boolean, phrase and proximity logic is correct (I checked it against brute force). Before it could be used I changed
> `search.py` and `searcher.py` (paths, shared `Hit`, plain-text queries, lazy engine, year filter) and the two tokenizers
> (clear NLTK message): please keep those, or replace them with your own fix. What only you can do:
> (1) regenerate `judgments.jsonl` and the tokenised copy with ISO dates (`2025-01-02`); (2) fix `bench_size`: read the coram line
> (`[A, B and C, JJ.]`, with `*` marking the author) and never write 0, use null when unknown; every 3+ judge bench is currently
> wrong; (3) make `parse_atom` raise `ValueError` at the end of input; (4) replace the hard-coded paragraph numbers in `zones.py`;
> (5) implement `ingest.py` and `index.py` so `make build-index` rebuilds the corpus, stop committing the index and the tokenised
> copy, and add tests; (6) add older judgments (the overruling cases) to the sample. Run `python -m eval.conformance --module m1`.

---

## M2: statutes and continuity

| # | Severity | Finding | State |
|---|---|---|---|
| 1 | High | `stubs.statute` was set to `false` while `doc_statutes.jsonl` is not committed, so `python eval/smoke.py` failed out of the box (`doc_statutes.jsonl: missing`). The team rule is to flip it in the commit that makes smoke pass | **Fixed** (set back to `true`; flip it in the commit that adds the sample's file) |
| 2 | High | `parse_query` reads **2 of the 9** statute forms the Build Guide lists. Failing: `u/s 302/34 IPC` (nothing found), `Section 302 read with 34 IPC`, `S. 302 I.P.C.`, `Sections 302 and 307 of the Indian Penal Code`, `Section 482 Cr.P.C.` (all give act `UNKNOWN`), `BNS 3(5)` (read as `BNS 3`, a different provision), `section 120-B IPC` (the `B` is lost) | **Open** |
| 3 | High | A bare number is never resolved from the offence date: `section 103` dated 2025 and dated 2020 are both `UNKNOWN 103`, so every type D query and every doctrine query that names only a number (`377`, `438`, `498A`, `497`, `80`, `318`) gets no statutory signal. Prose offences (`sedition`, `adultery`, `mob lynching`) give none either, and `offence_id` is never filled (0 of 691 references), so M3's point-level health cannot work | **Open** |
| 4 | High | Extraction quality on the 200 real judgments, against an independent reference regex (not hand labels): M2 finds about 35% of the (judgment, act, section) pairs the reference sees (488 of 1,387) and 71% of M2's pairs are also in the reference. The misses are spelled-out acts (`Code of Criminal Procedure`, `Indian Penal Code`) and lists (`Sections 147, 148, 323, 324, 307 and 302 of the IPC` yields only `302`). The false positives are paragraph numbers read as sections: of 206 act-first matches, 149 (72%) are `IPC. 16. Thus ...` with no `Section` word; about 110 of 691 stored references (16%) look like this | **Open** |
| 5 | Medium | `statute_map.csv` has one row (IPC 302 to BNS 103) against a plan of 20 to 40, and cites two blog posts rather than the official MHA or PRS tables | **Open** |
| 6 | Medium | `continuity()` special-cases ids starting `STUB-` (a real function that knows about stubs; this is why the demo showed a meaningless 0.00 as if it were real), and returns 0.0 silently for a document it has no data on, recording it in a module-level set and a log line. M3's `health()` raises for the same case. 0.0 therefore means both "no information" and "no match" | **Open** (M4 now treats every signal as stub when search is stub) |
| 7 | Medium | `extract_refs` is quadratic in the matches per document: 59 s on a 320,000-character text of repeated `IPC. 1. `. Real judgments have far fewer matches, so this matters for hostile or very long input | **Open** (known failure marked in `tests/test_robustness.py`) |
| 8 | Low | M2's tests live in `m2_statute/tests/` and were not collected by `pytest`; the module loads config with its own `load_config` (ignoring `LEXSHIFT_CONFIG`); `lru_cache` on the document table goes stale if the file is rebuilt in the same process; the skeleton docstrings were left in `mapping.py` and `extractor.py` | `pytest.ini` now collects M2's tests; the rest **Open** |

**What to send M2**
> Your extractor runs on the real corpus (172 of 200 judgments get references) and your 8 tests pass. I set `stubs.statute` back to
> `true` because `doc_statutes.jsonl` is not committed and the smoke gate failed; flip it when you commit that file for the sample.
> To do, in order of effect: (1) the act-first pattern reads paragraph numbers after `IPC.` and `CrPC.` as sections (72% of its
> matches; `u/s. 125 CrPC. 10. We have heard` gives `CrPC 10`): require a `Section`/`u/s` word or no full stop; (2) support the forms
> the Build Guide lists: lists (`302/34`, `302 and 307`, `r/w 34`), `Indian Penal Code`, `I.P.C.`, `Cr.P.C.`, `Code of Criminal
> Procedure`, `3(5)`, `120-B` (normalise to `120B`); (3) resolve a bare number from the offence date (`section 103` dated 2025 is `BNS 103`,
> dated 2020 `IPC 103`) and fill `offence_id`; (4) grow `statute_map.csv` towards 20-40 rows from the official tables; (5) drop the
> `STUB-` special case; (6) the pair-checking loop in `extract_refs` is quadratic; (7) use `common.config.load_config`. Run
> `python -m eval.conformance --module m2` and `python -m pytest`.

---

## M3: citations and treatment

Real-data results (203 judgments, stand-in labels): 8,896 mentions; 147 resolved to a corpus judgment (1.7%; 122 of the 4,761
mentions that carry a Supreme Court reporter citation); 43 tagged appeal history (all unresolved); `health(Koushal)` is 0.1 with evidence from
the 5-judge Navtej bench and no other judgment is lowered; `python -m eval.conformance --module m3` has 0 FAIL.

| # | Severity | Finding | State |
|---|---|---|---|
| 1 | High | The LLM cache key is `sha256(prompt version, model, window)` and omits the few-shot examples, although its docstring says everything that can change the answer is in the key. Labelling once without examples and again with them makes **zero new API calls** and keeps the first label (verified). Windows labelled before the gold set exists stay zero-shot forever, yet the F1 table would say "few-shot" | **Open** |
| 2 | High | `gold merge` rewrites `disagreements.csv` from the current sheets on every run: if the second labeller's sheet is missing or empty the typed adjudications are wiped, and `treatment_gold.csv` shrinks, silently (verified). It also accepts a sheet with 247 of 250 windows blank without saying so, and writes non-atomically | **Open** |
| 3 | Medium | `same_parties` treats different cases with a shared party name as one dispute (`Ram Singh v. State of Bihar` and `Ram Singh v. State of U.P.` is `True`): a real precedent edge would be tagged appeal history and dropped | **Open** |
| 4 | High | Three silent dependencies on M1: the `doc_id` shape, `reporter_citations`, and bench sizes. All three were broken in the real data (see M1 6 and 7): the resolver silently skipped exact-key resolution, the coram reader read 0 of 122 recent coram lines, and it crashed on the date | **Fixed** (`_EN` suffix accepted, year read from any shape, mixed-case coram lines read). **Open**: report how many negatives the bench check discards and fail loudly when the corpus has no usable benches |
| 5 | Medium | Evidence quality on real text: the window picked as evidence is the *headnote's "Case Law Cited" list* ("... Suresh Kumar Koushal ... [2013] 17 SCR 1019 - overruled Naz Foundation v. Govern...", "... Lalita Kumari ... - followed. List of Acts ...") rather than the sentence in the reasoning that overrules. Ties are broken by confidence, then citing id, not by how informative the window is | **Open** |
| 6 | Low | Name extraction keeps neighbouring words (`A Constitution Bench in Bachan Singh v. State of Punjab`, `Ram Kishan Vs. State of Haryana the Court`, `Bench v. Bar` read as a case) and margin letters inside names (`Naz B Foundation`) | **Open** |
| 7 | Low | Appeal-history tagging applies to non-Supreme-Court citations whose window contains `set aside`, `reversed` or `quashed`; a High Court decision cited for its holding is tagged. It cannot affect a score (a High Court case never resolves) but it inflates the statistic | **Open** |
| 8 | Low | The evidence window loses its `[[ ]]` marker in `citations.jsonl`, so no consumer can find the treating sentence | **Open** |
| 9 | Low | Memory and ergonomics: `run_health` loads every mention (with its window) into memory; `scores._table()` loads all evidence at the first call; commands print raw tracebacks when inputs are missing; `classify_llm` re-reads the cache per call; the Gemini model alias is not pinned | **Open** |

**What to send M3**
> The pipeline ran end to end on 203 real judgments and `doc_health.jsonl` passes the contract; with a stand-in labeller Koushal
> comes out at 0.1 from the 5-judge Navtej bench. I changed `resolver.py` in three places (accept the `_EN` suffix in `doc_id`, read
> the year from `02 January 2025`-style dates, read mixed-case coram lines like `[C.T. Ravikumar* and Sanjay Kumar, JJ.]`):
> keep them or replace them. Please fix: (1) put the few-shot examples (or a hash of them) in the cache key and refuse to label
> zero-shot silently; (2) make `gold merge` leave `disagreements.csv` alone when an input is missing and report unlabelled windows;
> (3) prefer the reasoning sentence over a headnote citation list when choosing evidence, and keep the `[[ ]]` marker;
> (4) tighten `same_parties`; (5) report negatives discarded by the bench check, by reason. Run
> `python -m eval.conformance --module m3` after building.

---

## M4: ranking, evaluation, demo (ours)

Fixed during this integration, all with tests:

* A missing file or unknown id in a module (`KeyError`, `FileNotFoundError`) is one clear `ArtefactError`; an unloadable module (missing
  library or data) is reported the same way, and a module's printing during loading goes to stderr so `--json` stays valid.
* `rank()` accepts a foreign `Hit` class with the same fields (strict about content, tolerant about the carrier).
* **When search is a stub, every signal is flagged as stub**, even if its module is real: a "real" statute or treatment module
  was only asked about placeholder ids. This closes a hole where the demo labelled a meaningless 0.00 as real.
* The demo shows evidence in full (it had cut it at 220 characters, which ended before the overruling sentence), strips control
  characters (they are in every document M1 produced), turns an unexpected module error into one line with `--debug` for the
  traceback, and the pooling tool and ablation runner share the same loading and error handling.
* `pytest` collects M2's tests; the CI workflow downloads the NLTK stop words so M1's tests run there.
* New: `python -m eval.conformance`, the randomised and scaling tests, and the connection tests.

Still true of M4: `rel` is min-max scaled over the candidates, so a result's `rel` of 0 or 1 says where it falls among the 100,
not how strong the match is (DECISIONS.md D-006); the judged queries, grades and gold overruling list are not written.

## Order of work from here

1. M1: ISO dates, correct benches, a rebuild command, older judgments in the sample, then flip `stubs.search` once `smoke` passes.
2. M2: the extractor fixes, then commit the sample's `doc_statutes.jsonl` and flip `stubs.statute`.
3. M3: the cache key and gold-merge fixes, the Gemini run and the gold set, then build `doc_health.jsonl` and flip `stubs.health` and `stubs.authority`.
4. M4: with real modules on, write the queries, pool, grade, tune on dev, report on test.
5. Everyone: `python -m eval.conformance` and `python eval/smoke.py` must be clean before merging to `main`.
