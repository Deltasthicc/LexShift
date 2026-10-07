# Decision log

Every non-obvious decision, and every assumption verified or falsified, with the date and the evidence. Append; do not
rewrite history (mark a decision superseded and add the new one). IDs: **D-nnn** decisions, **OQ-n** open questions.

## Decisions

### D-001 (2026-10-06) The Build Guide wins over the Project Brief on layout, contracts and formulas
The Team Build Guide (6 October 2026) and `PROJECT_BRIEF.md` overlap and disagree in places. The Guide is later, more
specific, and says its contracts are fixed in hour 0, so it wins on the points below. The brief still governs the goal, the
rubric, the constraints, the evaluation ideas and the risks.

| Topic | Brief | Guide (adopted) |
|---|---|---|
| Layout | `src/{ingest,index,...}`, `artifacts/`, `data/concordance/ipc_bns.csv` | top-level `common/ m1_index/ m2_statute/ m3_treatment/ m4_rank/ eval/ app/ stubs/`, `data/statute_map.csv` |
| Ownership | workstreams A to D | M1 to M4 (A=M1, B=M2, C=M3, D=M4) |
| Relation types | EQUIVALENT, MODIFIED, SPLIT_MERGED, REPEALED, NEW | equivalent, modified_punishment, modified_elements, split, merged, omitted, new |
| Final score | 3 terms: relevance, continuity, health (health folds in authority) | 4 terms: rel, cont, health, auth (authority is a separate PageRank signal) |
| Health | `authority * (1 - negative)`, weighted over all citers | strongest valid negative: overruled 0.1, doubted/criticised 0.6, otherwise 1.0 |
| Baselines | B0 to B4 plus Full | B0, B1 (+continuity), full (+health+auth) for the MVP |
| Judged set | 40 to 50 queries | 30 queries: 10 dev, 20 test |
| Treatment classifier | fine-tune a small encoder on the GPU | LLM few-shot (cached) plus tf-idf/logistic baseline: see D-008 |

The start-prompt's "Phase 0, stop and wait" flow and its `src/` layout are superseded by this log and the new layout.

### D-002 (2026-10-06) Project and repository naming, branches, privacy
The project is **LexShift**. The GitHub repository `Deltasthicc/IRHackathon` was renamed to **`Deltasthicc/LexShift`**
(it was empty; GitHub redirects the old URL). Branches follow Guide 4.4: `m1-index`, `m2-statute`, `m3-treatment`, `m4-rank`,
plus `main`. By request, the repository names no individuals: branches and docs identify modules, not people, and the
copy of the brief in the repo has the team names removed.

### D-003 (2026-10-06) Explicit stub switches, never an automatic fallback
Cross-module functions are served by the real module or a fixed-value stub chosen by `stubs:` in `common/config.yaml`
(`LEXSHIFT_STUBS` overrides per run). A missing or failing real function is an error, not a silent switch to a stub,
because a silent fallback could put a fake number into the demo or the evaluation, and the rubric gives zero for a faked
demo. Stub output is flagged on every path: `Result.stubbed`, the CLI banner, and `eval/run_ablation.py` refuses to write
results unless `--allow-stubs` (then names them `stub_*`, git-ignored).

### D-004 (2026-10-06) Contract fields the Guide did not specify (v0.1 proposals)
Proposed in `common/schema.py`; any owner may amend before their module merges: `QueryStatutes` fields (`query`,
`offence_date`, `governing_act`, `refs`, `notes`, derived `offence_ids`); `qrels.tsv` is tab-separated with a header row;
`eval/gold_overrulings.csv` columns; optional derived `data/processed/doc_meta.jsonl`; `Result` carries four additive
fields (`evidence`, `raw`, `contributions`, `stubbed`) beyond the Guide's seven, none replacing a contract field;
`Judgment.bench_size` may be `None` when it cannot be recovered; unknown acts are recorded as `UNKNOWN`.
Evidence for the Guide's own fields: Guide section 4.2 and 4.3.

### D-005 (2026-10-06) Module file names chosen to avoid shadowing
`m1_index/tokenizer.py` (not `tokenize.py`, which would shadow the standard-library `tokenize`), `m1_index/searcher.py`,
`m2_statute/matcher.py` and `m3_treatment/scores.py` so that no module shares a name with the function its package
re-exports (`from pkg import search` would otherwise rebind the submodule attribute). The classifier, bench check and LLM
baseline live together in `m3_treatment/classifier.py`.

### D-006 (2026-10-06) Normalisation is configured per signal
The Guide says "min-max normalize" in M4's block. Min-max over the top-100 candidates is applied to `rel` (BM25 is unbounded
and query dependent) and `auth` (PageRank mass is only meaningful relative to the candidates). `cont` and `health` are
already calibrated weights in [0, 1] (equivalent 1.0, overruled 0.1 and so on); min-max would stretch a candidate set whose
health only varies between 0.6 and 1.0 to 0 and 1, making the penalty depend on who else was retrieved. They use `identity`
(clip to [0, 1]). The choice is in `ranking.normalize` in `common/config.yaml` and can be flipped; an ablation of it on DEV is
a candidate next step. **Interpretation of the Guide: confirm with the team.**

### D-007 (2026-10-06) Metric definitions
* Relevant means grade >= 1 (`evaluation.relevant_threshold`) for P@k, Recall@k and MAP; nDCG uses graded gains
  (`2**grade - 1`). Grade 0 already folds in "overruled on the queried point", so returning such a case costs precision.
* Evaluation depth is 20 (`evaluation.depth`), equal to the pooling depth: judging was done on the union of every system's
  top-20, so going deeper would count unjudged documents as non-relevant. MAP is computed over that depth.
* Documents without a judgement for a query count as grade 0 (the pooling assumption); `judged@k` is reported so holes in the
  pool are visible.
* Recall@k is relative to the judged relevant documents in the pool, not to the whole corpus. Queries with no relevant
  judged document are excluded from recall and MAP (and counted).
* `harmful@k` is the fraction of the top-k that is in `eval/gold_overrulings.csv`, a hand-verified list that is **not**
  derived from the system's own health signal, to avoid circularity. Guide: "harmful@10 (overruled cases in the top 10)".

### D-008 (2026-10-06) Treatment classifier: LLM few-shot, run offline and cached
The Guide specifies LLM few-shot on the citation window (main) plus tf-idf and logistic regression (baseline); the brief
proposed fine-tuning an encoder on the GPU. We follow the Guide. This is consistent with "no live LLM": the LLM runs offline,
every output is cached, and the demo reads frozen labels. A fine-tuned encoder stays a possible extra if time remains. The
model, prompts and cached outputs must be declared in `AI_USE_LOG.md`. **M3 confirms the final choice.**

### D-009 (2026-10-06) Python version and tooling
Target is Python 3.11 (Guide). Developed and tested on Python 3.11.4 in a virtualenv. Dependencies are limited to what the
code imports (`pyyaml`, `pytest`); planned libraries are listed, commented out, in `requirements.txt` per owner. `pytest`
writes temporary files under `.pytest_tmp/` inside the repo because the system temp directory was not writable on one
development machine.

### D-010 (2026-10-06) Initial weights are placeholders
`ranking.configs` in `common/config.yaml` holds untuned starting weights (`b1`: rel 0.7, cont 0.3; `full`: rel 0.5, cont 0.2,
health 0.2, auth 0.1). They are weights to be tuned on DEV only, not findings. Each config's weights are renormalised to sum
to 1 at load time so `final` stays in [0, 1].

### D-011 (2026-10-06) Dataset facts verified so far
Source: the AWS Open Data registry page, read on 2026-10-06. **Verified:** bucket `indian-supreme-court-judgments`, region
`ap-south-1`, `aws s3 ls --no-sign-request s3://indian-supreme-court-judgments/`, no AWS account, CC-BY-4.0, bi-monthly
updates, judgments from 1950 to 2025, raw JSON metadata, parquet metadata and zip files, English and regional languages.
**Not stated on the page and therefore still unverified (M1 to check on a sample, then update this entry):** folder layout,
parquet schema and field list, size, judgment count, whether judgments are PDFs or text, availability of citation metadata,
how often BNS/BNSS appear, which citation formats occur, how often "overruled" appears in non-precedent senses.

**M3 addendum (2026-10-06, from the bucket itself).** I listed the bucket over HTTPS and downloaded the 2013 and 2018
parquet metadata and 9 English PDFs (Navtej Singh Johar, Joseph Shine, Suresh Kumar Koushal and 6 routine 2018 judgments).
Findings:
* Layout: `metadata/{json,parquet,tar}/year=YYYY/` and `data/{pdf,tar}/year=YYYY/english/<path>_EN.pdf`.
* Parquet fields: `title, petitioner, respondent, description, judge, author_judge, citation, case_id, cnr, decision_date,
  disposal_nature, court, available_languages, raw_html, path, nc_display, scraped_at, year`.
* `citation` is the SCR citation (`[2018] 10 S.C.R. 1005`). `case_id` is the neutral citation (`2018 INSC 696`). `path`
  is `<SCR year>_<volume>_<first page>_<last page>`: all 854 rows of 2013 match that pattern.
* `judge` can list only the author. The "Bench : N Judges" text in `raw_html` was missing for every 2013 row.
* The judgments are SCR-formatted PDFs. They contain margin letters A to H, the running heads "SUPREME COURT REPORTS"
  and "[2018] 13 S.C.R.", a coram line ("[MADAN B. LOKUR, S. ABDUL NAZEER AND DEEPAK GUPTA, JJ.]"), a headnote with a
  case-law list ("... (2014) 1 SCC 1 : [2013] 17 SCR 116 – overruled"), and footnote citations.
* Citation formats seen: SCC, SCR (including Suppl.), SCC OnLine, AIR (Supreme Court and High Courts), SCALE, Cri LJ.
  There was no INSC citation in the 2018 texts.

### D-012 (2026-10-06) How weights are tuned
`python -m eval.run_ablation --tune` grid-searches the weight simplex of each multi-signal config (b1, full) on the DEV
split only, objective mean nDCG@10. Grid step 0.1 (about ten dev queries would only fit noise on a finer grid); relevance
keeps a floor weight of 0.3 (`--min-rel`), because the other signals re-rank BM25 candidates rather than replace relevance,
which is a design choice and not a finding; ties go to the vector nearest the starting weights, then lexicographic order,
so the result is deterministic. The dev-only rule is enforced in code (`eval.tuning.TuningError` on any non-dev query), the
result is saved to `common/weights_tuned.yaml` and reported as "tuned on dev", a dev table produced right after tuning is
labelled optimistic, and a stub run saves nothing.

### D-013 (2026-10-06) rank() is collect() plus fuse()
`m4_rank.rank.collect` gathers each query's raw signals once and `fuse_collected` ranks them for any weight vector, so the
ablation and the tuning grid never repeat provider calls (a grid of 120 vectors would otherwise cost 120 search/continuity/
health/authority passes per query). Only the signals a config weights are collected, so b0 never touches M2 or M3.
Provider output is checked against `common/contracts.py` at runtime and a violation raises `ContractViolation`, because a
malformed signal must fail loudly instead of quietly reordering a ranking. Evidence is shown strongest-first as M3 returns it,
truncated to `ranking.max_evidence`; the explanation still counts the full list.

### D-014 (2026-10-06) How the qrels are built (pooling and judging tools)
`eval/pool.py` pools the top-20 (the evaluation depth) of b0, b1 and full into `eval/judging/<round>/`. The judge sheet is
**blind**: documents are shuffled per query with a seeded shuffle and carry no scores, ranks, system names, continuity or health
values, because those come from the system under test and would make the grades circular; which system returned what is kept in
a separate `provenance.csv`. Pooling is **incremental**: documents already in `qrels.tsv` are not asked about again, so a second
round after tuning only adds what is new. A round directory is never overwritten (`--force` regenerates only the template,
provenance and summary, and is refused once any judge file exists, because replacing the template would orphan the grades),
and pooling from stub providers is refused. `eval/make_qrels.py` requires each
judge file to contain exactly the template's rows, reports percent agreement and Cohen's kappa (plain and quadratic-weighted,
because grades are ordinal), requires every disagreement to be adjudicated by re-reading (the `adjudicated` column), refuses to
change a grade already in `qrels.tsv`, and writes `qrels.tsv` (atomically) only when the round is complete
(`--allow-incomplete` writes the settled rows). While a judge file has problems it leaves `disagreements.csv` untouched, so a
damaged file can never wipe adjudications already typed in. No tool assigns a grade. The Guide's wording is "pooled top-20 of
all configs, two judges"; the blind sheet, the incremental rounds and the adjudication file are our additions.

### D-015 (2026-10-06) Review of the M4 branch: what was found and fixed
A structured review of `main..m4-rank` found 21 issues; all real ones were fixed and covered by tests. The substantive ones:
`make_qrels` could wipe typed adjudications when a judge file was damaged; `pool --force` could orphan graded sheets; the CLI
parsed other modules' explanation text back apart and could crash on a ` | ` or a newline in it (notes are now sanitised and the
renderer no longer trusts them); `harmful@10` (lower is better) and `judged@10` (measures the pool) were selectable as tuning
objectives, so tuning could have optimised the wrong direction (now restricted to `eval.metrics.OBJECTIVES`: nDCG@10, MAP, P@5,
P@10, R@10); an unsatisfiable relevance floor, `--step 0`, an empty `--configs` and `--bootstrap 0` crashed with an
`IndexError` or `ZeroDivisionError` instead of a usage message; a config without a relevance weight was accepted although
candidates always come from `search()` (stub flags would have missed it); short or BOM-prefixed spreadsheet rows crashed the
loaders; judge sheets now neutralise spreadsheet formulas in court text and round names cannot be paths. Tuning no longer
rebuilds Results and explanations per grid point (`m4_rank.fusion.rank_ids`, columns normalised once), and `--tune` no longer
collects the dev queries twice. The `ranking:` and `evaluation:` config sections are validated with clear messages
(`m4_rank.weights.validate_ranking_config`).

**Boundary with the other modules.** The branch initially edited `common/io.py` and `paths:` in `common/config.yaml`, which
CLAUDE.md says to agree with the owners first. Both were reverted or moved: the table helpers (byte-order mark, short rows,
atomic write) live in `eval/loaders.py`, and the judging folder is `evaluation.judging_dir`, a key in the M4-owned section. The
only change under `common/` on this branch is that one key. Found but not changed, because it is outside M4's folder: an unused
import in `common/contracts.py`.

### D-016 (2026-10-06) M3 treatment classifier: Gemini few-shot, offline and cached (closes D-008)
The main classifier is Google Gemini through `google-genai`, model `m3_treatment.llm.model` (default `gemini-2.5-flash`),
temperature 0, structured JSON output, 10 windows per request, prompt version `v1` (`m3_treatment/classifier.py`). Every
answer is cached in `data/cache/m3_llm_labels.jsonl`, keyed by sha256(prompt version, model, marked window). Only
`python -m m3_treatment.pipeline label-llm` calls the API (it needs `GEMINI_API_KEY`). `classify_llm()` and the demo path
read frozen files only. By default the LLM labels only mentions resolved to a corpus judgment (`llm.scope: resolved`),
because the others cannot move any score; the gold windows are always labelled. Few-shot examples come only from a
held-out few-shot pool of the gold set (2 per class, chosen by hash), which is excluded from the F1 table. The baseline is
tf-idf (word 1-2 grams over the whole window, plus a second tf-idf over 150 characters either side of the target) with
class-balanced logistic regression, scored by stratified 5-fold cross-validation on the same evaluation windows.

### D-017 (2026-10-06) citations.jsonl has one record per mention; unclassified mentions are explicit
Each place a judgment refers to an earlier case is one record, so every window stays available as evidence. PageRank merges
parallel edges by taking the largest weight, so a case mentioned 20 times does not vote 20 times. Self-references (running
headers, the judgment's own citation) are dropped. Mentions outside the LLM scope (unresolved, or appeal history) get
`label = neutral`, `confidence = 0.0`. Confidence 0 means "not classified": such a record has no corpus target, or is a
reversal on appeal, so it can never change health or authority. Windows given to a classifier or a labeller mark the
cited case with `[[ ]]`. citations.jsonl now keeps the markers too (D-033).

### D-018 (2026-10-06) Short-form mentions are linked to the case they refer to
Indian judgments usually treat a case through a short form: in Navtej Johar the overruling sentence is
"Suresh Kumar Koushal (supra) needs to be, and is hereby, overruled", and later "The decision in Koushal stands overruled".
The extractor links `supra` mentions to the latest earlier named mention containing their tokens, preferring one that
carries a reporter citation. It links `alias` mentions (the petitioner side without "& Ors.", or its last word if that word
has five or more letters and is not a common name such as Singh or Kumar) only to cases named earlier in the same judgment,
and only in Title Case or UPPER CASE. Measured on Navtej Johar: all 26 "Koushal (supra)" mentions link to the cited full
mention. Extraction time fell from 10.7s to 0.25s on that 850k-character judgment once alias search used a word-position
index.

### D-019 (2026-10-06) Resolver: exact keys first, page ranges only with an agreeing name, two-gate Jaccard
Order: (1) an exact normalised reporter key from `reporter_citations` or the SCR key in the doc_id; (2) the SCR page range
from the doc_id, accepted only when the mention names the case and the names agree (Jaccard >= 0.3); (3) party-name Jaccard
with the year within +/- 1. Evidence for (2): the SCR prints Koushal as both `[2013] 17 SCR 116` (correct, per the metadata)
and `[2013] 17 SCR 1019`, and page 1019 falls inside an unrelated judgment's range. Evidence for the two gates in (3): with
only the stop-listed tokens, "Sushil Kumar v. State of Punjab" matched "Sushil Sharma v. State of NCT of Delhi". The score
is now the Jaccard over all party tokens, and the stop-listed ("informative") tokens must also agree. The stop list is
corpus driven: title tokens in more than 2% of titles, once they occur in at least 5. Near ties stay unresolved.

### D-020 (2026-10-06) Bench size falls back to the coram line; an unknown bench never validates a negative
The bench check is the Guide's rule: citing bench >= cited bench. It uses `bench_size` from M1, else `len(judges)` when more
than one judge is listed, else the number of judges on the coram line in the first 6,000 characters of the text ("CJI" is a
title, not another judge). Otherwise the bench is unknown, and a negative with an unknown bench on either side does not lower
health (it is still stored). A single name is not trusted, because the dataset's `judge` field can be the author alone.
Checked on the 9 downloaded judgments: Navtej 5, Joseph Shine 5, Koushal 2, M.A. Antony 3. **Request to M1:** fill
`bench_size` from the coram line. Without bench sizes no overruling could pass the check.

### D-021 (2026-10-06) M3 cleans PDF furniture before extraction; offsets refer to the cleaned text
`m3_treatment.text.clean_text` drops margin letters, bare page numbers and the running heads, then joins wrapped lines.
Left in, the running head "[2018] 11 S.C.R." glued onto the next paragraph number reads as a citation
"[2018] 11 S.C.R. 62", which page-range resolution then mapped to a neighbouring judgment. This does not change M1's
`text`. The sentence splitter treats "Ors." as never ending a sentence (merging a rare true boundary only enlarges a window).

### D-022 (2026-10-06) health and authority details
* health(d) = the strongest valid negative with confidence >= `m3_treatment.min_confidence` (0.5): overruled 0.1, doubted 0.6,
  otherwise 1.0 (Guide).
* Evidence: one item per (citing judgment, label), with valid negatives first and then up to the cap (`max_evidence` 5)
  positive treatments from the largest benches. Extra keys `confidence`, `citing_bench` and, on negatives, `offence_ids`
  sit next to the contract's `citing_doc, label, sentence`.
* authority(d) = log(1 + N * PageRank(d) * bench_weight(d)) / max. PageRank is our own power iteration over `followed` and
  `neutral` edges weighted by confidence, with damping 0.85, uniform redistribution of dangling mass, and parallel edges
  merged by max. bench_weight = log(1 + bench) / log(1 + 7), capped at 1. An unknown bench uses 2 for this weight only.
  Recency is not used anywhere (newer is not stronger). Known limitation: PageRank favours older judgments, which have
  had more time to be cited.
* Labelling rule: a window that reports what another court did to the target ("in X this Court overruled [[Y]]") is
  `neutral`. That treatment is captured from X's own text when X is in the corpus.

### D-023 (2026-10-06) Point-level health (stretch) uses the citing judgment's offences
When `doc_statutes.jsonl` (M2) exists, each negative evidence item carries the offence ids of the citing judgment.
`health(d, offence_ids)` then applies a negative only if those ids overlap the query's. An item with no known ids always
applies. This is coarse: it uses the offences of the whole overruling judgment, not of the overruled point.

### D-024 (2026-10-06) Review fixes in M3
* **LLM cache and few-shot prompts.** The cache key now includes a fingerprint of the exact few-shot examples (or
  `zero-shot`). Before, a label made before the gold set existed was reused under the few-shot prompt, and the F1 table
  would have called it few-shot. The few-shot pool is drawn once and frozen in `data/labelling/m3_fewshot_pool.csv`, so
  adding gold labels later does not change the prompt. The F1 report states the prompt actually used (zero-shot or N-shot).
* **gold merge safety.** `merge` now refuses, writing nothing, when a sheet is missing, the sheets are swapped, the second
  sheet has windows the first does not, a window is still blank (`--allow-incomplete` merges only the labelled rows), or
  the merge would drop an adjudication already typed into `disagreements.csv`. Files are replaced atomically.
* **Appeal history.** "Same parties" now compares only the non-government side ("State of Haryana" names the prosecutor,
  not the dispute) and needs at least one shared distinctive token (not a common name such as Ram or Singh, not in the
  corpus stop list). Before, "Ram Singh v. State of Haryana" and "Ram Singh v. State of U.P." counted as one dispute,
  so a real overruling between them would have been dropped. Running headers are still recognised as self-references
  by an exact-title test.
* **Dependencies on M1.** `extract` reports how many judgments have a known bench, a parseable `reporter_citations` entry
  and a dataset-form `doc_id`, in `reports/resolution.md` and on stderr. With no known bench at all it exits non-zero and
  `citations build` stops, because then no negative treatment could lower any score. `health` reports negatives that
  did not count and why (unknown bench or smaller citing bench).

### D-025 (2026-10-06) M3 merged into m4-rank and checked against M4
M3 arrived through a pull request merged into `main`; `main` was merged into `m4-rank`. The only conflicts were append-only
(`DECISIONS.md`, `requirements.txt`) and were resolved by keeping both sides. M3 edited only its own `m3_treatment:` section of
`common/config.yaml`. Findings are in [docs/INTEGRATION_REVIEW.md](docs/INTEGRATION_REVIEW.md); they are for M3 to act on and
M4 did not change M3's code. What M4 changed, because the integration test showed it:
* `m4_rank.rank.ArtefactError`: a provider's `KeyError` or `FileNotFoundError` (an id missing from `doc_health.jsonl`, a build step
  not run) is now one clear error naming the call, handled by the CLI, `eval.pool` and `eval.run_ablation`, instead of a traceback.
  The call site is always named and the original exception is chained, so a genuine bug in a module is still traceable.
* The demo no longer truncates evidence at 220 characters. M3's evidence is a three-sentence window and the sentence that does the
  overruling is the middle one; with the cut the overruled case's own evidence ended before it. Evidence is shown in full, wrapped,
  with M3's `confidence` and `citing_bench` when present; `--evidence-chars N` shortens it on request. The first version of the test
  passed for the wrong reason (another item quoted the same words) and now checks inside the overruled item.
* Evidence items may carry optional extra keys; M3 adds `confidence`, `citing_bench`, and `offence_ids` on negatives
  (docs/CONTRACTS.md).
`stubs.health` and `stubs.authority` stay `true`: `doc_health.jsonl` does not exist until M1's corpus does.

### D-026 (2026-10-06) M1 and M2 merged; the four modules connected and checked together
`m1-index` and `m2-statute` were merged into `m4-rank` (no conflicts). All four modules were then run end to end on real judgments
(M1's 200 plus three downloaded from the public bucket) and attacked with random and hostile input. Every finding, with the message to send
each owner, is in [docs/INTEGRATION_REVIEW.md](docs/INTEGRATION_REVIEW.md); `python -m eval.conformance` reproduces the data and API checks.

**Edits made in other owners' modules**, because the connection was broken without them and the task was to make it work. Each is the
smallest edit that fixes a verified failure; owners may take them or replace them:
* M1 `search.py`: index and corpus paths relative to the repository (they pointed at one person's home folder) and the same files `searcher.py`
  reads; no progress printing. `searcher.py`: `Hit` imported from `common.schema` instead of redefined; the engine is built on the first
  call instead of at import; a query with no operators is plain text (candidates are the documents containing any stemmed term, then BM25),
  so `BNS 103` and `3(5)` and `u/s` work; the year is read from `02 January 2025`-style dates and a missing year satisfies no year bound.
  `tokenizer.py` and `text_tokenizer.py`: a clear message when the NLTK stop words are missing, and the stop-word file is read directly when
  NLTK 3.9+'s path-security check rejects it (Windows packaged apps redirect AppData, so the same file resolves to another folder and the whole
  search failed to import; found when the interface was started from the desktop app's shell). `requirements.txt`: `nltk`.
* M3 `resolver.py`: the dataset's language suffix is allowed in `doc_id` (`2025_1_1_11_EN`), the year is read from any date shape (`year_of`),
  and the coram reader accepts the recent mixed-case format with an author asterisk.
* M2: no code changed. `stubs.statute` was set back to `true` (its file `doc_statutes.jsonl` is not committed, so smoke failed);
  `pytest.ini` now collects `m2_statute/tests`.
* Not changed anywhere: M1's data files, which break the `Judgment` contract (dates, benches); only M1 can regenerate them.

**M4 changes** (all tested): `ArtefactError` for missing data and unloadable modules, with a module's loading output sent to stderr;
`rank()` accepts a foreign `Hit` class; **when search is a stub every signal is flagged as stub**, because the other modules were only asked
about placeholder ids; control characters are stripped from evidence and judge sheets; an unexpected module error is one clear line
(`--debug` for the traceback); the NLTK stop words are downloaded in CI.

Known failures are marked, not hidden: `tests/test_robustness.py` has two `xfail` tests (M2's quadratic `extract_refs`, M1's `IndexError`
on `murder AND`); each turns into a pass when its owner fixes it.

### D-027 (2026-10-06) The web interface, the judging workbench and the feasibility counter
(Numbering note: M3's own D-024 reached `main` first, so the two integration entries above are D-025 and D-026.)

* **Server.** Python standard library only (`http.server`), no framework, no build step, no new dependency: the live path stays offline
  and the interface runs wherever the tests do. It binds to the loopback address, answers only to a loopback `Host` header (a web page
  you happen to have open cannot reach it), accepts writes only as JSON from its own origin, caps the body at 64 KB, and serves nothing
  outside `app/web/static`. The page's Content-Security-Policy allows no inline script or style and no other origin; the tests assert that
  the page's own files contain no remote URL, no inline code and no `innerHTML` (the vendored libraries are checked by hash instead).
* **No logic in the interface.** `app/service.py` calls `m4_rank` (`collect` once, then `fuse_collected` for B0, B1 and full), so the
  screen cannot disagree with `rank()`, and one request serves all three configurations: switching is instant. A stub signal is reported
  as a stub on every result, and when search is a stub every signal is (D-026).
* **Wording and honesty.** The page never says "dead law" or "bad law" (a test scans the files), carries the not-legal-advice note, shows
  evidence in full with its confidence, and says "stub run" on any `stub_*` result file. Dates are shown as stored (M1's `02 January 2025`
  is not ISO yet).
* **Design brief.** The visual direction followed the `gpt-taste` skill (editorial split hero, 2-line headline, a gapless 4 by 2 bento,
  image scale-and-fade and card stacking, evidence carousel, marquee, inline pill in the headline, Outfit). Where the skill conflicts with the
  project rules the rules won: no stock images (they are network fetches), so the artwork is generated SVG and CSS; and no invented
  testimonials or partners, so the carousel shows the treatment evidence of the current results and the marquee shows real judgment titles
  from the index.
* **Vendored GSAP and Outfit.** At the owner's request GSAP 3.15.0 (with ScrollTrigger) and the Outfit variable font 5.3.0 were downloaded
  once with `npm pack` from their official packages and copied unmodified into `app/web/static/vendor` and `app/web/static/fonts`. The run
  time still fetches nothing: the files are served by the local server, the CSP allows `script-src` and `font-src` from the same origin only,
  and a test checks each file against the SHA-256 recorded in `app/web/static/vendor/README.md`, that the GSAP files contain no network call,
  and that both libraries are served. GSAP's "no charge" licence is stated in the file headers (https://gsap.com/standard-license); Outfit is
  SIL OFL 1.1. The motion is created inside `gsap.matchMedia()`, so visitors who prefer reduced motion get a static page, and if the vendored
  files are missing the page still works unanimated. CSS `scroll-behavior: smooth` was removed because it fights ScrollTrigger; anchors scroll
  smoothly from script instead.
* **Judging workbench.** It writes only `judge1.csv` or `judge2.csv` in a round's folder, through the same atomic table writer as the
  tools, refuses to touch a file that no longer matches the template, neutralises spreadsheet formulas in notes, and reads only
  `sheet_template.csv`: never `provenance.csv`, scores, ranks or the other judge's file. It does not compute or show agreement (that would
  let one judge see the other's grades) and it has no suggestion feature; `make_qrels` stays the only place agreement is reported.
* **Feasibility counter (`python -m eval.feasibility`).** Judging queries are chosen before looking at results, but a query with nothing to
  find in the corpus is wasted. The tool counts, from the real search and an independent regular expression over the text, how many
  judgments hold each query's words and section numbers. It is a coverage check, never a grade, and refuses a stub search. **Measured
  finding:** on M1's 200-judgment sample (all 2025) 2 of the 25 example queries are answerable, 16 are thin and 7 empty, so the corpus must
  grow in volume and years before the query list is final (request to M1, in docs/INTEGRATION_REVIEW.md).

### D-028 (2026-10-07) Smoother motion, no black panels, and the second design pass
The owner reported abrupt cut-offs, black areas and motion that did not flow. Causes found in the code, and what changed:
* **Black panels.** Stacked cards and fading images were dimmed with `brightness(...)`, which turns a card black. No brightness filter is used
  any more (a test fails if one returns); cards and images use scale, offset and a mild opacity.
* **Hard edges.** The hero clipped its own gradients and art (`overflow: clip`) and every section drew its own backdrop. There is now one fixed ambient
  background behind the whole page that drifts with the scroll, sections have none, dividers are feathered hairlines, and the hero art is masked, not clipped.
* **Flash then gap on load.** The hero painted, the script hid it and animated it back in. It is now hidden from the first paint by CSS
  (`html[data-intro="pending"]`), the script clears the flag as it starts the intro, and a CSS animation shows everything after 4.5 s if the script never
  runs; a second failsafe completes the timeline if frames are not being produced.
* **Steppy scroll motion.** Scrubbed tweens followed the wheel 1:1. Every scroll-linked tween now has smoothing (`scrub: 0.3` to `1.4`; a test rejects
  `scrub: true`), and CSS smooth scrolling was removed (it fights ScrollTrigger) in favour of eased `ScrollToPlugin` tweens.
* **Instant show and hide.** Panels, suggestions, views and results appeared and vanished. Drawers slide, suggestions pop, views cross-fade (and route
  changes are serialised so two fades never overlap), results stagger in, and a theme change cross-fades.
* **Cost.** Large blur filters, backdrop blur on every panel and SVG rings animated on the main thread were removed; the rings and floating plates use the
  individual `rotate` and `translate` CSS properties on their own layers, and GSAP keeps `transform` for scroll and pointer effects on the same elements.

The `gpt-taste` skill was run again and its seeded selection followed: **Artistic Asymmetry** hero (text offset left, art floating in from the bottom
right), **Geist** (not bundled: it needs a download the owner has not approved, so the stack lists Geist first and falls back to the bundled Outfit),
**Inline Typography Images** (two pills in the headline), **Horizontal Accordions** (the four signals; replaces the bento, whose gapless property is now the
accordion's: its slices always sum to the full width, measured 1,145 against 1,144 pixels), **Feedback Carousel** (the evidence of the current results, now
with drag, dots and "show it in the judgment"), **Scroll Pinning** (the principles section) and **Scrubbing Text Reveal** (the statement). `Flip` and
`ScrollToPlugin` were copied from the already downloaded and hash-checked `gsap-3.15.0.tgz`; nothing new was fetched.

New interactions: the ranking ladder with animated re-ordering, treatment-flagged filter, expand all, keyboard navigation and a shortcuts panel, copy id,
reader previous and next, jump from a piece of evidence to the cited passage in the citing judgment, tooltips on the score bars, toasts, a scroll-progress
line and a request indicator, magnetic buttons and a pointer-following glow on the accordion, and in the judging screen auto-advance to the next ungraded
document with `j`, `k` and `n`. Measured here: the structure, states and behaviour in a browser pane at phone, tablet and desktop widths. Not measured:
frame rate on the owner's machine (the pane throttles animation frames, so timing could not be profiled).

### D-029 (2026-10-07) Geist bundled; a submission audit, the pipeline figure and a report draft
* **Geist.** The owner approved the download (supersedes the "not bundled" clause of D-028). `@fontsource-variable/geist` 5.3.0 was fetched with `npm pack`
  and its Latin and Latin Extended variable files copied unmodified to `app/web/static/fonts/` with the SIL OFL text; hashes are in
  `app/web/static/vendor/README.md` and a test checks them. Outfit stays as the bundled fallback. Geist Mono was not downloaded (ids and code use the
  system monospace font). Geist's default spacing is tighter than Outfit's, so the display letter-spacing was loosened (headline `-0.04em` to `-0.03em`,
  the closing call to action `-0.045em` to `-0.034em`) after the first render showed glyphs touching.
* **`eval/submission_check.py`.** One command for the machine-checkable items of the submission checklist, with four levels: PASS, TODO (not done yet),
  FAIL (a rule is broken) and MANUAL. It reads files only and makes no number. A folder that is merely inside another repository is treated as not a
  repository (found by its own test, because the test folders live under the checkout). On this branch it reports no FAIL; the TODOs are exactly the
  data and steps that need people (the real providers, the judged queries, qrels, gold list, the agreement report, the tuned weights, the result files,
  and the AI-log entries whose human review is still pending).
* **`eval/figures.py`.** The pipeline diagram from ARCHITECTURE.md as `docs/figures/pipeline.png` and an editable `.svg`, drawn by code so it can be regenerated;
  it carries no measured number (a test checks).
* **`docs/REPORT_DRAFT.md`.** The report prose that does not depend on results (problem, IR concept table with files, libraries in IR terms, beyond IR,
  limitations, AI-use declaration), with a `<FILL: file>` wherever a number, a measured fact or an owner's input is needed. No claim about retrieval
  quality is made; the novelty claims are labelled as design claims until section 5 supports them.
* **What is not done, and why.** The judged queries, the two judges' grades and the gold overruling list are made by hand and are not written; the corpus (200
  judgments, all 2025) cannot support the plan until M1 grows it (D-027); M2 and M3 still have their real functions off, so the evaluation runner
  refuses to produce results. The test-set table, the report PDF and the video follow those.

### D-030 (2026-10-07) Third integration pass: M1's ISO dates, the 30 candidate queries, a robust pytest folder
* **Branches.** `origin` fetched and every branch compared with `m4-rank`: only `m1-index` had a new commit (`287846e`, ISO dates in `judgments.jsonl`), merged
  without conflict. `main`, `m2-statute` and `m3-treatment` are unchanged and already contained. Results of the re-run are in docs/INTEGRATION_REVIEW.md (update of
  2026-10-07): the date finding is closed for `judgments.jsonl`, and `bench_size` 0 (27 records) is the only failure left when the real search and statute are on.
* **The 30 candidate queries and their criteria** (added to the working tree by another coding assistant, declared in AI_USE_LOG.md and reviewed here for
  consistency): five more candidates (`test16` to `test20`), `eval/examples/query_grade_criteria.example.md`, and the updated guide. They are inputs, not labels:
  `eval/queries.jsonl` and `eval/qrels.tsv` stay empty until people adopt, verify and grade. `eval.feasibility` was re-run on them and confirms the guide's table
  (3 answerable, 17 thin, 10 empty on the 200 judgments of 2025). **Risk to watch:** the criteria name the cases a judge should expect at each grade; a judge who grades
  from those names without reading the judgment would turn an AI-written aid into the label, which rule 5 forbids. The guide already says every pair is graded after
  reading the actual judgment. The workbench hides scores, ranks and system names but not the judgment itself, and two judges who copy the same aid would
  agree with each other and raise kappa without reading anything, so agreement alone cannot detect it: use the criteria to settle disagreements, not to pre-assign grades.
* **pytest folder.** A locked `.pytest_tmp` (a file watcher or editor holding it open on Windows) made every test error with `PermissionError` before it started. A
  root `conftest.py` now falls back to a fresh folder for that run and removes stale ones; `.gitignore` covers `.pytest_tmp*`.

### D-031 (2026-10-07) Fourth integration pass, the Index page for M1, and the 90-second M4 demo
* **Branches.** `origin` fetched again: `m1-index` (+2), `m2-statute` (+1) and `main` (M2 merged) had moved; `m3-treatment` had not. All merged into `m4-rank`. Each branch was also
  run on its own: `main` and `m2-statute` **fail the shared smoke gate** (M2's `stubs.statute: false` without `doc_statutes.jsonl`, and a malformed `statute_map.csv`). Findings and
  the messages to send are in docs/INTEGRATION_REVIEW.md ("Second update"). M2's files were taken as pushed; the malformed map was **not** edited here: the owner has to decide the
  layout. A converted copy was used in a scratch folder only, to measure what works once the map is fixed (real search plus real statute: `BNS 103 -> IPC 302 (OFF_MURDER)` appears as
  continuity, `section 103` follows the offence date, prose `sedition` and `murder` are understood).
* **Tests follow M1's and M2's new code**: helpers my earlier connection fix had added to `searcher.py` (`is_plain_text`, `_engine`, `min_year`) no longer exist, so those tests
  now call the public `search()`; `extract_refs` takes the judgment date. Failures that remain are M2's own and are not hidden: the continuity robustness test and M2's own 7 hour-0 tests.
  `eval.conformance` now checks the index `search()` actually loads (`index.pkl.gz`) and calls the old files stale; CI builds the index before the tests.
* **`make build-index` builds only the index.** `python -m m1_index.ingest build` empties `judgments.jsonl` when `data/raw` is empty (M1 finding 13).
* **The Index page** (`#/index`, `app/m1_view.py`, `app/web/static/js/m1.js`): a separate page for M1's pipeline built from the owner's list (corpus, text processing, indexing, querying,
  retrieval). It reads M1's real index, read-only: counts, zone shares, the tokenizer step by step (and a flag if the walk-through ever differs from M1's `tokenize()`), postings with
  zone counts and positions, the parsed query tree, zone-weighted BM25 with one calculation worked out, a **check of the index against a plain scan of all the text** (agrees for Boolean,
  phrase, AND, OR and NOT queries tested; proximity is not checked), and measured latency (median and 95th percentile of 15 runs; no library-BM25 comparison exists). Items on the
  owner's list that the pushed code does not contain (lnc.ltc, query optimisation) are marked "not in the pushed code", lnc.ltc by probing `m1_index.scoring` at run time. Design: the
  `gpt-taste` skill was run with the seed 1017 (length of the request): artistic-asymmetry hero, Geist, a horizontal accordion for the five stages, inline typography pills in the
  headline, a feedback-style carousel (the query as a quotation, its best results as overlapping plates), scale-and-fade scroll on the panels and hover physics on tiles and plates;
  opacity never goes below 0.5 and nothing is dimmed with a filter. Not measured: frame rate on the owner's machine.
* **`docs/DEMO_M4.md`**: M4's 90-second demo from the existing screens (no separate M4 page is needed: the Search page already shows fusion, the ladder and the breakdown; Evaluation and
  Judging show how it will be measured), with what to say, the queries that work on the current corpus, and what to do when a module is not ready.

### D-032 (2026-10-07) `m4-rank` on `main`; navigation fixes; the request tracker
* **`m4-rank` pushed to `main` at the owner's request** (a fast-forward: `main` had been merged into `m4-rank` first, including M1's pull request #3). The merge gate of CLAUDE.md is **not
  met on one count**: `python -m pytest` has 8 failures, all in M2's statute layer (M2's own 7 hour-0 tests and the continuity robustness test, which fails because M2's pushed map is malformed);
  `python eval/smoke.py` passes with the configuration as committed. `stubs.statute` stays `true` on `main`: M2's `false` made `main` fail its own smoke gate (the file it reads is not in git and
  the map is invalid), and the owner has not fixed either yet. Every stub is still flagged on every screen.
* **Navigation.** Search pressed from further down the page changed the highlight but did not scroll, and a link to the hash already in the address bar did nothing (no `hashchange`). The router now
  scrolls to the top for Search and to the section for Method, and the nav links handle a click on the current hash themselves; the status button lost its name when its text was hidden and the
  five links plus the status text overflowed below 900 px (the text is hidden from 900 px down and the button has its own label). Every other button on the Search, Method, Evaluation,
  Judging and Index screens was clicked in a browser: the ranking ladder, ranked and compare modes, result count, the treatment filter, expand all, the shortcuts and status panels, the
  reader with previous and next, copy id (the browser pane refuses clipboard access; the page says so), the keyboard shortcuts, the theme button, the hero and call-to-action buttons, the
  method accordion, and the Index page's stages, jumps, carousel, forms, check and latency buttons. The browser pane throttles animation frames, so scroll positions were measured by stepping
  GSAP's ticker; frame rate on a real machine was not measured.
* **The request tracker** (docs/INTEGRATION_REVIEW.md) lists, per module, what was asked and what the pushed code does today.

### D-033 (2026-10-07) M3 fixes from the integration review (docs/INTEGRATION_REVIEW.md on m4-rank, M3 findings 5-10)
Measured on M1's 200 judgments of 2025 (on `main`) and on a 203-judgment test corpus (those 200 plus Koushal, Navtej
Johar and Joseph Shine downloaded from the public bucket). Treatment labels in the test run came from a keyword stand-in
kept outside the repo, used only to exercise the pipeline; they are not results.
* **Resolver and bench sizes.** `resolver.py` is taken unchanged from m4-rank (D-026: doc_ids with a language suffix such
  as `_EN`, dates in any shape, mixed-case coram lines), and `bench_of` now prefers the coram line to M1's `bench_size`.
  On M1's corpus the coram line is readable for all 200 judgments; it agrees with `bench_size` wherever both are known,
  except 7 three-judge benches stored as 2 (M1's `judges` keeps "Vikram Nath, Sanjay Karol" as one name), and it fills
  the 27 unknown sizes (21 three-judge and one five-judge bench in all). Before: doc_ids in the dataset form 0 of 200,
  bench known 173 of 200; after: 200 of 200 for both.
* **Running headers (finding 10).** A name-only, unresolved mention is a self-reference when every distinctive token of the
  title's private side (not a government word, not a common name, not frequent in the corpus) occurs in it, and its other
  side opens with a word of the title or its initials (`windows.is_own_title`). This catches headers that are truncated
  ("Sudershan Singh Wazir v. State"), abbreviated ("NAVTEJ SINGH JOHAR v. UOI THR. SECY") or glued to the next words
  ("Mahabir & Ors. v. State of Haryana Code of Criminal Procedure"). Appeal-history tags on M1's corpus: 477 before,
  58 after (on the test corpus 665 before, 63 after). I read all 224 distinct (judgment, name) pairs then treated as
  self-references in the test corpus: one was a different case ("Sanjay v. Union of India" in "Sanjay v. State of
  U.P."), which the other-side test now keeps.
* **Appeal history for non-Supreme-Court decisions (finding 7).** "set aside", "reversed", "quashed" or "impugned" must
  occur in the mention's own sentence within 250 characters of it (`windows.appeal_context`), not anywhere in the
  window: the next sentence's "the judgment of the High Court is set aside" is this Court's order on the appeal.
* **Evidence choice (finding 5).** `extract` records `in_headnote` per mention: whether it lies before the jurisdiction
  line ("CRIMINAL ORIGINAL JURISDICTION", "Case Arising From CRIMINAL APPELLATE JURISDICTION") where the reporter's
  headnote and its "Case Law Cited" list end (`text.body_start`). Evidence sorts a headnote mention after a reasoning
  mention of the same strength, and each evidence item carries `in_headnote` (true, false, or null when
  `m3_mentions.jsonl` is missing). On Navtej, the 14 Koushal windows the stand-in labelled overruled split into 7
  headnote lines (including the one after Shayara Bano that the review flagged) and 7 reasoning sentences; the evidence
  is now a reasoning sentence. The health score is unchanged: a headnote line still counts as a treatment.
* **The marker (finding 8).** `citations.jsonl` keeps `[[ ]]` around the cited mention in `window` (and so in the
  evidence `sentence`), so a reader can find the treating sentence; strip `[[`/`]]` before searching the judgment text.
  This replaces the last sentence of D-017.
* **Names (finding 6).** A name restarts after a lower-case "in"/"since" or "Cited" ("A Constitution Bench in Bachan
  Singh v. ..." gives "Bachan Singh v. ..."). The respondent side stops at a heading or running-text word (Code, Writ,
  Petition, List, Although, Section, ...), after "& Ors." / "& Anr.", and at a lower-case "the" that does not follow
  "of"/"by"/"through". Margin letters on the edge of a text line ("Reserve Bank of \nC India") are dropped in
  `clean_text`; a letter in mid-line is an initial ("Aparna A Shah") and stays. On the test corpus (all name and full
  mentions): a lead-in such as "Court in" 55 to 0; a heading word after the respondent 30 to 0; a lower-case "the" on
  the respondent side 60 to 28, most of which are real ("State Represented by the Inspector of Police"), a few still
  run on ("State of Bihar of the PW-20"). Known limit: a capitalised word after a name still joins it.
* **Memory and errors (finding 9).** `run_health` streams citations.jsonl and keeps only resolved, non-appeal records (the
  unresolved 98% are dropped as read) and writes doc_health.jsonl as it goes. It warns when citations.jsonl names
  judgments that are not in judgments.jsonl (it was built from another corpus): rebuild citations and health whenever
  M1 rebuilds. Pipeline and `gold sample` commands print one `error:` line instead of a traceback when an input is
  missing; `gold merge` reads sheets saved by Excel as "CSV UTF-8" (byte-order mark); `python -m m3_treatment.scores`
  no longer triggers runpy's double-import warning (the package imports `scores` on first use).
* **Pinned model (finding 9).** `gemini_caller` refuses a moving alias or preview id (`*-latest`, `*-preview`, `*-exp`),
  and each cache row records the `model_version` that answered. The configured id is now `gemini-3.5-flash-lite`
  (stable; temperature 1.0; 30 windows per request): on 2026-10-07 the free tier of `gemini-2.5-flash` stopped at its
  20 requests a day after 160 of the 269 corpus windows, and `gemini-3.8-flash` returned 503 (high demand). All 269
  labels in use come from one model (the cache key includes it), zero-shot until the gold set exists. Google's model page (read 2026-10-07) says 2.5 access is now limited to projects that
  used it before and recommends temperature 1.0 for Gemini 3. If the key is refused, set `llm.model` to a stable
  Gemini 3 id and `llm.temperature: 1.0`; the cache key includes the model, so nothing stale is reused.
* **The label cache is committed (closes OQ-5).** It moved from the git-ignored `data/cache/` to
  `data/llm_labels/m3_llm_labels.jsonl`. It is small (hash keys and labels, no judgment text), and with it anyone can
  rebuild `citations.jsonl` and `doc_health.jsonl` offline, without an API key, which is the frozen-output rule.

### D-034 (2026-10-07) Fifth integration pass: the 468-judgment corpus, and how much corpus the evaluation needs
* **Branches.** `m1-index` (+4, the 468-judgment corpus), `m2-statute` (+1) and `m3-treatment` (+1, also on `main`) merged into `m4-rank`; `main` was not touched. Results, new findings (M1-19, M1-20,
  M2-12) and the request tracker are in docs/INTEGRATION_REVIEW.md (third update). Tests: 561 passed, 1 expected failure (M2's own tests pass again). They follow the corpus: the year filter test partitions by the years present instead of assuming 2025.
* **`eval.feasibility --target N`** states how far the corpus is from N candidate judgments per query, which queries have none (they need specific judgments added) and, under a stated assumption (matches grow
  in proportion to the corpus; a match is not a relevant judgment), the corpus size that would bring the median query and 90% of the others to N. Hand-checked test included.
* **Is the corpus enough? No** (measured, not assumed): median 3 candidate judgments per query, 4 of 30 queries reach 10, 6 have none, no overruled and overruling pair is present, nothing before 2024.
  Recommendation: about 1,500 to 2,000 judgments, built as a base spread over 2015 to 2025 plus **targeted** additions (the judgments the search finds for each query's words, and both ends of every doctrine
  query). Choosing documents by the queries' words is corpus construction, not labelling, and is recorded here so the report can say so. Random sampling alone would need about 1,200 judgments for the median
  query and about 4,700 for 90% of those with a match, and still could not help the 6 queries with none.
* **Stub switches.** `python eval/smoke.py` passes with search and statute real for the first time; the switches are the owners' to flip and stay `true`. CI now builds M2's `doc_statutes.jsonl` as well as M1's index.

### D-035 (2026-10-07) The progress watcher
`python -m eval.progress_watch` (also `make watch`) fetches every branch, merges `m4-rank` and every lane's new commits into a **separate worktree** (`.watch/wt`, branch `integration/watch`, never pushed,
git-ignored), rebuilds what is derived, runs the tests, the smoke gate twice, the conformance check, `eval.feasibility --target 10`, M3's extract stage and the submission audit there, and scores each lane
from those results (the weights and the checks are in `LANES` of the script; partial credit for counts such as "27 of 35 benches right"). A merge that conflicts is aborted and reported with its files. The
owner's working tree is never touched; `--apply` fast-forwards the checked-out `m4-rank` to the integration branch only when the tree is clean, the merge is a fast-forward, the tests did not get worse and the score did
not drop, and it commits and pushes nothing of its own. The score is readiness for the submission, not retrieval quality; the report PDF, the video and the clean-machine test are listed but not scored. Reports
name lanes and never people (commit authors are not read).

## Open questions

* **OQ-1** How is the 200-document sample shared with the team (committed under `data/sample/`, a release asset, or a shared
  drive)? M1 decides in hours 0-3. `data/processed/` is git-ignored. Note that CI runs `python eval/smoke.py`: once a module
  flips its stub switch, the data it reads must be available to CI, which favours committing a small sample.
* **OQ-2** Which corpus subset keeps ranking meaningful and the index laptop-friendly (for example criminal cases from 2000
  onwards)? M1 decides once the sample shows what the data looks like.
* **OQ-3** Code licence. No licence has been chosen; the dataset's CC-BY-4.0 attribution applies regardless.
* **OQ-4** Whether a larger-bench reference or a stayed provision should show as its own treatment state in the demo (for
  example sedition, where the operation of the section was stayed rather than struck down). Needed for the limitation segment
  of the video; verify the facts against the orders first.
* **OQ-5** Closed by D-033: the LLM label cache is committed (`data/llm_labels/`), so `citations.jsonl` and
  `doc_health.jsonl` rebuild offline from M1's corpus. Still open: how CI reads `doc_health.jsonl` (ship it with M1's
  sample, OQ-1, or rebuild it in CI from the committed cache).
