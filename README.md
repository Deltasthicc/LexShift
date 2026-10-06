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
python -m pytest            # unit tests
python eval/smoke.py        # contract + end-to-end check; the merge gate for main
```

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
| `make build-index` | `python -m m1_index.ingest build` then `python -m m1_index.index build` | M1 |
| `make build-statutes` | `python -m m2_statute.extractor build` | M2 |
| `make build-citations` | `python -m m3_treatment.citations build` | M3 |
| `make build-health` | `python -m m3_treatment.scores build` | M3 |
| `make demo QUERY='...'` | `python -m app.cli "..." [--offence-date YYYY-MM-DD]` | M4 |
| `make eval` | `python -m eval.run_ablation --split test` | M4 |
| `make tune` | `python -m eval.run_ablation --tune` | M4 |
| `make pool ROUND=round1` | `python -m eval.pool --round round1` | M4 |
| `make qrels ROUND=round1` | `python -m eval.make_qrels --round round1` | M4 |
| `make check-data` | `python -m eval.check_data` | M4 |
| `make feasibility` | `python -m eval.feasibility` | M4 |
| `make ui` | `python -m app.server` | M4 |
| `make conformance` | `python -m eval.conformance` | all |

The M1 to M3 commands are skeletons that print "not implemented yet" and exit non-zero until their owners land them.

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
| **Compare** | BM25 alone beside the selected ranking, with a line joining each judgment's two positions. B0, B1 and the full system are computed from one collection of signals, so switching is instant |
| **How the query was read** | the governing code, the sections found and their offence ids (M2) |
| **Reader** | the whole judgment in a side panel with the query's words marked |
| **System status** | the indicator in the navigation: which modules are real and which are stubs, the weights and where they come from, which data files exist. In stub mode a bar says so on every screen and every stub signal is hatched |
| **Evaluation** | the state of the hand-made files, the checks of `python -m eval.check_data`, and the ablation tables once they exist (stub runs are labelled) |
| **Judging** | the blind two-judge workbench for the pooled sheets: it writes `judge1.csv` and `judge2.csv`, shows no scores, ranks or system names, and never suggests a grade ([eval/JUDGING_GUIDE.md](eval/JUDGING_GUIDE.md)) |

The interface adds no ranking logic: it shows what `rank()` computes. Its decisions are in DECISIONS.md D-027.

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

*Last updated 2026-10-06 (M1, M2 and M3 merged into `m4-rank` and run together on real judgments: [docs/INTEGRATION_REVIEW.md](docs/INTEGRATION_REVIEW.md)).
This table is the honest state of the project; each owner updates their row when they merge.*

| Module | State on `main` |
|---|---|
| Shared contracts, config, stubs, smoke test | **Done**, with unit tests |
| M1 corpus, index and `search()` | **Search works** on a committed 200-judgment sample (all from 2025): Boolean, phrase, proximity and zone-weighted BM25 are correct, and free text is ranked. **Not done:** the corpus cannot be rebuilt (`ingest.py` and `index.py` are skeletons), `judgments.jsonl` breaks the `Judgment` contract (non-ISO dates, wrong bench sizes), no tests; so `stubs.search` stays `true`. Needs older judgments in the sample |
| M2 statute layer | **Minimal version**: reads `IPC 302` and `Section 103 of the BNS`, maps one section (IPC 302 to BNS 103). Misses most statute forms and reads paragraph numbers as sections; bare numbers are not resolved from the offence date; `stubs.statute` stays `true` until `doc_statutes.jsonl` is committed |
| M3 citations and treatment | **Code built and tested** (citation extractor and resolver, windows and appeal-history filter, Gemini and tf-idf classifiers, bench check, PageRank, real `health()` and `authority()`, gold-set tooling), its review fixes (cache key, gold merge, same parties, data checks) are merged and were re-verified; run end to end on 203 real judgments (a stand-in labeller, since there are no Gemini labels or gold set yet) and checked against M4's `rank()` and demo: Koushal comes out overruled by the 5-judge Navtej bench. **Not done:** the real labelling run, the gold set, the F1 table, a built `doc_health.jsonl` for the corpus; so `stubs.health` and `stubs.authority` stay `true` |
| M4 `rank()`, evaluation, demo | `rank()` (normalisation, weighted fusion, heap top-K, explanations), the metrics, the ablation and dev-only tuning runner, the pooling and two-judge qrels tools, the data checker, the feasibility counter, the CLI demo and the web interface (search, compare, evidence, status, evaluation and a blind judging workbench) are implemented and unit-tested against fixtures and the stubs, and the interface was checked in a browser on the 200-judgment sample; report skeleton, video script and submission checklist are drafted (branch `m4-rank`; skeleton only on `main` until it is merged) |
| Judged queries and qrels | **Not written yet: they are made by hand.** Example queries, rules, the query worksheet and the tooling are ready ([eval/JUDGING_GUIDE.md](eval/JUDGING_GUIDE.md)). `python -m eval.feasibility` shows that the current 200-judgment sample (all 2025) cannot support the plan: of the 25 example queries 2 are answerable, 16 thin and 7 empty, so the corpus has to grow first |

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
