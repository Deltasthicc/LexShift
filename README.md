# LexShift

**Good-law-aware search over Indian Supreme Court judgments.** LexShift ranks precedents by how well they match a query *and* by whether the law behind them still holds: whether the statute they interpreted has been replaced, and how later benches have treated them.

> Built for the CSD358 Information Retrieval mid-term hackathon (Shiv Nadar University), **Track 6: vertical search for law**.
> LexShift shows *treatment signals with evidence and a confidence*. It is a research prototype and **not legal advice**; it never declares a case unusable, it shows the sentence that a later court wrote and lets you judge.

**Where it stands (2026-10-07):** all four modules are real and wired together (nothing is a stand-in), on a corpus of **4,819 Supreme Court judgments**. 815 tests pass, the smoke check passes, and the web interface runs fully offline on a laptop CPU. The first evaluation (one judge, 10 dev queries) is done; the two-judge round and the test split are not. Details, numbers and limits are below.

---

## Contents

1. [Run it locally (read this first)](#run-it-locally)
2. [What LexShift does and why](#what-lexshift-does-and-why)
3. [How it works](#how-it-works)
4. [Status](#status)
5. [What is done](#what-is-done)
6. [Using it: the web pages, the command line, the evaluation](#using-it)
7. [Rebuilding things (optional)](#rebuilding-things-optional)
8. [Repository layout and branches](#repository-layout-and-branches)
9. [Limitations and future work](#limitations-and-future-work)
10. [Data, ethics, AI use, licence](#data-ethics-ai-use-licence)
11. [Documentation index](#documentation-index)

---

## Run it locally

Everything the demo needs is **in the repository**: the 4,819-judgment corpus (packed, 41 MB), the statute references, the treatment and authority scores, the titles and the citation records. You do **not** need an API key, a GPU or a data download; the only network use is installing the Python packages and NLTK's small stop-word list.

**You need:** Python **3.11**, git, about **2 GB** of free disk (the Python packages, the unpacked corpus and the index) and about 2 GB of RAM.

### The one-command way

```powershell
# Windows PowerShell
git clone https://github.com/Deltasthicc/LexShift.git
cd LexShift
.\run_demo.ps1
```

```bash
# macOS, Linux or Git Bash
git clone https://github.com/Deltasthicc/LexShift.git
cd LexShift
./run_demo.sh
```

The script creates `.venv` if there is none and installs `requirements.txt`, downloads NLTK's stop-word list, runs `python -m app.setup`, and starts the interface at **http://127.0.0.1:8765** with every module real. The first run takes about **3 minutes**, almost all of it building the search index; later runs start in seconds.
If PowerShell refuses to run the script, use `powershell -ExecutionPolicy Bypass -File .\run_demo.ps1`, or the manual steps below.

### The manual way

```bash
git clone https://github.com/Deltasthicc/LexShift.git
cd LexShift
python -m venv .venv
# activate:  .venv\Scripts\Activate.ps1   (Windows PowerShell)   |   source .venv/bin/activate   (macOS, Linux)
pip install -r requirements.txt
python -m nltk.downloader stopwords     # once; the tokenizer reads this list
python -m app.setup                     # once, and after every `git pull` (see below)
python -m app.server --real --open      # http://127.0.0.1:8765
```

**What `python -m app.setup` does**, each step only if it is missing or does not match the corpus:

1. unpacks `data/corpus/judgments.jsonl.xz` into `data/processed/judgments.jsonl` (checks its SHA-256);
2. restores the derived data from `data/corpus/derived/` (statute references, treatment and authority scores, titles, citation records), checking row counts and checksums;
3. loads the search index to prove it is readable, and **rebuilds it** (about 2.5 minutes) if it is missing, damaged or from another corpus;
4. checks that no `stubs:` switch is true and that no `LEXSHIFT_STUBS` override is set in your shell, and tells you if one is.

The interface also restores any missing data file from git when it starts, so a forgotten setup step cannot leave a page empty. Run `python -m app.setup` again after every `git pull`.

### Check that it is really all real

* The top bar shows a green pill, **All modules real**, and there is no yellow "Stub mode" banner. (Reload the browser tab after restarting the server; an old tab keeps the old status.)
* `python -m eval.submission_check` starts with `[PASS] every provider is real`.
* `python eval/smoke.py` ends with `0 failed` and its first line says `search=real, statute=real, health=real, authority=real`.

### Things to try

| Query (offence date) | What to look at |
|---|---|
| `adultery as an offence` | With **BM25 only**, *Sowmithri Vishnu* (1985, which upheld the adultery offence) is first. With **All four**, *Joseph Shine* (2018, which overruled it) is first and *Sowmithri* drops to second with treatment 0.10 and the sentence from *Joseph Shine* as evidence. Open a result to see the arithmetic |
| `BNS 103` (2025-01-10) | The offence date selects the BNS; continuity maps BNS 103 to IPC 302 as *equivalent*, so IPC-era murder precedents rank. The *Why* column says so |
| `IPC 302` (2020-06-01) | The same offence under the old code: continuity says *same provision* |
| `confessional statement to an NDPS officer under section 67` | *Kanhaiyalal* (overruled by *Tofan Singh*) matches the words best but is pushed down by its treatment score |
| `consensual same-sex relations section 377` | *Navtej Singh Johar* first; *Koushal*, which it overruled, is pushed out of the top results |
| `"common intention" /s murder`, `murder AND intention` | Proximity and Boolean queries (the Index page explains them) |

### If something goes wrong

| What you see | Why, and the fix |
|---|---|
| Yellow **Stub mode** banner, or "Overridden for this run by `LEXSHIFT_STUBS`" | A leftover `LEXSHIFT_STUBS` in your shell, or an old server still answering on port 8765. Start with `python -m app.server --real`, or clear it (`Remove-Item Env:LEXSHIFT_STUBS` in PowerShell, `unset LEXSHIFT_STUBS` in bash). `run_demo.ps1` does both and closes the old server |
| `doc_health.jsonl not found` (or another data file) | You skipped the setup. Run `python -m app.setup`. Do **not** run `python -m m3_treatment.scores build`: it needs files that are built by other steps |
| "The Index page cannot read M1's index" / a decompression error | The index file is damaged or from an older build. `python -m app.setup` rebuilds it (about 2.5 minutes) |
| The first search takes a few seconds | The first query loads the index; later ones take tens of milliseconds |
| Titles show as ids | `python -m app.docmeta`, then restart the server |
| `Path traversal blocked` / `EOFError` from `nltk.downloader` | Your user-data folder is redirected (some desktop-app shells do this). Run that one command from an ordinary Windows Terminal or PowerShell window |
| Port 8765 is busy | `python -m app.server --real --port 9000`, or close the other server |

Run the checks with `python -m pytest` (815 tests, about 2 minutes), `python eval/smoke.py` and `python -m eval.conformance`.

---

## What LexShift does and why

A precedent can match your query perfectly and still be unsafe to cite. It goes stale in two ways:

* **Statutory change.** The Bharatiya Nyaya Sanhita (BNS) replaced the Indian Penal Code (IPC) on 1 July 2024, and the BNSS replaced the CrPC. Numbers moved (murder: IPC 302 became BNS 103), numbers collided (BNS 302 is *not* murder), and some provisions were modified, split, merged, omitted or newly created. The offence date decides which code applies, so both codes are live at once.
* **Judicial treatment.** A later bench of equal or larger strength overruled, doubted, criticised or distinguished it.

Free tools rank by text relevance, so stale and healthy precedents look alike. Paid tools (SCC Online, Manupatra) show overruled flags beside the results. LexShift's contribution is to use statutory continuity and aggregated judicial treatment **inside the ranking function**, not as a warning bolted on afterwards, and to show the evidence behind each status.

## How it works

For each query LexShift fetches the 100 best candidates with BM25, then re-ranks them with four signals, each scaled to 0 to 1:

```
final(q, d) = w_r * rel(q,d)  +  w_s * cont(q,d)  +  w_h * health(d)  +  w_a * auth(d)
```

| Signal | Meaning | Module |
|---|---|---|
| `rel` | zone-weighted BM25 relevance of the judgment to the query | M1 |
| `cont` | statutory continuity: how much of the judgment's statutory basis carries over to the code that applies to the query (IPC 302 to BNS 103: 1.0; omitted provisions: 0.1) | M2 |
| `health` | lowered if a *valid* later bench overruled (0.1) or doubted (0.6) the judgment; otherwise 1.0 | M3 |
| `auth` | authority: PageRank over the citation graph (followed and neutral citations), weighted by bench strength | M3 |

Three systems are compared, from the same candidates, with weights in `common/config.yaml`: **B0** BM25 only (the baseline), **B1** 0.7 relevance + 0.3 continuity, **Full** 0.5 / 0.2 / 0.2 / 0.1. The Full weights are untuned starting values; tuning on the dev queries is one command once there are enough grades.

Design rules: old IPC judgments are not dead (a BNS query still retrieves them, penalised only in proportion to how much the law changed); treatment is classified only on the passage around a specific cited case, never by keyword matching a whole judgment; "set aside on appeal" is not an overruling; a smaller bench cannot overrule a larger one; newer is not stronger. The live demo runs offline on a laptop CPU with no live language model; the one model step (labelling citation windows) ran offline once and its outputs are frozen in `data/llm_labels/`.

Pipeline diagram and where each IR concept lives in the code: [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md).

---

## Status

| Part | State |
|---|---|
| Shared contracts, config, setup, tests | **Done.** 815 tests pass, the smoke check passes, `python -m eval.submission_check` has 0 failures; one command (`run_demo.ps1` / `run_demo.sh`) sets up and runs everything real |
| M1 corpus, index, search | **Done.** 4,819 judgments, compact positional index, Boolean / phrase / proximity queries, BM25 and lnc.ltc |
| M2 statutes, continuity | **Done**, apart from checks only people can make: 35 of the 36 map rows are still unverified against the official tables, and the 50-judgment precision check is open |
| M3 citations, treatment, authority | **Done** on the 4,819-judgment corpus (labels cached, no key needed to rebuild). Open: the hand-labelled gold set and the per-class F1 table |
| M4 ranking, evaluation tools, interface | **Done.** `rank()`, metrics, pooling, qrels, ablation, harmful@10 report, six web pages |
| Evaluation | **Dev split graded by one judge (10 queries): done.** Open: the test split (20 queries), the two-judge round, the gold overruling list (draft ready), weight tuning |
| Report, video, clean-machine test | Not part of the code; tracked in [docs/SUBMISSION_CHECKLIST.md](docs/SUBMISSION_CHECKLIST.md) |

---

## What is done

### M1: corpus, index and search ([m1_index/README.md](m1_index/README.md))

* **Corpus: 4,819 English Supreme Court judgments.** The public dataset holds 38,147 English judgments (19.5 GB of PDF); loading all of it does not suit an offline laptop demo, so the corpus is the **criminal-law part of 2005 to 2025** (judgments whose title looks criminal and whose text mentions IPC, BNS, CrPC, BNSS, NDPS and similar) **plus the named doctrine cases** the queries need (both ends of nine overruling pairs). 7,850 judgments were downloaded and read; 4,819 kept. `data/corpus_manifest.csv` lists each one and why it is in. The pipeline (`python -m m1_index.ingest download`) is resumable and offline after the download.
* **Text and zones.** PDF to text, then four searchable zones (headnote, facts, arguments, holding) by headings and position; titles, dates, benches and reporter citations parsed from OCR'd volumes.
* **Index.** Our own inverted and positional index with zone and year/bench fields, stored compactly (183,673 terms, 3.8 million postings, 17.3 million positions; 52.7 MB on disk, loads in about 2 s). Boolean, phrase and proximity queries (`AND OR NOT`, `"phrases"`, `/s`, `/p`, `/k`) with query optimisation (smallest posting list first). Zone-weighted BM25, lnc.ltc cosine and heap top-K, checked against the `rank_bm25` library (`m1_index/reports/benchmark.md`).
* **Coverage:** 26 of the 30 judged queries have at least 10 candidate judgments (it was 4 of 30 before the corpus grew); 9 of the 10 doctrines have both an overruled and an overruling judgment in the corpus.

### M2: statutes and continuity ([m2_statute/README.md](m2_statute/README.md))

* A typed mapping of 36 provisions (21 IPC to BNS, 15 CrPC to BNSS) with a relation and weight for each (`equivalent` 1.0, `modified_elements` 0.5, `omitted` 0.1, ...).
* An extractor that reads statute references in all the forms judgments use (`u/s 302 IPC`, `S. 302 I.P.C.`, `Sections 302 and 307 of the Indian Penal Code`, `BNS 3(5)`, `the Code`), gives a bare "Section N" its act from the same judgment, and ignores sections of other statutes. 65,036 distinct references over 190,518 mentions; the share with an unknown act fell from 68% to 37%.
* A query parser (a bare number takes its code from the offence date) and `continuity()` with an explanation such as `BNS 103 -> IPC 302 (equivalent)`. All 9 statute forms in the build guide are read; offence ids come from the map, so one offence has one id across both codes.
* The sedition row (IPC 124A to BNS 152) was corrected after reading the PRS legislative brief: sedition was removed and clause 152 only "may have retained aspects", so it is `modified_elements` 0.5, not `equivalent`.

### M3: citations and judicial treatment ([m3_treatment/README.md](m3_treatment/README.md))

* **Find** every reference to an earlier case (SCR, SCC, AIR, SCALE, JT, neutral citations, "X v. Y", `supra` and later short forms): 160,705 mentions. **Resolve** each to a judgment in the corpus (reporter key, then SCR page range, then party-name similarity): 25,853 resolved (16.1%; the rest cite High Court, foreign or pre-2005 decisions), 9,453 distinct citing-to-cited edges. **Window**: the citing sentence plus one either side, with appeal history excluded (2,573 mentions).
* **Classify** (offline, once): Gemini (`gemini-3.5-flash-lite`, zero-shot) labelled the 1,010 windows that mention a cue such as overruled or doubted, because only `overruled` and `doubted` can lower a score. Result: 142 overruled, 65 doubted, 188 valid negatives (the citing bench is at least as large as the cited one). All answers are cached in `data/llm_labels/`, so rebuilding needs no key and the demo never calls a model.
* **Score**: `health()` lowered for 48 judgments (including *Sowmithri Vishnu*, *V. Revathi*, *Kanhaiyalal*, *Raj Kumar Karwal*, *P. Rathinam*, *Salauddin* and *Navjot Sandhu*, each with the later court's sentence as evidence); `authority()` is our own PageRank over 25,319 citation records, times a bench weight.

### M4: ranking, evaluation and the interface ([m4_rank/README.md](m4_rank/README.md), [eval/README.md](eval/README.md))

* **`rank()`**: per-signal normalisation, weighted fusion, heap top-K and a human-readable explanation for every score. `python -m app.cli` prints the weights, each signal's raw and scaled value and its contribution.
* **Evaluation tools**: a pooling tool (builds blind judging sheets from the top results of every system), a two-judge qrels builder with Cohen's kappa and adjudication (and a clearly-labelled single-judge mode), the metrics (P@5, P@10, Recall@10, MAP, nDCG@10, harmful@10, judged@10), an ablation and dev-only tuning runner with paired-bootstrap intervals, a data checker, a feasibility counter, and `eval.harmful_report` (known-overruled judgments in the top 10, no grades needed).
* **The web interface** (offline, Python standard library only, nothing fetched from the network): see the next section.
* **Setup and checks**: `python -m app.setup`, `run_demo.ps1/.sh`, `python -m eval.conformance` (each module's artefacts against the shared contracts), `python -m eval.submission_check` (the submission checklist, as far as a program can check it), `python -m eval.progress_watch`.

### Evaluation so far (honest status)

* **30 hand-written queries** (10 dev, 20 test) across four types: a BNS query needing an IPC precedent, changed or omitted provisions, doctrines with overruled cases, and bare-number collisions.
* **First real result, single judge, dev split** (`eval/results/ablation_dev.md`; one person graded 70 pooled documents of the 10 dev queries; starting weights; all four modules real):

| System | P@5 | P@10 | Recall@10 | MAP | nDCG@10 |
|---|---|---|---|---|---|
| B0: BM25 only (baseline) | 0.740 | 0.440 | 0.810 | 0.709 | 0.727 |
| B1: + statutory continuity | 0.760 | 0.470 | 0.866 | 0.712 | 0.736 |
| Full: all four signals | 0.800 | 0.480 | 0.883 | 0.729 | 0.732 |

  The signals push in the right direction, but the gains are small and the paired-bootstrap 95% intervals against B0 include zero (for example Full, P@5: +0.06, [-0.02, +0.14]). With one judge and 10 queries this shows the machinery works, **not** a significant improvement.
* **Not done yet:** the test split (20 queries) is ungraded; the two-judge round (`eval/judging/round1`, 680 pooled documents) is ungraded; `harmful@10` needs the gold overruling list (a draft with supporting passages is in `eval/gold_overrulings.draft.csv`, to be read and adopted by a person; on the draft, `eval.harmful_report` shows for example *Kanhaiyalal* falling from rank 1 under B0 to rank 6 under Full); M3's hand-labelled gold set and per-class F1 table; weight tuning on dev.

---

## Using it

### The web interface

`python -m app.server --real --open` (or `run_demo.ps1`). Pages, one per module:

| Page | What it shows |
|---|---|
| **Search** | free text, a section such as `BNS 103`, or a Boolean/proximity query, with an optional offence date. Three ranking steps (**BM25 only**, **+ Continuity**, **All four**) re-order the results so the effect of each signal is visible. Open a result for its score table (signal, score, weight, contribution, reason), the treatment evidence sentences with confidence and citing bench, and a reader with the judgment text |
| **Index (M1)** | how a judgment becomes searchable, on the real index: corpus, text processing (live tokenizer), postings of any term, the query parser's tree, BM25 scoring step by step |
| **Statutes (M2)** | how the query was read (governing code, sections, offence ids), continuity of the top results, and the mapping table |
| **Treatment (M3)** | the pipeline stage by stage on the real data: find citations, resolve, window, classify, scores |
| **Ranking (M4)** | the weights of each configuration, the state of the hand-made evaluation files, the checks of `python -m eval.check_data`, and the ablation tables when they exist |
| **Judging (M4)** | the blind grading workbench for the pooled sheets: no scores, ranks or system names are shown and no grade is suggested. Keys `0` `1` `2` grade, `j` and `k` move, `n` jumps to the next ungraded document. Every click is saved to `judge1.csv` or `judge2.csv` in the round's folder |

A status pill in the navigation says which modules are real; in stub mode a banner says so on every page. The page's Content-Security-Policy forbids any network fetch; fonts and GSAP are bundled in `app/web/static` ([versions and hashes](app/web/static/vendor/README.md)).

### The command line

```bash
python -m app.cli "adultery as an offence" --verbose -k 3
python -m app.cli "BNS 103 murder" --offence-date 2025-01-10 -k 3
```

Options: `--config b0|b1|full`, `-k`, `--json`, `--verbose` (query parse, weights, raw signals), `--evidence-chars N`.

### The evaluation workflow

```bash
# 1. Pool the documents to grade, from the real systems (writes blind sheets to eval/judging/<round>/)
python -m eval.pool --round quick --split dev --depth 5 --configs b0,b1,full
# 2. Grade them in the web page (#/judging), as judge 1 (and, for the real protocol, judge 2 independently)
# 3. Build the qrels (two judges: kappa and adjudication; or --single-judge, stated as such in agreement.md)
python -m eval.make_qrels --round quick --single-judge
# 4. Run the systems and score them
python -m eval.run_ablation --split dev                  # or --tune (dev only), then --split test
# 5. Optional, no grades needed: known-overruled judgments in the top 10 (needs eval/gold_overrulings.csv)
python -m eval.harmful_report
```

The queries, the grades and the gold overruling list are written **by people**, never generated. How, with worked grading rules: [eval/JUDGING_GUIDE.md](eval/JUDGING_GUIDE.md). The runner refuses stub providers, `--tune` never sees a test query, and with no grades it says so instead of printing numbers.

### Make targets

`make ready` (= `python -m app.setup`), `make test`, `make smoke`, `make ui`, `make demo QUERY='...'`, `make eval`, `make tune`, `make pool ROUND=...`, `make qrels ROUND=...`, `make check-data`, `make feasibility`, `make conformance`, `make final-check`, `make watch`, `make m3` and the other `m3-*` targets. Every target is a plain Python command listed in the Makefile; `make` is optional.

---

## Rebuilding things (optional)

You do not need any of this to run LexShift.

| To rebuild | Command | Time and needs |
|---|---|---|
| the search index | `python -m m1_index.index build` | about 2.5 minutes |
| the statute references | `python -m m2_statute.extractor` | about 20 seconds |
| titles for the pages | `python -m app.docmeta` | seconds |
| the whole corpus from the public bucket | `python -m m1_index.ingest download --years 2025-2005`, then `python -m m1_index.ingest pack` | 3.9 GB of PDFs, 1.5 to 2 hours; resumable; `--tier all` also takes non-criminal titles |
| M3 citations, health and authority from the cached labels | `make m3` (`python -m m3_treatment.pipeline build`) | about 5 minutes; no key |
| the treatment labels for new windows | put `GEMINI_API_KEY` in `.env` (see `.env.example`), then `python -m m3_treatment.pipeline label-llm` (`--dry-run` first) | resumable; the cache is committed |
| the packed derived data (maintainers, after any rebuild) | `python -m app.setup --pack`, then commit `data/corpus/derived/` | |

---

## Repository layout and branches

```
LexShift/
├── run_demo.ps1 / .sh   one command: set up the data and start the real interface
├── app/            setup.py (restore data), server.py and service.py (web), cli.py, web/ (pages, scripts, vendored fonts)
├── common/         schema.py (shared dataclasses), config.yaml (paths, switches, weights), contracts, provider wiring
├── data/           corpus/ (packed corpus and derived data, tracked), statute_map.csv, llm_labels/, treatment_gold.csv,
│                   corpus_manifest.csv; raw/ and processed/ are git-ignored and rebuilt
├── m1_index/       catalog, selection, ingest, zones, tokenizer, index, query parser, scoring, search, benchmark
├── m2_statute/     mapping, extractor, query parser, continuity, hand-check sampler
├── m3_treatment/   citation extraction and resolution, windows, classifier, graph, health(), authority()
├── m4_rank/        rank(): normalisation, fusion, explanations, weights
├── eval/           queries, qrels, metrics, pooling, ablation, harmful report, conformance, submission audit, judging rounds, results
├── stubs/          fixed-value stand-ins used only in tests and in integration (flagged, never evidence)
├── tests/          unit, connection and randomised robustness tests
└── docs/           ARCHITECTURE, CONTRACTS, WORKFLOW, DEMO_M4, REPORT and VIDEO drafts, INTEGRATION_REVIEW
```

Root documents: [PROJECT_BRIEF.md](PROJECT_BRIEF.md) (goal, rubric, constraints), [DECISIONS.md](DECISIONS.md) (every non-obvious decision, dated, with evidence), [AI_USE_LOG.md](AI_USE_LOG.md) (the AI-use declaration), [CLAUDE.md](CLAUDE.md) (instructions for coding assistants in this repo).

One long-lived branch per module (`m1-index`, `m2-statute`, `m3-treatment`, `m4-rank`) and `main` for integration, which is always runnable (merge only after `pytest` and `python eval/smoke.py` pass). Function signatures and file formats: [docs/CONTRACTS.md](docs/CONTRACTS.md); working rules: [docs/WORKFLOW.md](docs/WORKFLOW.md).

---

## Limitations and future work

**Limitations we faced**

* **Corpus is a subset.** Criminal-law judgments of 2005 to 2025 plus named cases, not all 38,147 English judgments: older precedents that are not named are absent, so only 16% of citations resolve to a judgment we hold.
* **Text quality.** Older volumes are OCR'd: zone boundaries are heuristics, and a few titles and bench sizes are wrong or missing (13 judgments have no bench).
* **Statutes.** The map covers 36 provisions, and only the sedition row was re-verified against an official source; 37% of statute mentions still have no resolvable act (mostly other statutes' small section numbers).
* **Treatment is cue-limited and imperfect.** Only windows with an "overruled" or "doubted"-type cue were sent to the model, so a treatment worded differently is missed (for example *Shafhi Mohammad* and *Asian Resurfacing* are not lowered); the citation resolver sometimes links a different case with a similar name (a *Frick India* citation was linked to *Revathi*); the model can misread a list of cited cases.
* **Ranking quirk.** Min-max scaling lets a document that repeats a term very often dominate a bare query such as `BNS 103`; continuity corrects it only partly.
* **Evaluation is thin.** One judge, 10 dev queries, untuned weights, no significant gain shown; the test split, the two-judge round, the gold overruling list, the treatment gold set and the F1 table are not done.

**What we would do next**

* Widen the corpus (all years, all titles: `fetch --tier all` already exists) and resolve more citations.
* Verify and extend the statute map against the MHA and PRS tables (including provisions the BNS dropped, such as IPC 377 and 497), and run the 50-judgment precision check.
* Check each name-based citation link against the mention's own reporter citation; classify every resolved window, with a second model for agreement.
* Finish the evaluation: grade the two-judge round and the test split, adopt the gold list, tune the weights on dev only, report on test with intervals, and build the treatment gold set and F1 table.
* Index sentence and paragraph boundaries for real `/s` and `/p` proximity; try learned weights or a small learning-to-rank model once there are enough grades; add regional-language judgments.

---

## Data, ethics, AI use, licence

* **Data.** The **Indian Supreme Court Judgments** dataset on AWS Open Data (<https://registry.opendata.aws/indian-supreme-court-judgments/>): public bucket `indian-supreme-court-judgments`, no AWS account needed, licence **CC-BY-4.0**, judgments from 1950 to 2025, attributed as described in [data/README.md](data/README.md). We store no personal data beyond what the courts publish, and we fetched only from the open dataset, one file at a time.
* **Not legal advice.** The output is treatment signals with evidence and a confidence; they can be wrong, can apply to one point of a judgment only, or can be superseded by a pending reference to a larger bench. Read the cited sentences and the judgments.
* **AI use.** AI coding assistants and the one LLM used for labelling citation windows are declared in [AI_USE_LOG.md](AI_USE_LOG.md), which becomes the AI-use declaration in the report. No relevance grade, gold label or judged query was generated: those are made by people.
* **Licence.** Code licence not yet chosen (a team decision, OQ-3 in [DECISIONS.md](DECISIONS.md)). The dataset is CC-BY-4.0 and must be attributed.

## Documentation index

| Document | What is in it |
|---|---|
| [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) | Pipeline, ranking function, where each IR concept lives in the code |
| [docs/CONTRACTS.md](docs/CONTRACTS.md) | Function signatures, file formats, vocabularies |
| [docs/WORKFLOW.md](docs/WORKFLOW.md) | Branches and merge rules |
| [m1_index/README.md](m1_index/README.md), [m2_statute/README.md](m2_statute/README.md), [m3_treatment/README.md](m3_treatment/README.md), [m4_rank/README.md](m4_rank/README.md) | Each module: status, method, measured numbers, limits |
| [data/README.md](data/README.md) | What is tracked, the dataset, attribution |
| [eval/README.md](eval/README.md), [eval/JUDGING_GUIDE.md](eval/JUDGING_GUIDE.md) | The evaluation protocol; writing queries and grades by hand |
| [docs/DEMO_M4.md](docs/DEMO_M4.md) | M4's video segment: pages, script, how to run, what to claim |
| [docs/INTEGRATION_REVIEW.md](docs/INTEGRATION_REVIEW.md) | The modules run together on real judgments: findings and the request tracker |
| [docs/REPORT_SKELETON.md](docs/REPORT_SKELETON.md), [docs/REPORT_DRAFT.md](docs/REPORT_DRAFT.md), [docs/VIDEO_SCRIPT.md](docs/VIDEO_SCRIPT.md), [docs/SUBMISSION_CHECKLIST.md](docs/SUBMISSION_CHECKLIST.md) | Report, video and submission checklist |
| [DECISIONS.md](DECISIONS.md), [PROJECT_BRIEF.md](PROJECT_BRIEF.md) | Decision log; goal, rubric, constraints, risks |
