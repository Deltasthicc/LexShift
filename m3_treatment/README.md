# M3: citations and judicial treatment

Branch: `m3-treatment`. You work from M1's `judgments.jsonl` and hand M4 the `health()` and `authority()` signals.

**Goal.** Find how later judgments treated each earlier one, and turn that into health and authority scores.

## What you build

- [ ] Case-citation extractor: SCC, AIR, SCR and neutral citation formats, plus "X v. Y" case names. `citations.py`
- [ ] Resolver: link each citation to a `doc_id` via metadata; fallback is Jaccard on party-name tokens plus year. **Report the
      resolution rate**; unresolved citations are kept (`cited_doc = null`), never dropped. `resolver.py`
- [ ] Citation windows: the citing sentence plus or minus 1-2 sentences. `windows.py`
- [ ] Appeal-history filter: if the cited case is the judgment under appeal (same parties, "impugned judgment", set aside),
      tag `is_appeal_history` and exclude it. That is a reversal, not an overruling. `windows.py`
- [ ] Gold set of about 150-300 windows. Use cue words only to find candidate windows (to fix class imbalance), then label by
      reading. Two labellers on a subset give Cohen's kappa. `gold.py`, `data/treatment_gold.csv`
- [ ] Classifier: LLM few-shot on the window (main; **cache all outputs**) and tf-idf + logistic regression (baseline).
      Report precision, recall and F1 **per class**. `classifier.py`
- [ ] Bench check: a negative label counts only if the citing bench is at least as large as the cited bench. `classifier.py`
- [ ] `health(d)`: strongest valid negative treatment (overruled 0.1, doubted/criticised 0.6, otherwise 1.0). `authority(d)`:
      PageRank over positive and neutral edges x bench weight, normalised. `graph.py`, `scores.py`
- [ ] Stretch: apply the penalty only for queries on the offence the overruling discusses (the `offence_ids` argument)

## You hand over

`citations.jsonl`, `doc_health.jsonl`, `treatment_gold.csv`, `health()`, `authority()`, and the classifier F1 table.
Contract: [../docs/CONTRACTS.md](../docs/CONTRACTS.md).

## IR concepts you explain in the video

Citation graph, PageRank and static quality g(d), proximity windows, Jaccard matching, classifier evaluation.

## Done when

Both output files exist for the full corpus, the F1 table is done, and well-known overrulings in the corpus are flagged
(check for example Suresh Kumar Koushal, overruled by Navtej Singh Johar). Verify each against the judgments before use.

## Watch out for

Rare classes; "set aside" is not overruling; LLM cost and rate limits (cache); unresolved citations. Design rules: no raw
keyword matching for treatment, and newer is not stronger. The LLM runs **offline only**; nothing in the live demo may call
one. Declare the model and the prompts in `AI_USE_LOG.md`.

## Hour 0-3 tasks

1. Wait for (or help check) M1's 200-document sample; run the citation extractor on it and count formats.
2. Start collecting candidate windows for the gold set and agree the labelling guide with the second labeller.
3. Make `health()` and `authority()` real on the sample (even a hand-checked handful), then flip `stubs.health` and
   `stubs.authority` to `false` once `python eval/smoke.py` passes.
