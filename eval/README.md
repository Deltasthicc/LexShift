# Evaluation (owner: M4)

Everything needed to measure whether adding statutory continuity and judicial treatment improves ranking over plain BM25.

**Writing the queries and the grades by hand: read [JUDGING_GUIDE.md](JUDGING_GUIDE.md)** (example queries, the grading rules with
worked examples, and the step-by-step commands).

| Tool | What it does |
|---|---|
| `python -m eval.pool` | pools the top-20 of every system into a blind judge sheet (`eval/judging/<round>/`) |
| `python -m eval.make_qrels` | reconciles the two judges, reports kappa, lists disagreements, writes `qrels.tsv` |
| `python -m eval.check_data` | checks queries, qrels and the gold list against the plan |
| `python -m eval.feasibility` | counts what the corpus holds for each query (coverage only, never a grade) |
| `python -m app.server` | the web interface; its **Judging** screen is the blind two-judge workbench that writes `judge1.csv` and `judge2.csv` |
| `python -m eval.run_ablation` | tunes on dev, evaluates, writes the table, per-query CSV and chart |
| `python eval/smoke.py` | contract and end-to-end check (the merge gate) |

## Systems compared

| Name | Signals | Meaning |
|---|---|---|
| `b0` | rel | BM25 only: the baseline |
| `b1` | rel + cont | adds statutory continuity |
| `full` | rel + cont + health + auth | adds judicial treatment and authority (`b2` is accepted as an alias) |

## The judged query set (written by hand, never generated)

`queries.jsonl`, one JSON object per line: `{"qid", "text", "offence_date", "split", "type"}`.

* **30 queries: 10 `dev`, 20 `test`.** Weights are tuned on `dev` only; headline numbers are reported on `test`.
* Types: **A** a BNS query needing an IPC precedent; **B** changed or omitted provisions; **C** doctrines with overruled
  cases; **D** bare-number collisions (for example "section 302").
* `offence_date` is an ISO date or `null`; it drives the IPC/BNS code choice.

`qrels.tsv`: tab-separated, header `qid<TAB>doc_id<TAB>grade`. Grades: **2** relevant and good law; **1** relevant but the
law materially changed or the precedent was criticised; **0** irrelevant, or overruled on the queried point. Documents that
are not listed for a query count as 0 (the pooling assumption).

**Pooling.** Judge the union of the top-20 of every system, with two judges. Do not derive the grades from the mapping or
the classifier the system uses (circularity): read the judgments. `eval.pool` writes the sheet blind (shuffled, no scores, no
ranks, no system names) and is incremental, so a later round only asks about documents that are not graded yet.

`gold_overrulings.csv`: hand-verified overrulings, used **only** to compute `harmful@k`. Columns: `overruled_doc_id`,
`overruling_doc_id`, `point`, `source`, `verified_by`. Verify each row against the judgments before using it.

## Metrics

All defined in `metrics.py`, with the choices written down in [DECISIONS.md](../DECISIONS.md) (D-007).

## Honesty rules

* Never tune on `test`. `run_ablation.py --tune` refuses to run on it.
* Results computed with any stub provider are not results: `run_ablation.py` refuses to write them unless `--allow-stubs`,
  and then names the files `stub_*` (git-ignored).
* With fewer than the full 30 queries, the table says how many queries it used.
