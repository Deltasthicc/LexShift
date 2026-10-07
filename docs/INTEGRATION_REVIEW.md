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

## Update, 2026-10-07: what the remote branches hold now

Fetched `origin` and compared every branch with `m4-rank`. **Only `m1-index` moved** (one new commit, `287846e` "Normalize judgment dates to ISO format", merged
here). `main` (`76ad44c`), `m2-statute` (`f0a629d`) and `m3-treatment` (`7777a6b`) hold nothing that `m4-rank` does not already contain.

| After merging `287846e` | Result |
|---|---|
| `judgments.jsonl` dates | **Fixed**: 200 of 200 are ISO (`2025-01-02`); the date failure is gone from `eval.conformance` and from the smoke gate |
| `judgments.jsonl` against the `Judgment` contract | 173 of 200 valid; the 27 others have `bench_size` 0 (finding M1-7). With the real search and statute switched on, `eval/smoke.py` fails on exactly this and nothing else, so **`bench_size` is now the only thing between M1 and flipping `stubs.search`** |
| `data/processed/index/tokenized_judgments.jsonl` | **Not fixed**: still `29 May 2025` style dates in 200 of 200 records (M1's year filter reads either shape, so nothing breaks) |
| M3 on the merged corpus (extract and resolve only, no labels) | runs; 7,051 mentions, 51 resolved to a corpus judgment (0.7%), 20 distinct citing-to-cited edges, 477 tagged appeal history; bench known for 200 of 200 because M3 falls back to the coram line when `bench_size` is 0 |
| Whole suite | 519 passed, 2 expected failures (the known `parse_atom` and `extract_refs` cases) |
| `eval.feasibility` on the 30 candidate queries | 3 answerable, 17 thin, 10 empty (the 200 judgments are all from 2025) |

## Request tracker, 2026-10-07 (after the fifth pass, the 468-judgment corpus)

What each owner was asked to do in the earlier reviews, and where it stands in the code that is pushed.

| Owner | Asked for | State |
|---|---|---|
| **M1** | ISO dates in `judgments.jsonl` | **Done**; the tokenised copy is not regenerated (no longer read, still tracked) |
| | `bench_size` never 0, and right | **Done** (null when unknown; 294 of 306 agree with the coram line, 27 of 35 benches of 3 or more are right; one 5-judge bench is stored as 6) |
| | `parse_atom` raises `ValueError` | **Done** |
| | zones without hard-coded paragraph numbers | **Done in effect** |
| | a rebuild command, stop committing the index | **Half**: `python -m m1_index.index build` works (7.0 MB at 468 judgments); `ingest build` empties the corpus when `data/raw` is empty, `download()` is a no-op, the old 74 MB files are still tracked |
| | a larger corpus with older judgments | **Half**: **468 judgments, 2024 (268) and 2025 (200)**; nothing before 2024, so no overruled case of the doctrine queries is in it (see "Is the corpus enough?") |
| | titles | **New defect**: 259 of the 268 new records have the title cut to `X v. v.` (M1-19) |
| | tests for M1, lnc.ltc, query optimisation, library BM25 comparison | **Open** |
| | flip `stubs.search` | **Open, and possible**: with search and statute real the smoke gate passes |
| **M2** | paragraph numbers are not sections | **Done** |
| | the Build Guide's statute forms | **6 of 9** (`S. 302 I.P.C.`, `Cr.P.C.`, `BNS 3(5)` fail); `BNS 103` and `IPC 302` are read again |
| | `statute_map.csv` in the contract layout | **Done** (36 rows, valid); no official sources |
| | bare numbers resolved by the offence date | **Regressed**: the governing act is right but the section's act is `UNKNOWN` (4,053 of 7,266 references; M2-12) |
| | drop the `STUB-` special case, use `common.config.load_config` | **Open** |
| | commit `doc_statutes.jsonl` or build it in CI, then flip the switch | **Open** (CI now builds it; the switch is still `true` here) |
| **M3** | review fixes (cache key, gold merge, same parties, data checks) | **Done** (D-024) |
| | evidence is the reasoning sentence, keep the `[[ ]]` marker, running headers, appeal history, name extraction, memory and errors, pinned model, committed label cache | **Done** (D-033, `fbcc054`) |
| | the gold set (two labellers), the Gemini run, the F1 table, `citations.jsonl` and `doc_health.jsonl` for the corpus | **Open** (`data/treatment_gold.csv` has only its header) |
| | flip `stubs.health` and `stubs.authority` | **Open** (waits for the files above) |
| **M4** | everything in the build guide that code can do | **Done**; the queries are adopted; grading, the gold list, tuning and the test table need people and a bigger corpus |

## Sixth update, 2026-10-07 (night): the 4,819-judgment corpus; M1 and M2 finished, M3 waits for a key

`m3-treatment` (+1, labels and the .env key loading) and `main` (the simplified interface, pull request #7) were merged into `m4-rank`. M1's corpus, index and ingest, M2's extractor and the M3 labelling scope were
done in this branch at the owners' request (D-037, D-038). Measured here, not estimated:

| Measured | Before (468 judgments) | Now (4,819) |
|---|---|---|
| Corpus | 468: 2024 (268) and 2025 (200) | **4,819**: 2005 to 2025 criminal-law judgments plus 8 older named cases; read from the public bucket (7,850 PDFs, 3.9 GB) |
| Queries with at least 10 candidate judgments (`--target 10`) | 4 of 30; 6 with none | **26 of 30**; `test20` has none, `dev06`, `test07` and `test10` are thin |
| Doctrines with both an overruled and an overruling judgment | 0 of 10 | **9 of 10** (*Mohan Lal* is not in the dataset) |
| Search index | 7 MB, dict of dicts | **52.7 MB compact**, loads in about 2 s; full ranking of a query about 50 ms once warm |
| `eval.conformance --module m2` | 3 FAIL | **0 FAIL, 10 PASS**: 9 of 9 statute forms, bare numbers by offence date |
| Act UNKNOWN in M2's references | 56% to 68% | **37.2%** of 190,518 mentions |
| Offence ids on references | 1,402 of 32,075 | **12,441 of 65,036** |
| M3 `extract`: mentions / resolved / distinct edges / appeal history | 22,861 / 269 (1.7%) / 127 / 133 | **160,705 / 25,853 (16.1%) / 9,453 / 2,573 (1.6%)** |
| Tests | 561 passed | **805 passed, 1 skipped** (full run on the merged tree) |
| `python eval/smoke.py` (search and statute real) | 0 failed | **0 failed** |
| Judging round 1 (`eval.pool --configs b0,b1`, real systems only) | none | **680 documents for 30 queries**, about 1,360 judgements for two judges |

Fixed on the way: an `I.P.C.` / `Cr.P.C.` form never read (`\b` cannot follow a full stop, in M2's extractor and in the corpus filter); a sedition row that said `equivalent` (the PRS brief says it was removed);
a titles bug (`State through CBI v. v. Arul Kumar`); OCR'd coram lines (a lost bracket, `ANDLOKESHWAR`, `&`, a closing `J`); an invented default date (`2020-01-01`) in `ingest`; `STUB-` special case in `continuity()`;
a map scan per candidate that made a full ranking take 2 s; the integration tests that assumed a four-digit year at the start of every doc id.

| Lane | State | What is still needed |
|---|---|---|
| **M1** | **Done.** `stubs.search` is `false`. | nothing for the code; a person should skim `data/corpus_manifest.csv` and the limits in `m1_index/README.md` |
| **M2** | **Done except verification by people.** `stubs.statute` is `false`. | the other 35 map rows verified in two official sources (they cite only "MHA"); the 50-judgment precision check (`python -m m2_statute.audit_sample`) |
| **M3** | Code complete; **blocked on `GEMINI_API_KEY`** for the new corpus (1,010 windows, about 34 requests). `stubs.health` and `stubs.authority` stay `true`. | the key in `.env`, `python -m m3_treatment.pipeline label-llm`, `make m3`, then flip the two switches; the gold set (two labellers) and the F1 table |
| **M4** | Done as far as code goes. Pooled round 1; interface merged. | two judges grade `eval/judging/round1`; the gold overruling list (by hand); then `python -m eval.make_qrels`, `python -m eval.run_ablation --tune`, `--split test`; a second pooling round once M3 is real |

## Third update, 2026-10-07 (evening): the 468-judgment corpus

`m1-index` moved by four commits (`97b355c` "Update 468-document corpus and ingestion cleanup", and a merge of `main`), `m2-statute` by one (`c244ff1`), `m3-treatment` by one
(`fbcc054`, also on `main` through pull request #4). All were merged into `m4-rank` (one conflict, `pytest.ini`). `main` was not touched.

| Measured here | Before | Now |
|---|---|---|
| Corpus | 200 judgments, all 2025 | **468 judgments: 2024 (268) and 2025 (200)**, 55 with a bench of 3 or more |
| Search index | 2.6 MB | 7.0 MB; about 1.1 s to load, about 2 ms per query |
| `python eval/smoke.py` with search and statute real | failed (the map) | **0 failed** (first time) |
| Tests | 539 passed, 8 failed (all M2's) | **561 passed, 1 expected failure** |
| `eval.feasibility` on the 30 queries | 3 ok, 17 thin, 10 empty | **14 ok, 10 thin, 6 empty** |
| Queries with at least 10 candidate judgments (`--target 10`) | not measured | **4 of 30**; 20 have fewer, 6 have none |
| M3 `extract` (no labels), mentions / resolved / edges | 6,539 / 51 (0.8%) / 20 | 19,224 / 269 (1.4%) / 127 |

New findings:

| # | Severity | Finding |
|---|---|---|
| M1-19 | **High** | **259 of the 268 new 2024 records have their title cut to `X v. v.`** (for example `Satender Kumar Antil v. v.`): the text has `v.` on a line of its own and the respondent after it, and the extractor takes the `v.` twice. It shows in every result list, and it breaks M3's own-title test: the case's caption is then counted as appeal history (**2,762 tags, 14.4% of mentions, 2,728 of them in the 2024 part; the 2025 part has 34, 0.5%**). It also stops name-based citation resolution for those cases |
| M1-20 | Low | One 5-judge Constitution Bench (`2024_2_946_988_EN`) is stored as a bench of 6 |
| M2-12 | **High** | A bare section number is resolved to the right governing act but its own act stays `UNKNOWN`: `section 103` dated 2025-02-01 gives `UNKNOWN 103`, and **4,053 of 7,266 references in the corpus have act `UNKNOWN` (56%; it was 4 of 2,755)**. Type D queries (bare numbers) therefore get no continuity. `BNS 3(5)` is read as `BNS 3` |
| M2 | Fixed | `statute_map.csv` is valid (36 rows), `BNS 103` is read, the real `continuity()` runs, M2's own tests pass |
| M3 | Fixed | review findings 5 to 10 (D-033). Still no labels, no gold set, no `doc_health.jsonl` |

### Is the corpus enough? (measured with `python -m eval.feasibility --target 10`)

**No.** Counting, for each query, the judgments that contain all its content words (and mention the section where it names one): the median query has **3**, the
mean 4.5; 20 of 30 have fewer than 5; 6 have none (`dev02`, `dev06`, `test07`, `test14`, `test15`, `test20`). And the structural gap is larger than the counts:

* **No overruling pair is in the corpus.** Of the 25 cases the grading criteria name for the type C queries, only the *overruling* judgment of one doctrine (`High Court Bar
  Association, Allahabad`, 2024) is present, and its overruled partner (`Asian Resurfacing`, 2018) is not. *Koushal* and *Navtej*, *Joseph Shine*, *Puttaswamy*, *Sushila Aggarwal*,
  *Tofan Singh*, *Mukesh Singh*, *Mohan Lal*, *Arjun Panditrao* and the others are not documents here (some are cited by 3 to 21 judgments). Without both ends the treatment signal
  cannot lower anything and `harmful@10` has nothing to count. This needs **specific** judgments, from 2010 to 2023.
* **Nothing before 2024**, although type A queries need IPC-era precedents and type D needs both codes.
* Rare topics (sedition, mob lynching, organised crime, section 318 in either code) have 0 to 3 matches.

What it would take, as estimates (assumptions in the tool's output: matches grow in proportion to the corpus, and a match is not a relevant judgment):

| Aim | Corpus size by random sampling | By targeted additions |
|---|---|---|
| the median query reaches 10 candidate judgments | about 1,200 | |
| 90% of the queries that have a match reach 10 | about 4,700 | |
| every query reaches 10 | not reachable by sampling (6 queries have none) | **at most about 180 extra matching judgments** (the sum of the shortfalls; fewer where queries share them), plus the 25 named older cases |

So the recommendation is a **targeted top-up, not a bigger random sample**: about 1,500 to 2,000 judgments in all, being a base spread over 2015 to 2025 (so IPC-era precedents exist),
plus, for each of the 30 queries, the judgments the search finds for its words (up to 15 more each), plus the overruled and overruling judgments of each doctrine query (the 25 cases
named in `eval/examples/query_grade_criteria.example.md`). Choosing documents by the query's words is corpus building, not labelling; record it. Size is no obstacle: the index is
about 15 KB per judgment, so 2,000 judgments are about 30 MB, loaded in a few seconds.

Grading effort does not grow with the corpus: the pool is the union of the top 20 of each system, at most 30 x 3 x 20 = 1,800 documents per judge before overlap (the pooling tool reports the
real number). That, not the corpus, is what limits how many queries two people can grade.

## Second update, 2026-10-07 (later): M1's and M2's final pushes

Fetched `origin` again. `m1-index` moved by two commits (`0283d5a` "Update M1 indexing and corpus pipeline", `bfc6e7c` "Fix unknown bench sizes in judgment corpus"),
`m2-statute` by one (`fa0269f` "Finalize M2 statute layer, query parser, and matcher"), and `main` now holds M2's work (`38c4240`). `m3-treatment` is unchanged
(`7777a6b`). All were merged here (one conflict: `m1_index/searcher.py`, resolved by taking M1's rewrite; the helpers my earlier connection fixes added to it
were dropped and the tests that used them now test M1's public `search()`).

Each branch was also run **on its own** (a separate checkout of `origin/<branch>`):

| Branch as pushed | `python eval/smoke.py` | Notes |
|---|---|---|
| `m1-index` | 0 failed, 2 skipped (every provider a stub) | the new index file is not in git: run `python -m m1_index.index build` first |
| `m2-statute` | **2 FAIL** | `doc_statutes.jsonl` missing and `statute_map.csv` invalid (see M2-8); its own tests are not collected by its `pytest.ini` and 7 of 8 fail |
| `m3-treatment` | 0 failed, 2 skipped | unchanged |
| **`main`** | **2 FAIL** | M2 set `stubs.statute: false` and merged without `doc_statutes.jsonl` (ignored by git) and with the invalid map, so **the merge gate fails on `main`** |

### M1: what the new push fixed

* **`judgments.jsonl` is contract-valid: 200 of 200** (bench size is `None` where unknown, never 0; dates are ISO).
* **Boolean, phrase and proximity search still work, and malformed queries no longer raise** (`murder AND`, `(` return a result or an empty list). A plain scan of every token of
  every zone (`/api/m1/verify`, tested) agrees with the index for `murder AND intention` (36 judgments), `"common intention"`, `OR`, `AND NOT`.
* **The zone problem is gone**: 0 of 63 matches for `murder` now score 0 (it was 3 of 66).
* **The index is small and rebuildable**: `python -m m1_index.index build` reads `judgments.jsonl` and writes `index.pkl.gz` (2.6 MB, about 18 s here), loaded in about 0.5 s.
  The 74 MB it replaces is no longer read.

### M1: still open

| # | Severity | Finding |
|---|---|---|
| 13 | **High** | `python -m m1_index.ingest build` opens `judgments.jsonl` for writing before it reads anything: with an empty `data/raw` it **rewrites the corpus with zero records**, and `download()` only prints a line, so the corpus still cannot be fetched or rebuilt from the source. M1's own error message ("Run 'make build-index'") pointed at this command; `make build-index` now builds only the index |
| 14 | Medium | `bench_size` for the 27 unknown records is still wrong where the coram line names the judges: `eval.conformance` finds 105 of 122 agree, and 0 of 10 benches of 3 or more are right. M3 works around this by reading the coram line itself |
| 15 | Medium | The old index files (`inverted_index.json`, `tokenized_judgments.jsonl`, 74 MB) are still tracked and no longer read; the tokenised copy still has `29 May 2025` dates; `search.py`, `parser.py`, `text_tokenizer.py` are older copies of the live modules |
| 16 | Medium | `search()` loads `data/processed/index` **relative to the working directory**: from any other folder it raises `FileNotFoundError` (an earlier connection fix had made it repository-relative; the rewrite undid it) |
| 17 | Low | `/s` and `/p` are accepted but mean "within 5 tokens", not same sentence or paragraph; positions restart at 0 in each zone and are merged into one list per document, so phrase and proximity tests compare positions across zones (the checks above agree, but a coincidence across a zone boundary is possible); `filters` honours `year` and `bench_size` only |
| 18 | Info | Listed in the owner's plan but **not in the pushed code**: lnc.ltc cosine scoring (`scoring.py` is still the stub), query optimisation (operands run in the order written), a comparison against a library BM25 (`rank_bm25` is not installed). The Index page marks them instead of describing them |

### M2: what the new push fixed

Extraction is much better: **2,755 references in 199 of 200 judgments** (it was 691 in 172), bare numbers resolve by the offence date (`section 103` dated 2020 is `IPC 103`, dated 2025
is `BNS 103`), lists and the spelled-out forms read (`302/34`, `Sections 302 and 307 of the Indian Penal Code`, `I.P.C.`, `120-B`), seven prose offences are understood
(`murder`, `sedition`, ...), the document table reloads when the file changes, and the map holds 20 offences. `eval.conformance` reads **6 of the 9** forms the Build Guide lists
(it was 2). Measured with a corrected copy of the map (below): `BNS 103 -> IPC 302 (OFF_MURDER) (equivalent)` shows up as the continuity explanation of real results.

### M2: still open

| # | Severity | Finding |
|---|---|---|
| 8 | **Blocker** | `data/statute_map.csv` on `m2-statute` and `main` is **malformed**: the original header and IPC 302 row, then a second header (`offence_id,act1,section1,act2,section2,relation,weight`) and 20 rows in that other layout. `load_map()` stops on line 3, so **every real `continuity()` call for a query that names a statute raises `SchemaError`**, and the Search page shows that error. One header, the contract's columns (`old_act,old_section,new_act,new_section,relation,weight,source,note`) and a `source` per row fix it (a converted copy made all of the following work) |
| 9 | **High** | An act followed by a bare number is not read: `BNS 103`, `IPC 302`, `BNS 3(5)` give no references (the headline query form), and `Section 482 Cr.P.C.` is read as **IPC** 482 (wrong act). Requiring the word `Section` removes the paragraph-number false positives in judgments but should not apply to queries |
| 10 | High | M2's own 8 tests: 7 fail on M2's own code (they describe the old behaviour) and are not collected by M2's `pytest.ini`; `main` fails the shared smoke gate (above) |
| 11 | Medium | `doc_statutes.jsonl` is not committed (`data/processed/*` is ignored), so the switch cannot be flipped for CI or a clean clone; 20 of 20 rows cite no official source; the prose lexicon has 7 entries (`attempt to commit suicide` is not one of them) |

**What to send M1**
> Thank you for the ISO dates, the real `bench_size` values (`None` instead of 0), the zone fix, the safe query parser and the 2.6 MB index with a rebuild command: all four of
> my checks on your side pass now. Open: (1) `ingest build` empties `judgments.jsonl` when `data/raw` is empty (it opens the file for writing first) and its message points
> people to it: guard it and make `download()` real; (2) `bench_size` is still wrong for 3-judge benches (read the coram line in the text); (3) load the index relative to the
> repository, not the working directory; (4) delete the old 74 MB index files and the tokenised copy from git; (5) lnc.ltc, query optimisation and the library BM25
> comparison are on your list but not in the code: implement them or take them off the list before the demo. Your Index page is at `#/index` in the interface.

**What to send M2**
> Extraction is a big step up (2,755 references, 6 of 9 forms). Before it can be used: (1) `data/statute_map.csv` is two files glued together with two headers, so
> `load_map()` stops on line 3 and `continuity()` raises for every query that names a section: one header, the contract columns, a `source` column; (2) `BNS 103` and `IPC 302` on
> their own are not read any more (allow an act followed by a number in queries), and `Section 482 Cr.P.C.` comes out as IPC; (3) your own tests fail on your own code; (4) `main` now
> fails `python eval/smoke.py` because `stubs.statute` is false and `doc_statutes.jsonl` is not in git: flip the switch only in the commit that adds the file (or commit it).

## Where each module stands

| Module | Code | Connected to the others as pushed | After the fixes on `m4-rank` | Still open for the owner |
|---|---|---|---|---|
| **M1** | Boolean, phrase, proximity and BM25 ranking are correct (checked against brute force) | **No**: could not be imported on any other machine, returned hits the contract rejects, rejected every multi-word query | Yes | Data contract (dates, benches), zone splitter, build commands, tests, one parser bug, size |
| **M2** | A minimal hour-0 extractor and parser: works for `IPC 302` and `Section 103 of the BNS` only | Switched itself on while its data file was missing, so the shared smoke gate failed | Switch set back to `true` | Most statute forms, bare-number resolution, offence ids, false positives, the mapping table |
| **M3** | Complete against the Build Guide; runs end to end on real text; his review fixes (cache key, gold merge, same parties, data checks) were merged and re-verified on 2026-10-06 | As first pushed: **no** (crashed on M1's date format, silently skipped exact-key resolution, could not read recent coram lines) | Yes | Evidence choice and the lost marker, running headers, name extraction, then the real work: the hand-labelled gold set, the Gemini run, the F1 table and `doc_health.jsonl` for the corpus |
| **M4** | Done (see section M4) | Yes | n/a | Hand-made queries and grades |

Legend for the tables: **Fixed** means the fix is on `m4-rank` (the smallest edit that makes the connection work, listed in
DECISIONS.md D-026 so the owner can take it or replace it); **Open** means the owner must act.

---

## M1: corpus, index, search

| # | Severity | Finding | State |
|---|---|---|---|
| 1 | Blocker | `search.py` read its index from `Path.home() / "lexshift" / "data/processed/inverted_index.json"`, a clone folder on one machine, and `searcher.py` read different files (`data/processed/index/`). `import m1_index` failed with `FileNotFoundError` anywhere else | **Fixed** (repository-relative paths) |
| 2 | Blocker | `searcher.py` defined its own `Hit` class instead of `common.schema.Hit`, so every result failed the contract check (`hit[0] is Hit, expected common.schema.Hit`) | **Fixed** (imports the shared class; M4 also accepts a foreign class with the same fields) |
| 3 | Blocker | Any query without explicit operators raised `ValueError: Unexpected token`: `BNS 103`, `punishment for murder under section 103 BNS`, `cheating and dishonestly inducing delivery of property`. Only single words and Boolean syntax worked, so the headline demo query failed | **Fixed** (plain text is ranked as a bag of words; `3(5)` and `u/s` are not treated as operators) |
| 4 | High | Importing the package built a 70 MB engine (11 s) and printed five lines to stdout, which corrupts `--json` | **Fixed** (built on first use, no printing) |
| 5 | High | `parse_atom` raises `IndexError`, not `ValueError`, when a query ends after an operator or an open parenthesis (`murder AND`, `(`). Found by randomised input | **Open** (`tests/test_robustness.py`, marked as a known failure; the demo now reports it as one clear line) |
| 6 | High | **Fixed by M1 in `judgments.jsonl` (`287846e`, 2026-10-07); the tokenised copy still has the old dates.** Before: `judgments.jsonl` violated the shared `Judgment` contract in **0 of 200** records: `date` is `02 January 2025`, the contract says `2025-01-02`. M1's own year filter returned 0 hits for `year=2025` and raised `TypeError` for `min_year`; M3 crashed | Code **fixed** (year read from either shape). **Open**: regenerate the tokenised copy with ISO dates too |
| 7 | High | `bench_size` is wrong. 27 records have `0` (invalid; 14 of them print the coram line in the text); records with 3 or more judges are never right (0 of 10: stored as 2 or 0); overall 105 of 122 agree with the printed coram line. M3's bench check needs this: a larger bench can never be recognised | **Open** |
| 8 | Medium | `nltk` was not in `requirements.txt` and the stop-word corpus must be downloaded: a clean clone failed at import with a `LookupError`. Later, with NLTK 3.10, a machine whose AppData folder is redirected (the Windows desktop app's shell) failed at import with a `ValueError` from NLTK's path-security check | **Fixed** (`nltk` declared, clear message, CI downloads it, and the file is read directly when NLTK rejects the path) |
| 9 | Medium | The zone splitter hard-codes paragraph numbers (paragraphs 1-4 facts, 5-6 arguments, 12 and up holding, 7-11 in no zone; a comment says "for this judgment"). Text outside every zone is invisible to BM25: 3 of 66 matches for `murder` score exactly 0. For a long judgment `holding` is nearly the whole text, so zone weights mean little | **Open** |
| 10 | Medium | The corpus cannot be rebuilt from the repo: `ingest.py`, `index.py` and `scoring.py` are still skeletons, so `make download` and `make build-index` print "not implemented". `parser.py` is byte-identical to `query_parser.py`, `text_tokenizer.py` to `tokenizer.py`. 90 MB of derived data (index, tokenised copy) is committed. No tests were committed | **Open** |
| 11 | High | The sample is one year (2025), and it cannot support the evaluation: `python -m eval.feasibility` on the 30 candidate queries finds 3 answerable, 17 thin (3 or fewer judgments hold the words or the section) and 10 empty; section 103 is mentioned in one judgment and section 318 in none. Older citations cannot resolve and no precedent can be overruled inside the corpus, so the treatment signal has nothing to find; the evaluation needs older cases and more of them. Control characters (`\x08`, `\x07`) are in all 200 texts (184 headnotes) | **Open**; M4 now strips them for display |
| 12 | Low | Scale: the index is 0.171 MB of JSON per judgment (measured), so about 5 GB at 30,000 judgments (an extrapolation), loaded into memory twice (`RankedSearchEngine` and `SearchEngine` each load it). The laptop-CPU requirement is at risk at full size | **Open** |

**What to send M1**
> Your Boolean, phrase and proximity logic is correct (I checked it against brute force). Before it could be used I changed
> `search.py` and `searcher.py` (paths, shared `Hit`, plain-text queries, lazy engine, year filter) and the two tokenizers
> (clear NLTK message): please keep those, or replace them with your own fix. What only you can do:
> (1) thank you for the ISO dates in `judgments.jsonl`: regenerate the tokenised copy the same way (it still has `29 May 2025`); (2) fix `bench_size`: read the coram line
> (`[A, B and C, JJ.]`, with `*` marking the author) and never write 0, use null when unknown; every 3+ judge bench is currently
> wrong; (3) make `parse_atom` raise `ValueError` at the end of input; (4) replace the hard-coded paragraph numbers in `zones.py`;
> (5) implement `ingest.py` and `index.py` so `make build-index` rebuilds the corpus, stop committing the index and the tokenised
> copy, and add tests; (6) grow the corpus in volume and in years, with the older judgments (the overruling cases): `python -m eval.feasibility` shows 3 of the 30 candidate queries answerable on the current 200 judgments of 2025. Run `python -m eval.conformance --module m1`.

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

**First pass** (M3's code as first pushed, 203 judgments, stand-in labels): 8,896 mentions; 147 resolved to a corpus judgment (1.7%; 122 of
the 4,761 mentions that carry a Supreme Court reporter citation); 43 tagged appeal history (all unresolved); `health(Koushal)` is 0.1 with
evidence from the 5-judge Navtej bench and no other judgment is lowered.

**Second pass** (M3 pushed review fixes, DECISIONS.md D-024; merged into `m4-rank` and re-run on the same data): 147 of 9,215 mentions resolve
(1.6%), 12 negative labels all pass the bench check, Koushal is still 0.1 and the only lowered judgment, and the new data checks report
bench size, reporter citations and dataset-form ids known for 203 of 203 judgments. `python -m eval.conformance --module m3` has 0 FAIL and 0 WARN.
Four of the nine first-pass findings are fixed and each was reproduced against the new code (findings 1 to 4); one regression was found (10).

| # | Severity | Finding | State |
|---|---|---|---|
| 1 | High | The LLM cache key omitted the few-shot examples: relabelling with examples made zero new API calls and kept the zero-shot label | **Fixed by M3** (the key carries a fingerprint of the examples; verified: after labelling zero-shot, adding one example makes a new call; the pool is frozen in `m3_fewshot_pool.csv`) |
| 2 | High | `gold merge` rewrote `disagreements.csv` from the current sheets, so a missing second sheet wiped typed adjudications and shrank `treatment_gold.csv` silently | **Fixed by M3** (`MergeError` when a sheet is missing, swapped, has foreign windows or blank rows, or the merge would drop an adjudication; atomic writes; `--allow-incomplete`; verified with the second sheet missing) |
| 3 | Medium | `same_parties("Ram Singh v. State of Bihar", "Ram Singh v. State of U.P.")` was `True` | **Fixed by M3** (government side ignored, a distinctive shared token required; verified `False`, and the same dispute with `& Ors.` still `True`) |
| 4 | High | Three silent dependencies on M1: `doc_id` shape, `reporter_citations`, bench sizes | **Fixed** (my `resolver.py` edits are kept, merged with M3's `data_checks` and the report of negatives that did not count) |
| 5 | Medium | Evidence quality on real text: the window kept as evidence is the *headnote's "Case Law Cited" list* ("... Suresh Kumar Koushal ... [2013] 17 SCR 1019 - overruled Naz Foundation ...") rather than the sentence in the reasoning that overrules; ties are broken by confidence, then citing id | **Open** (still true after the re-run: the Koushal evidence is the Shayara Bano headnote list) |
| 6 | Low | Name extraction keeps neighbouring words (`A Constitution Bench in Bachan Singh v. State of Punjab`, `Ram Kishan Vs. State of Haryana the Court`, `Bench v. Bar` read as a case) and margin letters inside names (`Naz B Foundation`) | **Open** |
| 7 | Low | Appeal-history tagging applies to non-Supreme-Court citations whose window contains `set aside`, `reversed` or `quashed`; a High Court decision cited for its holding is tagged. It cannot affect a score but it inflates the statistic | **Open** |
| 8 | Low | The evidence window loses its `[[ ]]` marker in `citations.jsonl` (0 of 9,215 windows keep it), so no consumer can find the treating sentence | **Open** |
| 9 | Low | Memory and ergonomics: `run_health` loads every mention (with its window) into memory; `scores._table()` loads all evidence at the first call; commands print raw tracebacks when inputs are missing; `classify_llm` re-reads the cache per call; the Gemini model alias is not pinned | **Open** |
| 10 | Medium | **New in the merged code.** Running headers that repeat the judgment's own title with the words that follow it (`Mahabir & Ors. v. State of Haryana Code of Criminal Procedure ...`) are no longer self-references: `_same_title` needs a Jaccard of 0.8 over all tokens, so they fall through to appeal history. Re-run: 662 appeal-history tags instead of 43 (374 of them look like the judgment's own title) and 319 more mentions in every count, so the resolution rate and the appeal-history statistic are distorted. No score changes (appeal history is excluded from health and authority) | **Open** |

**What M3 has and has not finished.** The code is complete and tested. What is not done is data work that only M3 can do: the hand-labelled gold
set (`data/treatment_gold.csv` has only its header), the Gemini run, the F1 table (`reports/classifier_f1.md`) and `doc_health.jsonl` /
`citations.jsonl` for the corpus, so `stubs.health` and `stubs.authority` stay `true`. His README says he is waiting for M1's `judgments.jsonl`: it
exists on `m1-index` (200 judgments, all 2025), so extraction can run now. It will find no overruling inside that sample (it needs older cases).

**What to send M3**
> I merged your review fixes (cache key, gold merge, same parties, data checks) and re-ran everything on 203 real judgments; I reproduced each fix
> and they hold, thank you. Three things left in the code: (1) choose the reasoning sentence over a headnote "Case Law Cited" list as evidence and
> keep the `[[ ]]` marker in `citations.jsonl`; (2) running headers with trailing words are no longer self-references (662 appeal-history tags
> instead of 43): use a private-party-token test for `is_self` as well; (3) name extraction keeps neighbouring words. Then the data work: the
> gold set with two labellers, the Gemini run, the F1 table, and `doc_health.jsonl` once M1 ships older judgments with ISO dates and correct
> benches. Run `python -m eval.conformance --module m3` after building.

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

1. M1: ISO dates in the tokenised copy, correct benches (the last blocker for `stubs.search`), a rebuild command, older judgments in the sample, then flip `stubs.search` once `smoke` passes.
2. M2: the extractor fixes, then commit the sample's `doc_statutes.jsonl` and flip `stubs.statute`.
3. M3: evidence choice and the running-header regression, the gold set and the Gemini run, then build `doc_health.jsonl` and flip `stubs.health` and `stubs.authority`.
4. M4: **done** (2026-10-07): `rank()`, the evaluation tools, the interface, the 30 queries (adopted by the owner), and `m4-rank` on `main`. **Left, in this order, all needing people or the other modules:** (a) M1's corpus grows (older judgments, the cases named in `eval/examples/query_grade_criteria.example.md`); (b) all four modules real (`python -m eval.submission_check` shows the switches); (c) `python -m eval.pool --round round1`, two judges in the Judging screen, `python -m eval.make_qrels --round round1`, the hand-verified `eval/gold_overrulings.csv`; (d) `python -m eval.run_ablation --tune`, then `--split test`; (e) the report and the video. Nothing in (c) and (d) can be generated: grades and the gold list are written by people.
5. Everyone: `python -m eval.conformance` and `python eval/smoke.py` must be clean before merging to `main`.
