# M3: citations and judicial treatment

Branch: `m3-treatment`. You work from M1's `judgments.jsonl` and hand M4 the `health()` and `authority()` signals.

**Goal.** Find how later judgments treated each earlier one, and turn that into health and authority scores.

## Status

The code is built and tested (`python -m pytest tests/test_m3_*.py`), including an end-to-end run on a four-judgment
corpus with a fake LLM. It has also run on M1's 200 judgments, and on those plus Koushal, Navtej Johar and Joseph Shine
from the AWS bucket with stand-in labels: `health(Koushal)` is 0.1 with a reasoning sentence of Navtej as evidence
(D-033). **Not done yet:** the hand-labelled gold set, the Gemini run and therefore the F1 table, and
`citations.jsonl` / `doc_health.jsonl` for M1's corpus. `stubs.health` and `stubs.authority` stay `true` until
`doc_health.jsonl` exists for the corpus and `python eval/smoke.py` passes with them `false`.

`citations.jsonl` keeps `[[ ]]` around the cited mention in `window`; evidence items carry `confidence`, `citing_bench`,
`in_headnote` and, on negatives, `offence_ids`. Rebuild both files whenever M1 rebuilds `judgments.jsonl` (`health`
warns when they come from another corpus). The Gemini labels are committed in `data/llm_labels/`, so rebuilding needs
no API key.

## What you build

- [x] Case-citation extractor: SCC, AIR, SCR and neutral citation formats, plus "X v. Y" case names. `citations.py`
      (also SCC OnLine, SCALE, JT, Cri LJ, and short forms "Koushal (supra)" / "Koushal" linked back to the full citation)
- [x] Resolver: link each citation to a `doc_id` via metadata; fallback is Jaccard on party-name tokens plus year. **Report the
      resolution rate**; unresolved citations are kept (`cited_doc = null`), never dropped. `resolver.py`,
      report in `reports/resolution.md`
- [x] Citation windows: the citing sentence plus or minus 1-2 sentences. `windows.py`, `text.py`
- [x] Appeal-history filter: if the cited case is the judgment under appeal (same parties, "impugned judgment", set aside),
      tag `is_appeal_history` and exclude it. That is a reversal, not an overruling. `windows.py`
- [x] Gold-set tooling: cue-word stratified sampler, labelling sheets, merge, adjudication, Cohen's kappa. `gold.py`,
      [LABELLING_GUIDE.md](LABELLING_GUIDE.md)
- [ ] Gold set of about 150-300 windows, labelled **by people**, two labellers on a subset. `data/treatment_gold.csv`
- [x] Classifier: LLM few-shot on the window (Gemini, offline, **every output cached**) and tf-idf + logistic regression
      (baseline); per-class precision, recall and F1. `classifier.py`, `pipeline.py evaluate`
- [ ] F1 table (needs the gold set and the Gemini run). `reports/classifier_f1.md`
- [x] Bench check: a negative label counts only if the citing bench is at least as large as the cited bench. `classifier.py`
      (bench from M1, else the coram line in the text; unknown means it does not count)
- [x] `health(d)`: strongest valid negative treatment (overruled 0.1, doubted/criticised 0.6, otherwise 1.0). `authority(d)`:
      PageRank (own power iteration) over positive and neutral edges x bench weight, normalised. `graph.py`, `scores.py`
- [x] Stretch: apply the penalty only for queries on the offence the overruling discusses (`offence_ids`, uses M2's
      `doc_statutes.jsonl` when present)

## How to run (offline; only `label-llm` uses the network)

```bash
python -m m3_treatment.pipeline extract          # judgments.jsonl -> m3_mentions.jsonl + reports/resolution.md (checks M1 fields; exits 1 if no bench is known)
python -m m3_treatment.gold sample --n 250 --double 60   # blank sheets in data/labelling/ -> label them by hand
python -m m3_treatment.gold merge                # kappa, disagreements.csv, data/treatment_gold.csv
python -m m3_treatment.pipeline label-llm --dry-run      # how many windows, requests and tokens
GEMINI_API_KEY=... python -m m3_treatment.pipeline label-llm   # Gemini labels into data/llm_labels/m3_llm_labels.jsonl (commit it)
python -m m3_treatment.pipeline evaluate         # reports/classifier_f1.md (LLM and baseline, per class)
python -m m3_treatment.citations build           # extract + data/processed/citations.jsonl  (make build-citations)
python -m m3_treatment.scores build              # data/processed/doc_health.jsonl           (make build-health)
```

`label-llm` is resumable: the cache is append-only, so an interrupted run continues where it stopped. Use `--limit N`
to spend a fixed budget. Settings (model, batch size, pacing, scope, thresholds) are under `m3_treatment:` in
`common/config.yaml`.

## Pipeline

```
judgments.jsonl
  -> clean_text (margin letters, running heads)            text.py
  -> mentions: full | cite | name | supra | alias           citations.py
  -> resolve: reporter key > SCR page range (+name) > party-name Jaccard + year     resolver.py
  -> window (sentence +/- 1, target marked [[ ]]) + appeal-history + self filter     windows.py
  -> label: Gemini (cached) or baseline; bench check -> valid_negative              classifier.py
  -> citations.jsonl
  -> PageRank over followed/neutral edges -> authority; strongest valid negative -> health     graph.py, pipeline.py
  -> doc_health.jsonl  ->  health(), authority()  (lookups only)                    scores.py
```

## You hand over

`citations.jsonl`, `doc_health.jsonl`, `treatment_gold.csv`, `health()`, `authority()`, and the classifier F1 table.
Contract: [../docs/CONTRACTS.md](../docs/CONTRACTS.md). Decisions: D-016 to D-024 and D-033 in [../DECISIONS.md](../DECISIONS.md).

## IR concepts you explain in the video

Citation graph, PageRank and static quality g(d), proximity windows, Jaccard matching, classifier evaluation.

## Done when

Both output files exist for the full corpus, the F1 table is done, and well-known overrulings in the corpus are flagged
(check for example Suresh Kumar Koushal, overruled by Navtej Singh Johar). Verify each against the judgments before use.

## Watch out for

Rare classes; "set aside" is not overruling; LLM cost and rate limits (cache); unresolved citations. Design rules: no raw
keyword matching for treatment, and newer is not stronger. The LLM runs **offline only**; nothing in the live demo may call
one. Declare the model and the prompts in `AI_USE_LOG.md`.
