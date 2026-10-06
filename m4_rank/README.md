# M4: fusion ranking, evaluation and delivery

Branch: `m4-rank`. You consume everyone's functions through the contracts, so integration starts on day one against the
stubs and the real modules replace them one by one.

**Goal.** Combine all signals into the final ranking, prove it works, and package the submission.

## What you build

- [ ] `rank()`: top-100 from `search()`, add continuity, health and authority, normalise, weighted sum, return top-K with the
      per-signal breakdown and an explanation. `rank.py`
- [ ] Ablation configs: **B0** BM25 only, **B1** + statute continuity, **full** (+ health + authority)
- [ ] 30 queries (10 dev, 20 test), four types: **A** BNS query needing an IPC precedent, **B** changed or omitted
      provisions, **C** doctrines with overruled cases, **D** bare-number collisions. Written by hand. `eval/queries.jsonl`
- [ ] Graded qrels from the pooled top-20 of all configs, two judges: 2 = relevant and good law, 1 = relevant but law
      materially changed or precedent criticised, 0 = irrelevant or overruled on the queried point. `eval/qrels.tsv`
- [ ] Metrics: P@5, Recall@10, MAP, nDCG@10, harmful@10 (overruled cases in the top 10). Tune weights on **dev only**.
      `eval/metrics.py`, `eval/run_ablation.py`
- [ ] Demo (CLI or Streamlit) with score breakdowns and evidence sentences. `app/`
- [ ] README, report skeleton, video script

## You hand over

`rank()`, the `eval/` scripts, **one command that prints the full metrics table**, the demo app, README, and the report and
video drafts.

## IR concepts you explain in the video

Net score, evaluation metrics (P@k, recall, MAP, nDCG), pooling, ablation.

## Done when

One command reproduces the metrics table, the demo runs live, and the report draft has all required sections.

## Watch out for

Never tune on test queries. Keep stubs working so integration starts on day one. The judged queries, the qrels and the gold
overruling list are made by hand: do not let a model generate the labels the system is scored against. Never write "dead
law" or "bad law" in the UI: say "treatment signals", show evidence and confidence, and include the not-legal-advice note.

## Status

See the status table in the top-level [README](../README.md#status).
