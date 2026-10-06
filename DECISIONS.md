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
