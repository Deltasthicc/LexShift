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
cited case with `[[ ]]`. citations.jsonl stores the window without the markers.

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

### D-024 (2026-10-06) M3 merged into m4-rank and checked against M4
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

### D-025 (2026-10-06) M1 and M2 merged; the four modules connected and checked together
`m1-index` and `m2-statute` were merged into `m4-rank` (no conflicts). All four modules were then run end to end on real judgments
(M1's 200 plus three downloaded from the public bucket) and attacked with random and hostile input. Every finding, with the message to send
each owner, is in [docs/INTEGRATION_REVIEW.md](docs/INTEGRATION_REVIEW.md); `python -m eval.conformance` reproduces the data and API checks.

**Edits made in other owners' modules**, because the connection was broken without them and the task was to make it work. Each is the
smallest edit that fixes a verified failure; owners may take them or replace them:
* M1 `search.py`: index and corpus paths relative to the repository (they pointed at one person's home folder) and the same files `searcher.py`
  reads; no progress printing. `searcher.py`: `Hit` imported from `common.schema` instead of redefined; the engine is built on the first
  call instead of at import; a query with no operators is plain text (candidates are the documents containing any stemmed term, then BM25),
  so `BNS 103` and `3(5)` and `u/s` work; the year is read from `02 January 2025`-style dates and a missing year satisfies no year bound.
  `tokenizer.py` and `text_tokenizer.py`: a clear message when the NLTK stop words are missing. `requirements.txt`: `nltk`.
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
* **OQ-5** How the frozen M3 outputs reach the team and CI. The Gemini cache (`data/cache/`) and `data/processed/` are
  git-ignored, but `stubs.health` and `stubs.authority` can only be flipped to `false` once smoke (and CI) can read
  `doc_health.jsonl`. Options: commit the LLM cache (small text, makes rebuilds free) or ship `doc_health.jsonl` with
  M1's sample (OQ-1). M3 proposes committing the cache.
