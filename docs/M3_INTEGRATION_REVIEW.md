# M3 integration review (2026-10-06)

What was checked when M3's branch was merged into `m4-rank`: whether the code is complete against the Build Guide, whether it
fits M4's contracts, and whether it is accurate on adversarial input. It is a review of the code as merged, not of results:
there is no corpus yet, so nothing here says how well M3 performs on the real data.

**Method.** The full suite (`python -m pytest`: 308 tests at merge time, 65 of them M3's) and the shared smoke check were run.
M4's [integration test](../tests/test_m4_m3_integration.py) runs M3's real pipeline on a small synthetic corpus and drives M4's
`rank()` and demo with M3's real `health()` and `authority()`. Each item marked **verified** below was reproduced by running M3's
code; the rest come from reading it.

## What works

* All Build Guide items for M3 exist: extractor (SCC, AIR, SCR, INSC, SCC OnLine, SCALE, JT, Cri LJ, plus `supra` and short-form
  links), resolver, windows, appeal-history filter, classifiers, bench check, PageRank, `health()`, `authority()`, gold-set tooling.
* M3's output satisfies M4's runtime contract checks, including with `offence_ids`, and `doc_health.jsonl` covers every judgment.
* The design rules hold in the code: only windows around a specific cited case are classified ("objection overruled" is never
  seen), a smaller bench cannot validate a negative, an unknown bench never lowers health, recency is not used, no silent
  fallback when labels are missing, and the demo path never imports the LLM client or scikit-learn (tested).
* The LLM step is offline, resumable and cached; `--dry-run` estimates cost first.

## What is not done (M3 says so itself)

No `citations.jsonl` or `doc_health.jsonl` exist; no gold set, Gemini labels or F1 table; the code has run on 9 real judgments and a
synthetic corpus only. `stubs.health` and `stubs.authority` correctly stay `true`.

## Findings

| # | Severity | Finding |
|---|---|---|
| 1 | Medium-high, **verified** | The LLM cache key is `sha256(prompt version, model, window)` and omits the few-shot examples, although its docstring says everything that can change the answer is in the key. |
| 2 | Medium, **verified** | `gold merge` can wipe typed adjudications, and silently accepts a nearly empty sheet. |
| 3 | Medium, **verified** | `same_parties` treats different cases with a shared party name as one dispute. |
| 4 | Medium | Three silent dependencies on M1's output, and no report of how many negatives the bench check discards. |
| 5 | Low-medium, **verified** | Case-name extraction keeps neighbouring words and some false names. |
| 6 | Low-medium | Evidence windows lose their `[[ ]]` marker, so no consumer can find the treating sentence. |
| 7 | Low | Memory: every mention's window is loaded; the demo loads all evidence text at the first call. |
| 8 | Low | Commands print raw tracebacks when inputs are missing; `-m m3_treatment.scores` prints a runpy warning. |
| 9 | Low | `classify_llm` re-reads the cache file per call; the Gemini model alias is not pinned; kappa returns 1.0 when undefined. |

### 1. The few-shot examples are not in the cache key (verified)

`build_prompt` puts the examples into the prompt, but `cache_key` ignores them. Running `LLMLabeller` once without examples and
again with examples makes **zero new API calls** and keeps the first (zero-shot) label. Consequences: windows labelled before the
gold set exists stay zero-shot forever; the examples are the first two gold windows per class in hash order, so they change as the
gold set grows or adjudications change, and nothing relabels; the F1 table would be labelled "few-shot" while scoring a mixture.
Suggested fix: add a hash of the examples (and the prompt text) to the key, or stamp each cache row with it and make `citations`
and `evaluate` refuse rows whose stamp differs; and make `label-llm` refuse to run when `few_shot_per_class > 0` and the pool is empty
unless a `--zero-shot` flag says so.

### 2. `gold merge` (verified)

`merge()` rewrites `disagreements.csv` from the current sheets on every run. If the second labeller's sheet is missing or empty,
`disagreements` is empty and the file is rewritten as a header only: the adjudications already typed in are gone, and
`treatment_gold.csv` shrinks, with no warning. Separately, rows with a blank label are skipped silently: with 3 of 250 windows
labelled, `merge` reports `L1=3` and writes a 3-window gold set without saying that 247 are missing. M4's `eval/make_qrels.py` hit
the same pattern in review (DECISIONS.md D-015): leave the file alone while an input has problems, and report unlabelled counts.
The gold file is also written non-atomically.

### 3. Appeal-history false positives (verified)

`same_parties("Ram Singh v. State of Bihar", "Ram Singh v. State of U.P.")` is `True`. A different case with the same first party is
tagged `is_appeal_history` and excluded, so a genuine overruling by a later case that repeats a party name would be dropped.
Common names make this plausible in criminal appeals. Suggested: require a second signal (review or curative wording, "our order
dated", a near date) or count and print how many resolved Supreme Court citations are tagged appeal history so it can be audited.

### 4. Silent dependencies on M1

* The exact-key and page-range steps of the resolver rely on `doc_id` matching `<year>_<vol>_<first>_<last>`. If M1 uses another id,
  `CorpusIndex` silently skips those steps and resolution falls back to names with stricter thresholds. Nothing warns.
* `reporter_citations` must hold the dataset's citation strings; `bench_size` (or judges, or a coram line) must be recoverable.
  Without bench sizes no overruling passes the bench check and the demo shows overruled cases as healthy.
* `run_citations` returns only `valid_negatives`. Suggested: report negatives found, and how many were discarded for an unknown
  bench, a smaller bench, or low confidence, and a pre-flight line in `extract` (share of ids matching the pattern, share with
  citations, share with a known bench) that fails loudly when a share is near zero.

### 5. Name extraction noise (verified)

`A Constitution Bench in Bachan Singh v. State of Punjab` (leading words kept), `Ram Kishan Vs. State of Haryana the Court` (trailing
words kept), and `Bench v. Bar` is read as a case. Mentions with a reporter citation are unaffected (the exact key wins), but
name-only resolution, `same_parties` and the resolution-rate denominators use these names.

### 6. The treating sentence cannot be located

`citations.jsonl` stores the window without its `[[ ]]` markers, and `doc_health` evidence copies it. The treating sentence is usually
the middle of three, so a UI cannot highlight it and a short excerpt can cut it off (M4's demo showed exactly that before it was
changed to show the whole window). Suggested: keep the markers (or `target_start`, `target_end`) in the evidence.

### 7. Memory

`run_health` loads every record of `citations.jsonl` into memory, including unresolved mentions with their windows, and
`scores._table()` loads all evidence text on the first call. Unmeasured; it scales with corpus size and mentions per judgment.
Suggested: keep windows only for mentions that can become evidence (resolved, not appeal history), or stream.

## Cross-module requests

* M1: populate `bench_size` and `reporter_citations`, and keep the dataset's `<year>_<vol>_<first>_<last>` `doc_id` (or tell M3).
* M2: `doc_statutes.jsonl` with `offence_id` values is what makes point-level health work; without it every penalty always applies.
* All: before flipping `stubs.health`/`stubs.authority`, run `python eval/smoke.py` with them `false` on the 200-document sample.
