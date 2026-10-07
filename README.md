# LexShift

**Good-law-aware search over Indian Supreme Court judgments.** LexShift ranks precedents by how well they match a query
*and* by whether the law behind them still holds: whether the statute they interpreted was replaced, and how later benches
have treated them.

> Built for the CSD358 Information Retrieval mid-term hackathon (Shiv Nadar University), **Track 6: vertical search for law**.
> LexShift shows *treatment signals with evidence and a confidence*. It is a research prototype, **not legal advice**, and it
> never declares a case "bad law".

---

## Why

A precedent can match your query perfectly and still be unsafe to cite. It goes stale in two ways:

* **Statutory change.** The Bharatiya Nyaya Sanhita (BNS) replaced the Indian Penal Code (IPC) on 1 July 2024, and the BNSS
  replaced the CrPC. Numbers moved (murder: IPC 302 became BNS 103), numbers collided (BNS 302 is *not* murder), and some
  provisions were modified, split, merged, omitted or newly created. The offence date decides which code applies, so both
  codes are live at once.
* **Judicial treatment.** A later bench of equal or larger strength overruled, doubted, criticised or distinguished it.

Free tools rank by text relevance, so stale and healthy precedents look the same. Paid tools (SCC Online, Manupatra) show
overruled flags beside the results, and Indian Kanoon has a free "Reliability of a Precedent" feature that labels how the
court viewed cited text. LexShift's contribution is to use statutory continuity and aggregated judicial treatment **inside
the ranking function**, not as a warning bolted on afterwards, and to show the evidence behind each status. (We have not
verified whether Indian Kanoon aggregates across citing cases or feeds its ranking; the report compares honestly.)

## How it works

For each query LexShift fetches candidates with BM25, then re-ranks them with four signals, each in the range 0 to 1:

```
final(q, d) = w_r * rel(q,d)  +  w_s * cont(q,d)  +  w_h * health(d)  +  w_a * auth(d)
              weights tuned on DEV queries only, reported on TEST queries
```

| Signal | Meaning | Module |
|---|---|---|
| `rel` | BM25 relevance of the judgment to the query (zone-weighted) | M1 |
| `cont` | statutory continuity: how much of the judgment's statutory basis carries over to the code that applies to the query | M2 |
| `health` | lowered if a *valid* later bench overruled, doubted or criticised the judgment | M3 |
| `auth` | authority: citation-graph PageRank over positive and neutral citations, weighted by bench strength | M3 |

Three design rules:

1. **Old IPC judgments are not dead.** A BNS query still retrieves IPC precedents; we penalise only in proportion to how much
   the law changed.
2. **No raw keyword matching for treatment.** We classify only passages where a specific earlier case is cited, into
   followed / distinguished / doubted-criticised / overruled / neutral.
3. **Newer is not stronger.** Recency alone never raises or lowers a score; bench strength and treatment do.

Details and a pipeline diagram: [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md).

**Constraints that shape the design.** The live demo runs on a mid-range laptop CPU, offline, with no paid API and no live
language model. Anything that needed a GPU or an LLM (classifier training or few-shot labelling) runs offline and its outputs
are frozen files. Every number the demo shows comes from real code on real data; where something is not built yet, LexShift
says so instead of mocking it.

## Repository layout

```
LexShift/
├── common/          schema.py (shared dataclasses), config.yaml (paths, switches, weights), contracts, provider wiring
├── data/            statute_map.csv, treatment_gold.csv, raw/ and processed/ (git-ignored, rebuilt by the pipeline)
├── m1_index/        corpus ingest, zones, tokenizer, inverted+positional index, query parser, BM25, search()
├── m2_statute/      IPC<->BNS mapping, statute extractor, query statute parser, continuity()
├── m3_treatment/    citation extraction + resolution, treatment classifier, graph, health(), authority()
├── m4_rank/         rank(): normalisation, fusion, explanations, weight tuning
├── eval/            queries, qrels, metrics, ablation runner, smoke test
├── app/             command-line demo and the web interface (server.py, service.py, web/)
├── stubs/           fixed-value stand-ins for every cross-module function (flagged, never evidence)
├── tests/           unit tests
└── docs/            CONTRACTS.md, ARCHITECTURE.md, WORKFLOW.md
```

Also at the root: [PROJECT_BRIEF.md](PROJECT_BRIEF.md) (goal, rubric, constraints, risks),
[DECISIONS.md](DECISIONS.md) (every non-obvious decision, dated, with evidence),
[AI_USE_LOG.md](AI_USE_LOG.md) (the AI-use declaration, kept from the start), and [CLAUDE.md](CLAUDE.md) (instructions for
coding assistants working in this repo).

## Branches

One long-lived branch per module, plus `main` for integration. Each starts from the same skeleton, so every module can be
built and tested alone against the stubs.

| Branch | What it is for |
|---|---|
| `main` | Integration. Always runnable. Merge only after `pytest` and `python eval/smoke.py` pass |
| `m1-index` | Corpus ingestion, text processing, inverted and positional index, Boolean and proximity query parser, BM25 and tf-idf, `search()` |
| `m2-statute` | IPC to BNS (and key CrPC to BNSS) mapping, statute-citation extractor, query statute parser, `continuity()` |
| `m3-treatment` | Case-citation extraction and resolution, treatment classifier and gold set, citation graph, `health()` and `authority()` |
| `m4-rank` | Fusion ranking, ablations, judged queries and metrics, the demo, and the README, report and video drafts |

Rules for working across branches: [docs/WORKFLOW.md](docs/WORKFLOW.md). Function signatures and file formats that every
module codes against: [docs/CONTRACTS.md](docs/CONTRACTS.md).

## Quick start

Requires **Python 3.11** and git. Nothing else is needed to run the tests and the smoke check.

```bash
git clone https://github.com/Deltasthicc/LexShift.git
cd LexShift
python -m venv .venv
```

Activate the environment (`.venv\Scripts\Activate.ps1` on Windows PowerShell, `source .venv/bin/activate` on macOS or
Linux), then:

```bash
pip install -r requirements.txt
python -m nltk.downloader stopwords   # once; M1's tokenizer reads this list
python -m m1_index.ingest unpack      # once; the 4,819-judgment corpus from data/corpus/judgments.jsonl.xz (41 MB, tracked) into data/processed/, no network
python -m app.docmeta                 # once; case titles for the web page
python -m m1_index.index build        # once; M1's search index (about 140 seconds, 53 MB, git-ignored)
python -m m2_statute.extractor        # once; M2's statute references per judgment (about 20 seconds)
                                      # (the four lines above are `make data`)
python -m pytest            # unit tests
python eval/smoke.py        # contract + end-to-end check; the merge gate for main
```

If `python -m nltk.downloader stopwords` stops with `Path traversal blocked` and `EOFError`, your user data folder is redirected (this happens in
the shell of some desktop apps): run that one command from an ordinary Windows Terminal or PowerShell window instead. It is a one-time download into
your user profile; the tests and the demo read the list from there.

`make test` and `make smoke` do the same if you have `make`. Every Makefile target is a plain Python command, listed in
the next section.

### Stubs, and how you know a number is real

Until a module is built, `common/config.yaml` keeps its switch under `stubs:` set to `true` and the function is served by
a fixed-value stand-in from [stubs/fixed.py](stubs/fixed.py). Stub output is **never** evidence, and it is flagged
everywhere: `Result.stubbed`, a banner in the demo, and the evaluation runner refuses to write results from it. There is no
automatic fallback from a real function to a stub. Override a run with `LEXSHIFT_STUBS=none` (all real), `all`, or a list
such as `search,health`.

### Pipeline commands

| Make target | Command | Module |
|---|---|---|
| `make download` | `python -m m1_index.ingest download` | M1 |
| `make build-index` | `python -m m1_index.index build` (not `ingest build`: with an empty `data/raw` it empties `judgments.jsonl`) | M1 |
| `make build-statutes` | `python -m m2_statute.extractor build` | M2 |
| `make build-citations` | `python -m m3_treatment.citations build` | M3 |
| `make build-health` | `python -m m3_treatment.scores build` | M3 |
| `make m3` | `python -m m3_treatment.pipeline build`: the whole M3 pipeline from the committed label cache, no API key | M3 |
| `make m3-extract` | `python -m m3_treatment.pipeline extract`: mentions, resolution, windows, `reports/resolution.md` | M3 |
| `make m3-label-dry` | `python -m m3_treatment.pipeline label-llm --dry-run`: windows, requests and tokens, calls nothing | M3 |
| `make m3-label` | `python -m m3_treatment.pipeline label-llm` (needs `GEMINI_API_KEY`; `LIMIT=N` caps new windows) | M3 |
| `make m3-citations-baseline` | `python -m m3_treatment.pipeline citations --labels baseline` | M3 |
| `make m3-gold-sample` | `python -m m3_treatment.gold sample --n 250 --double 60` | M3 |
| `make m3-gold-merge` | `python -m m3_treatment.gold merge` (`ARGS=--allow-incomplete` merges the rows labelled so far) | M3 |
| `make m3-evaluate` | `python -m m3_treatment.pipeline evaluate`: per-class precision, recall and F1 | M3 |
| `make m3-test` | `python -m pytest tests/test_m3_*.py` (85 tests) | M3 |
| the Treatment page | `python -m app.server`, then `#/treatment` | M3's pipeline stage by stage on the real data (read-only) |
| `make demo QUERY='...'` | `python -m app.cli "..." [--offence-date YYYY-MM-DD]` | M4 |
| `make eval` | `python -m eval.run_ablation --split test` | M4 |
| `make tune` | `python -m eval.run_ablation --tune` | M4 |
| `make pool ROUND=round1` | `python -m eval.pool --round round1` | M4 |
| `make qrels ROUND=round1` | `python -m eval.make_qrels --round round1` | M4 |
| `make check-data` | `python -m eval.check_data` | M4 |
| `make feasibility` | `python -m eval.feasibility` | M4 |
| `make ui` | `python -m app.server` | M4 |
| `make final-check` | `python -m eval.submission_check` | M4 |
| `make watch` | `python -m eval.progress_watch` (`--every 600` repeats; `--apply` fast-forwards `m4-rank` when safe) | M4 |
| the Index page | `python -m app.server`, then `#/index` | M1's pipeline explained live against the real index (read-only) |
| `make figures` | `python -m eval.figures` | M4 |
| `make conformance` | `python -m eval.conformance` | all |

The M3 commands run the real pipeline end to end; [M3 below](#m3-citations-and-judicial-treatment) explains each stage.

## M3: citations and judicial treatment

M3 answers one question for every judgment: **what did later benches do with it?** Followed, distinguished, doubted,
overruled or neutral. The answer becomes two of the four ranking signals, `health()` and `authority()`, each backed by
the sentence that supports it. Full detail: [m3_treatment/README.md](m3_treatment/README.md).

**Status.** Built, tested (`make m3-test`, 85 tests) and run end to end on the 468-judgment corpus. `citations.jsonl`
and `doc_health.jsonl` cover every judgment, `health()` and `authority()` serve the live ranking, and
`LEXSHIFT_STUBS=none python eval/smoke.py` passes with every module real. The 269 citation windows that link two corpus
judgments are labelled by Gemini (`gemini-3.5-flash-lite`, zero-shot), run offline once and cached in
`data/llm_labels/m3_llm_labels.jsonl`: rebuilding needs no API key and the demo never calls a model. On a run that added
Koushal, Navtej Singh Johar and Joseph Shine from the AWS bucket, `health(Koushal)` is 0.1, with the reasoning sentence
of the five-judge Navtej bench as its evidence (D-033).

**On the 4,819-judgment corpus** (2026-10-07, night) `python -m m3_treatment.pipeline extract` finds 160,705 mentions, resolves 25,853 (16.1%) to a corpus judgment and 9,453 distinct
citing-to-cited edges, and tags 2,573 (1.6%) as appeal history. The labels below are for the old 468-judgment corpus: the new corpus needs 1,010 windows labelled (the scope is now `cued`: resolved windows
with an overrule or doubt cue, about 34 requests), which needs a Gemini API key (`.env`, see `.env.example`), then `make m3`. Until that run `stubs.health` and `stubs.authority` stay `true`.

**By the numbers of the earlier run** (the 468 judgments of 2024 and 2025):

| Stage | Result |
|---|---|
| Mentions found | 22,861; the 7,372 references of a judgment to itself are dropped |
| Citations kept | 15,489, in 421 judgments |
| By kind | case name 9,297 · later short form 4,070 · reporter citation 4,001 · full citation 3,856 · supra 1,637 |
| Resolved to a corpus judgment | 269 (1.7%): 201 by reporter citation, 68 by party name and year |
| Why the rest stay unresolved | they cite High Court, foreign or older Supreme Court judgments: 98% of the unresolved citations that carry a year cite one before 2024 |
| Appeal history, excluded | 133 |
| Labels on the 269 resolved windows | neutral 161 · followed 106 · distinguished 2 |
| Health | 1.0 for all 468: a two-year corpus holds no valid overruling of one of its own judgments |
| Authority | PageRank separates them; 53 judgments carry treatment evidence |
| Resolver check | 173 of 174 checkable reporter-citation links point to the judgment whose SCR citation the text gives |

**How it works, stage by stage** (each stage is a tab on the Treatment page):

1. **Find** (`text.py`, `citations.py`). The text is cleaned of margin letters and running page heads, then every
   reference to an earlier case is found: SCR, SCC, SCC OnLine, AIR, SCALE, JT, Cri LJ and neutral (INSC) citations, and
   "X v. Y" names. Five mention kinds: full, reporter citation, case name, `supra` ("Koushal (supra)") and later short
   forms ("the decision in Koushal"). Short forms point back to their full mention, because courts mostly state
   treatment in a short form: "Koushal stands overruled".
2. **Resolve** (`resolver.py`). Each mention is linked to a judgment: reporter key first, then SCR page range with a
   name check, then Jaccard similarity on party-name tokens plus the year. Unresolved mentions are kept and counted,
   never dropped; the rates go to `reports/resolution.md`.
3. **Window** (`windows.py`). The citing sentence plus one sentence either side, at most 1,500 characters, with the cited
   case marked `[[ ]]`, is what gets classified, not the whole judgment. Appeal history (the judgment under appeal,
   "impugned judgment", "set aside") is excluded: a reversal on appeal is not an overruling of a precedent.
4. **Classify** (`classifier.py`). Gemini labels each resolved window offline, with every answer cached under a key that
   includes the model; a tf-idf + logistic regression baseline is the comparison (`make m3-citations-baseline`). The
   bench check makes a negative label valid only if the citing bench is at least as large as the cited one. The
   gold-set tooling (`gold.py`) samples windows by cue word for two labellers, merges them with Cohen's kappa, and
   `make m3-evaluate` reports per-class precision, recall and F1 against those human labels.
5. **Score** (`graph.py`, `scores.py`). `health(d)` is the strongest valid negative: overruled 0.1, doubted 0.6,
   otherwise 1.0. `authority(d)` is PageRank by our own power iteration (damping 0.85) over followed and neutral edges,
   times a bench weight `log(1 + bench) / log(1 + 7)`, normalised to [0, 1]. With M2's offence ids a negative lowers
   health only for queries on the offence the overruling discusses. At query time both are lookups in `doc_health.jsonl`.

**IR concepts.** The citation graph and PageRank as a static, query-independent quality score g(d) added to relevance in
the net score; proximity windows, so only sentences around a specific cited case are classified; Jaccard matching in the
resolver; classifier evaluation by per-class precision, recall and F1, with Cohen's kappa for labeller agreement.

**Design rules.** No raw keyword matching for treatment; "set aside" on appeal is not an overruling; newer is not
stronger; a smaller bench cannot overrule a larger one; the LLM runs offline only and nothing in the live demo calls one.

## Demo

### Web interface

```bash
python -m app.server              # http://127.0.0.1:8765, reachable from this machine only
LEXSHIFT_STUBS=none python -m app.server --open
```

One page, offline, Python standard library only: no web font, script or image is fetched from the network (the page's
Content-Security-Policy forbids it), and the server checks the `Host` header and binds to the loopback address. GSAP with ScrollTrigger
(scroll motion) and the Outfit font are bundled in `app/web/static` from their official npm packages, with versions, licences and hashes in
[app/web/static/vendor/README.md](app/web/static/vendor/README.md). Press `/` to focus the search box.

| Screen | What it shows |
|---|---|
| **Search** | free text, a section such as `BNS 103`, or a Boolean/proximity query, with an offence date. Each result has its final score as one bar made of the four signals' contributions, the arithmetic and the reason behind each signal, the treatment status with the evidence sentences in full (with the classifier's confidence and the citing bench), and how far it moved against plain BM25 |
| **Ranking ladder and Compare** | Relevance, + continuity, + treatment and authority: switching steps re-orders the results with an animation, so the movement caused by each signal is visible. Compare puts BM25 alone beside the selected ranking with a line joining each judgment's two positions. All three systems are computed from one collection of signals, so switching is instant. "Treatment flagged only" keeps the results a treatment signal lowered |
| **How the query was read** | the governing code, the sections found and their offence ids (M2) |
| **Reader** | the whole judgment in a side panel with the query's words marked, previous and next result, and, opened from a piece of treatment evidence, the cited passage found, marked and scrolled to |
| **System status** | the indicator in the navigation: which modules are real and which are stubs, the weights and where they come from, which data files exist. In stub mode a bar says so on every screen and every stub signal is hatched |
| **Evaluation** | the state of the hand-made files, the checks of `python -m eval.check_data`, and the ablation tables once they exist (stub runs are labelled) |
| **Judging** | the blind two-judge workbench for the pooled sheets: it writes `judge1.csv` and `judge2.csv`, shows no scores, ranks or system names, and never suggests a grade ([eval/JUDGING_GUIDE.md](eval/JUDGING_GUIDE.md)) |

Keyboard: `j` and `k` move between results, `Enter` reads the focused judgment, `e` opens its details, `c` copies its id, `1` `2` `3` pick the signals,
`m` toggles compare, `f` flags only treatment-lowered results, `/` focuses the search box, `?` lists the shortcuts. In the judging screen `0` `1` `2`
grade the focused document and focus moves to the next ungraded one.

The interface adds no ranking logic: it shows what `rank()` computes. Its decisions are in DECISIONS.md D-027 and D-028.

### Command-line demo

```bash
python -m app.cli "BNS 103 murder" --offence-date 2025-01-10 -k 3 --verbose
```

Options: `--config b0|b1|full` (the ablation systems), `-k`, `--json` for machine-readable output, `--verbose` to also show
the query parse, the weights and the raw signals, `--evidence-chars N` to shorten the evidence passages. Each result shows its
score components, the reason behind each signal (for continuity, the statute mapping; for health, the label and the citing
judgment) and the evidence: the passage from the later judgment, shown in full (it is the evidence), with the classifier's
confidence and the citing bench when M3 supplies them.

Until M1 to M3 land their real functions the demo runs on the labelled stand-ins and says so loudly. This is real output of
that mode, **not a search result** (the ids and sentences are placeholders):

```
LexShift  |  config full  |  top 3  |  offence date 2025-01-10
query: BNS 103 murder

*** STUB MODE: rel, cont, health, auth come from fixed-value stand-ins, not from real data. This output is NOT a result. ***

 1. STUB-001   final 0.988
      rel    [####################]  1.00 x 0.50 = 0.500 (BM25 14.20)
      cont   [####################]  1.00 x 0.20 = 0.200 (STUB: fixed value, not computed from any judgment)
      health [####################]  1.00 x 0.20 = 0.200
      auth   [##################..]  0.88 x 0.10 = 0.088 (raw 0.80)
 ...
 4. STUB-003   final 0.723
      health [############........]  0.60 x 0.20 = 0.120 (doubted per STUB-000)
      evidence: doubted in STUB-000
        "STUB: fixed value, not computed from any judgment (placeholder sentence)"
```

If `data/processed/doc_meta.jsonl` exists (`python -m app.docmeta` derives it from `judgments.jsonl`), case titles, dates and
bench sizes are shown next to each id.

## Checking that the modules fit together

```bash
python -m pytest                      # unit, connection and randomised robustness tests (M1 to M4)
python eval/smoke.py                  # the merge gate: contracts and an end-to-end rank() with the providers selected in config.yaml
python -m eval.conformance            # real artefacts and real functions of M1, M2 and M3 against the shared contracts, per module
```

`eval.conformance` is the one to send to an owner: it names what breaks which contract and who has to act, and it exits 1 on a
failure. The full per-module findings from the first run on real judgments are in
[docs/INTEGRATION_REVIEW.md](docs/INTEGRATION_REVIEW.md).

## Data

Primary corpus: the **Indian Supreme Court Judgments** dataset on AWS Open Data
(<https://registry.opendata.aws/indian-supreme-court-judgments/>): public bucket `indian-supreme-court-judgments`, no AWS
account needed, licence **CC-BY-4.0**, judgments from 1950 to 2025. MVP scope is the English criminal-law judgments
(those mentioning IPC, BNS, CrPC or BNSS). Sources, attribution and what is still unverified:
[data/README.md](data/README.md).

## Evaluation

Systems compared: **B0** BM25 only, **B1** BM25 plus statutory continuity, **full** (plus health and authority). The plan
is 30 hand-written queries (10 dev, 20 test) across four types: a BNS query needing an IPC precedent, changed or omitted
provisions, doctrines with overruled cases, and bare-number collisions. Relevance is graded 0/1/2 by two judges over the
pooled top-20 of every system. Metrics: P@5, Recall@10, MAP, nDCG@10 and harmful@10 (known-overruled cases in the top 10).
Weights are tuned on dev only. Protocol and file formats: [eval/README.md](eval/README.md). The queries, the grades and the
gold overruling list are written **by hand** (two judges, blind sheets from the pooling tool, kappa reported); how, with example
queries and worked grading rules: [eval/JUDGING_GUIDE.md](eval/JUDGING_GUIDE.md).

Reproduce the table with one command, once the real modules and the hand-made queries and judgements exist:

```bash
python -m eval.run_ablation --tune --split test   # tune weights on DEV, report TEST
python -m eval.run_ablation --split test          # report TEST with the saved weights
```

It writes `ablation_test.csv`, `per_query_test.csv`, a Markdown table (with paired-bootstrap intervals against B0 and a
per-query-type breakdown) and a chart into `eval/results/`. It refuses to run on stub providers (and `--tune` refuses to see
a test query), and with no queries or judgements it says so instead of printing numbers.

## Status

*Last updated 2026-10-07 (M1, M2 and M3 merged into `m4-rank`, including M1's ISO-date commit, and run together on real judgments: [docs/INTEGRATION_REVIEW.md](docs/INTEGRATION_REVIEW.md)).
This table is the honest state of the project; each owner updates their row when they merge.*

| Module | State on `main` |
|---|---|
| Shared contracts, config, stubs, smoke test | **Done**, with unit tests |
| M1 corpus, index and `search()` | **Done (2026-10-07, night).** **4,819 English Supreme Court judgments** (the criminal-law part of 2005 to 2025 plus the named doctrine cases), read from the public AWS bucket by `python -m m1_index.ingest download`; tracked packed (`data/corpus/judgments.jsonl.xz`, 41 MB; `make unpack`). Zones, titles and benches parsed from OCR'd volumes; a compact positional index (52.7 MB, loads in about 2 s); Boolean, phrase and proximity queries with query optimisation; zone-weighted BM25 and lnc.ltc; checked against `rank_bm25`. `stubs.search` is `false`; 26 of the 30 judged queries have at least 10 candidate judgments (it was 4). Details and limits: [m1_index/README.md](m1_index/README.md) |
| M2 statute layer | **Done apart from verification by people (2026-10-07, night).** 9 of 9 statute forms read, bare numbers resolved (in queries by the offence date, in judgments from the same judgment and the map; UNKNOWN fell from 68% to 37% of 190,518 mentions), offence ids from the map (12,441 of 65,036 references), the sedition row corrected from the PRS brief. `stubs.statute` is `false`. **Open:** the other 35 map rows still cite just "MHA" and need two-source verification, and the 50-judgment precision check (`python -m m2_statute.audit_sample`) is for a person. [m2_statute/README.md](m2_statute/README.md) |
| M3 citations and treatment | **Done on the new corpus (2026-10-07, night): labelled, built, `stubs.health` and `stubs.authority` are `false`.** Citation extractor and resolver, windows, appeal-history and self-citation filters, Gemini and tf-idf classifiers, bench check, PageRank, `health()` and `authority()`, gold-set and evaluation tooling, all tested. On the 4,819-judgment corpus `extract` finds 160,705 mentions, 25,853 (16.1%) resolved to a corpus judgment, 9,453 distinct citing-to-cited edges. The labelling scope is `cued` (1,010 windows, 34 requests, all labelled by Gemini and cached in `data/llm_labels/`, so `make m3` rebuilds with no key): 142 overruled, 65 doubted, 188 valid negatives (the citing bench is at least as large as the cited one), health lowered for 48 judgments (*Sowmithri Vishnu*, *V. Revathi*, *Kanhaiyalal*, *Raj Kumar Karwal*, *P. Rathinam*, *Salauddin*, *Navjot Sandhu* among them), authority from 25,319 citation edges. Also open: the hand-labelled gold set, the F1 table, and a resolver that sometimes links a different case with a similar name (see D-039). [m3_treatment/README.md](m3_treatment/README.md) |
| M4 `rank()`, evaluation, demo | **On `main` since 2026-10-07.** `rank()` (normalisation, weighted fusion, heap top-K, explanations), the metrics, the ablation and dev-only tuning runner, the pooling and two-judge qrels tools, the data checker, the feasibility counter, the CLI demo and the web interface (search, compare, evidence, status, evaluation and a blind judging workbench) are implemented and unit-tested against fixtures and the stubs, and the interface was checked in a browser on the 200-judgment sample; the report skeleton and a prose draft, the pipeline diagram (`python -m eval.figures`), the video script and the submission checklist are written, and `python -m eval.submission_check` audits the checklist's machine-checkable items (branch `m4-rank`, merged into `main` on 2026-10-07). What remains for M4 is data that only people can make: the judged queries, the two judges' grades and the gold overruling list, then tuning on dev and the test table, the report PDF and the video |
| Judged queries and qrels | **Queries written (30, adopted by the owner); grades and the gold overruling list are not written: they are made by hand.** On the 4,819-judgment corpus `python -m eval.feasibility --target 10`: 27 ok, 2 thin, 1 empty, and **26 of 30 queries reach 10 candidate judgments** (it was 4 of 30); 9 of the 10 doctrines have both an overruled and an overruling judgment. **The first judging round is pooled** (`eval/judging/round1`: 680 documents from the real B0 and B1 systems; grading is by two people, `#/judging`), and a second round adds what the full system surfaces once M3 is real. Corpus: [m1_index/README.md](m1_index/README.md) |

No retrieval-quality result has been measured yet, so none is claimed here. The unit tests check the arithmetic against
hand-computed values on small synthetic fixtures; they say nothing about how well LexShift retrieves.

## Ethics, data use and AI use

* Dataset credited under CC-BY-4.0; we store no personal data beyond what the courts publish. Prefer the open dataset over
  crawling; if anything is ever fetched from a website, we obey `robots.txt` and rate-limit.
* The output is treatment signals with evidence, not legal advice.
* AI coding assistants and any LLM used for labelling are declared in [AI_USE_LOG.md](AI_USE_LOG.md), which becomes the
  AI-use declaration in the report.

## Documentation

| Document | What is in it |
|---|---|
| [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) | Pipeline, ranking function, where each IR concept lives in the code |
| [docs/CONTRACTS.md](docs/CONTRACTS.md) | Function signatures, file formats, vocabularies, the stub wiring |
| [docs/WORKFLOW.md](docs/WORKFLOW.md) | Branches, merge rules, the 36-hour plan |
| [eval/JUDGING_GUIDE.md](eval/JUDGING_GUIDE.md) | Writing the queries and grades by hand: worksheet, grading rules and worked examples, the workbench, the pooling and qrels tools |
| [docs/SUBMISSION_CHECKLIST.md](docs/SUBMISSION_CHECKLIST.md) | What to tick before submitting; `python -m eval.submission_check` checks the machine-checkable items |
| [docs/REPORT_SKELETON.md](docs/REPORT_SKELETON.md), [docs/REPORT_DRAFT.md](docs/REPORT_DRAFT.md) | The report's structure, and the prose that can be written before the evaluation exists (every result is a `<FILL>` from a file) |
| [docs/DEMO_M4.md](docs/DEMO_M4.md) | M4's 90-second demo: what to show, what to say, and what to do when a module is not ready |
| [docs/VIDEO_SCRIPT.md](docs/VIDEO_SCRIPT.md) | The demo video, segment by segment, with the live commands |
| [docs/INTEGRATION_REVIEW.md](docs/INTEGRATION_REVIEW.md) | The four modules run together on real judgments: findings per module and what to send each owner |
| [docs/REPORT_SKELETON.md](docs/REPORT_SKELETON.md) | The 8-page report, section by section, with where each number comes from |
| [docs/VIDEO_SCRIPT.md](docs/VIDEO_SCRIPT.md) | The 5 to 8 minute video: segments, live commands, recording checklist |
| [docs/SUBMISSION_CHECKLIST.md](docs/SUBMISSION_CHECKLIST.md) | Everything to tick before submitting |
| [DECISIONS.md](DECISIONS.md) | Decision log |
| [PROJECT_BRIEF.md](PROJECT_BRIEF.md) | Goal, rubric, constraints, risks |
| Per-module `README.md` | Each owner's spec, hand-over and "done when" |

## Licence

Code licence: not yet chosen (a team decision; recorded as OQ-3 in [DECISIONS.md](DECISIONS.md)). The dataset is
CC-BY-4.0 and must be attributed as described in [data/README.md](data/README.md).
