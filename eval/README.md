# Evaluation (owner: M4)

Everything needed to measure whether adding statutory continuity and judicial treatment improves ranking over plain BM25.

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
the classifier the system uses (circularity): read the judgments.

`gold_overrulings.csv`: hand-verified overrulings, used **only** to compute `harmful@k`. Columns: `overruled_doc_id`,
`overruling_doc_id`, `point`, `source`, `verified_by`. Verify each row against the judgments before using it.

## Metrics

All defined in `metrics.py`, with the choices written down in [DECISIONS.md](../DECISIONS.md) (D-007).

## Honesty rules

* Never tune on `test`. `run_ablation.py --tune` refuses to run on it.
* Results computed with any stub provider are not results: `run_ablation.py` refuses to write them unless `--allow-stubs`,
  and then names the files `stub_*` (git-ignored).
* With fewer than the full 30 queries, the table says how many queries it used.
