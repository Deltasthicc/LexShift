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
├── app/             command-line demo
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

The M1 to M3 commands are skeletons that print "not implemented yet" and exit non-zero until their owners land them.

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
Weights are tuned on dev only. Protocol and file formats: [eval/README.md](eval/README.md).

## Status

*Last updated 2026-10-06. This table is the honest state of `main`; each owner updates their row when they merge.*

| Module | State on `main` |
|---|---|
| Shared contracts, config, stubs, smoke test | **Done**, with unit tests |
| M1 corpus, index and `search()` | Skeleton and spec only; served by a stub |
| M2 statute layer | Skeleton and spec only; served by a stub; `statute_map.csv` is header-only |
| M3 citations and treatment | Skeleton and spec only; served by stubs; no labels yet |
| M4 `rank()`, evaluation, demo | Skeleton only on `main`; in progress on `m4-rank` |
| Judged queries and qrels | Not written yet (they are made by hand) |

No retrieval-quality result has been measured yet, so none is claimed here.

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
| [DECISIONS.md](DECISIONS.md) | Decision log |
| [PROJECT_BRIEF.md](PROJECT_BRIEF.md) | Goal, rubric, constraints, risks |
| Per-module `README.md` | Each owner's spec, hand-over and "done when" |

## Licence

Code licence: not yet chosen (a team decision; recorded as OQ-3 in [DECISIONS.md](DECISIONS.md)). The dataset is
CC-BY-4.0 and must be attributed as described in [data/README.md](data/README.md).
