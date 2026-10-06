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
| 6 | High | `judgments.jsonl` violates the shared `Judgment` contract in **0 of 200** records: `date` is `02 January 2025`, the contract says `2025-01-02`. M1's own year filter returned 0 hits for `year=2025` and raised `TypeError` for `min_year`; M3 crashed | Code **fixed** (year read from either shape). **Open**: the data must be regenerated with ISO dates, in `judgments.jsonl` and the tokenised copy |
| 7 | High | `bench_size` is wrong. 27 records have `0` (invalid; 14 of them print the coram line in the text); records with 3 or more judges are never right (0 of 10: stored as 2 or 0); overall 105 of 122 agree with the printed coram line. M3's bench check needs this: a larger bench can never be recognised | **Open** |
| 8 | Medium | `nltk` was not in `requirements.txt` and the stop-word corpus must be downloaded: a clean clone failed at import with a `LookupError`. Later, with NLTK 3.10, a machine whose AppData folder is redirected (the Windows desktop app's shell) failed at import with a `ValueError` from NLTK's path-security check | **Fixed** (`nltk` declared, clear message, CI downloads it, and the file is read directly when NLTK rejects the path) |
| 9 | Medium | The zone splitter hard-codes paragraph numbers (paragraphs 1-4 facts, 5-6 arguments, 12 and up holding, 7-11 in no zone; a comment says "for this judgment"). Text outside every zone is invisible to BM25: 3 of 66 matches for `murder` score exactly 0. For a long judgment `holding` is nearly the whole text, so zone weights mean little | **Open** |
| 10 | Medium | The corpus cannot be rebuilt from the repo: `ingest.py`, `index.py` and `scoring.py` are still skeletons, so `make download` and `make build-index` print "not implemented". `parser.py` is byte-identical to `query_parser.py`, `text_tokenizer.py` to `tokenizer.py`. 90 MB of derived data (index, tokenised copy) is committed. No tests were committed | **Open** |
| 11 | High | The sample is one year (2025), and it cannot support the evaluation: `python -m eval.feasibility` on the 25 example queries finds 2 answerable, 16 thin (3 or fewer judgments hold the words or the section) and 7 empty; section 103 is mentioned in one judgment and section 318 in none. Older citations cannot resolve and no precedent can be overruled inside the corpus, so the treatment signal has nothing to find; the evaluation needs older cases and more of them. Control characters (`\x08`, `\x07`) are in all 200 texts (184 headnotes) | **Open**; M4 now strips them for display |
| 12 | Low | Scale: the index is 0.171 MB of JSON per judgment (measured), so about 5 GB at 30,000 judgments (an extrapolation), loaded into memory twice (`RankedSearchEngine` and `SearchEngine` each load it). The laptop-CPU requirement is at risk at full size | **Open** |

**What to send M1**
> Your Boolean, phrase and proximity logic is correct (I checked it against brute force). Before it could be used I changed
> `search.py` and `searcher.py` (paths, shared `Hit`, plain-text queries, lazy engine, year filter) and the two tokenizers
> (clear NLTK message): please keep those, or replace them with your own fix. What only you can do:
> (1) regenerate `judgments.jsonl` and the tokenised copy with ISO dates (`2025-01-02`); (2) fix `bench_size`: read the coram line
> (`[A, B and C, JJ.]`, with `*` marking the author) and never write 0, use null when unknown; every 3+ judge bench is currently
> wrong; (3) make `parse_atom` raise `ValueError` at the end of input; (4) replace the hard-coded paragraph numbers in `zones.py`;
> (5) implement `ingest.py` and `index.py` so `make build-index` rebuilds the corpus, stop committing the index and the tokenised
> copy, and add tests; (6) grow the corpus in volume and in years, with the older judgments (the overruling cases): `python -m eval.feasibility` shows 2 of the 25 example queries answerable on the current 200 judgments of 2025. Run `python -m eval.conformance --module m1`.

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

1. M1: ISO dates, correct benches, a rebuild command, older judgments in the sample, then flip `stubs.search` once `smoke` passes.
2. M2: the extractor fixes, then commit the sample's `doc_statutes.jsonl` and flip `stubs.statute`.
3. M3: evidence choice and the running-header regression, the gold set and the Gemini run, then build `doc_health.jsonl` and flip `stubs.health` and `stubs.authority`.
4. M4: with real modules on, write the queries, pool, grade, tune on dev, report on test.
5. Everyone: `python -m eval.conformance` and `python eval/smoke.py` must be clean before merging to `main`.
