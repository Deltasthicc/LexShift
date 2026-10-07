# M4 video segment: ranking, evaluation and the interface (about 2 minutes 15)

**Your part (M4):** the fusion ranking `rank()` (four signals, one score), the evaluation tools (pooling, grading, metrics, ablation, tuning) and the web pages **Search**, **Ranking** and **Judging**.
You do not explain the other pages' internals (Index is M1, Statutes M2, Treatment M3): each owner shows their own.

All four modules are **real** now: `python -m eval.submission_check` says `[PASS] every provider is real`. Nothing on screen is a stand-in. Everything below is a live screen or a live command; read no number off this file.

## How to run it (do this once, before you record)

```powershell
cd C:\Users\shash\Downloads\IRHackathon
git pull origin main        # the latest main has everything below; your partners do the same
.\run_demo.ps1              # restores the data, clears any stale stub override, stops an old server on port 8765, starts the real one
```

`run_demo.ps1` is `python -m app.setup` (restores the 4,819-judgment corpus, the statute, treatment and authority data and the search index from files in git, no key and no network, about 3 minutes the first time) followed by `python -m app.server --real --open`.
The top bar must show the green pill **All modules real** and no stub banner; reload the browser tab after any server restart, an old tab keeps the old status. The page opens on an intro screen: press **Start searching**.
Then `python -m eval.submission_check` must say `[PASS] every provider is real`.

**Why you saw stub mode:** an old server was still running, started from another terminal with `LEXSHIFT_STUBS=health,authority` still set in that shell (a leftover from a test run); the page then says "Overridden for this run by LEXSHIFT_STUBS". `run_demo.ps1` and `--real` remove that override and close the old server.

## Grade the evaluation round first (about 25 minutes, this is what gives you results to show)

The numbers for item 4 come from grades, and grades are made by a person (never by the tool). A small round is ready: **70 documents, the 10 dev queries, the top 5 of each system**.

1. Open **Ranking**, click **Open the judging workbench** (or go to `#/judging`), choose round **quick**, "You are **Judge 1**". Grade each document with the keys `0` `1` `2` (2 = relevant and good law for that query and date, 1 = relevant but the law changed or the case was doubted, 0 = irrelevant or overruled on the point). `n` jumps to the next ungraded one. Every click is saved.
2. When all 70 are graded:

```powershell
python -m eval.make_qrels --round quick --single-judge   # one judge: it says so in eval/judging/quick/agreement.md
python -m eval.run_ablation --split dev                  # B0 vs B1 vs Full on the dev queries
```

3. Reload **Ranking**: the results table appears (P@5, P@10, R@10, MAP, nDCG@10, harmful@10, judged@10 for B0, B1 and Full, with the by-type nDCG). A second person grading the same sheet as `judge2.csv` and `python -m eval.make_qrels --round quick` (without the flag) gives agreement and kappa, which is better; the single-judge file is a stop-gap and must be called one.
4. Say only what the table shows. The pool is the top 5, so **P@5** is fully judged; P@10 and nDCG@10 count unjudged documents below rank 5 as not relevant for every system alike. `harmful@10` stays `n/a` until `eval/gold_overrulings.csv` is written by hand (see the end).

## The script

| Time | On screen | Say (first person; change the words, keep the facts) |
|---|---|---|
| 0:00 to 0:15 | **Search** page (press Start searching), the formula strip | "I own M4: the ranking, the evaluation, and this interface. The final score is relevance from M1, plus statutory continuity from M2, plus treatment and authority from M3. Each is scaled to 0 to 1 and weighted, and the weights are in the strip." |
| 0:15 to 0:50 | Type `adultery as an offence`, Search. Click **BM25 only**, then **All four**. Open the second result and read its breakdown table and evidence sentence | "With BM25 alone the first result is *Sowmithri Vishnu* from 1985, which held adultery valid. With all four signals *Joseph Shine*, the 2018 five-judge decision that overruled it, is first, and *Sowmithri* drops. The table shows why: relevance 1.00 times 0.50, continuity 1.00, **treatment 0.10** because it was overruled, and the evidence is the sentence from *Joseph Shine*, 'the decisions in Sowmithri Vishnu and Revathi stand overruled'. This is real data: 4,819 judgments, and the treatment label came from an offline model run once and cached." |
| 0:50 to 1:05 | Run the chip `BNS 103` (offence date 2025-01-10); open a result with continuity 1.00 | "The offence date picks the code. A BNS 103 query finds IPC 302 judgments because the mapping says they are equivalent, and the *Why* column says so." |
| 1:05 to 1:20 | **Limitation.** Back to `adultery as an offence`, open the *Revathi* result and its second evidence item | "One limitation: treatment evidence can be wrong. The first item for *Revathi* is right. This second one is a mistake upstream: the passage is a list of cited cases and the case it names is *Frick India v. Union of India*, a different judgment, which the citation resolver linked to *Revathi* by name and year; the model then read 'held per incuriam' next to it. That is why we show the sentence and a confidence next to every signal and say it is not legal advice, so a reader can see the error. Also, only windows with words like overruled or doubted were sent to the model, so a treatment stated without those words is missed." |
| 1:20 to 1:50 | **Terminal** (zoom the font): `python -m app.cli "adultery as an offence" --verbose -k 3` | "This is the pipeline's intermediate output: the weights, then per result each signal as raw value, scaled value, weight and contribution, then the raw signals before scaling. BM25 is min-max scaled over the 100 candidates, authority too; continuity and health are already between 0 and 1." Then open `m4_rank/fusion.py` and point at `final = sum of weight times normalised signal` and the `heapq` top-K, and `common/config.yaml`, section `ranking`, for the three configurations B0, B1 and Full. |
| 1:50 to 2:15 | **Ranking** page: the weights table, the evaluation tiles, the results table | "We evaluate three systems: B0 is plain BM25, the baseline; B1 adds continuity; Full adds treatment and authority. The judged queries are 30, written by hand, 10 to tune on and 20 to report. Judges grade a pool made from the top results of every system, blind. [Read the table: P@5 and nDCG of B0 against Full, say which is higher and by how much, and that it is one judge on 10 dev queries.]" |

## What to say about the evaluation if asked

* **Baseline:** B0, BM25 only (M1's index, the same retrieval for all three systems, so differences come only from the added signals).
* **Metrics:** P@5, P@10, Recall@10, MAP, nDCG@10, and harmful@10 (the share of the top 10 that is a known-overruled case, lower is better).
* **Why a pool:** nobody can grade 4,819 judgments per query; we grade the union of what each system returns in its top results, and report `judged@10` so the reader sees how much of each list was judged.
* **Tuning:** `python -m eval.run_ablation --tune` reads the dev queries only; the test queries are run once, afterwards.
* **What is not claimed:** the dev result is from one judge and 10 queries, so it shows the machinery works and which way the signals push, not a final number. The full round (`eval/judging/round1`, 680 documents, two judges) is the one for the report.

## Optional: the gold overruling list (for harmful@10)

`eval/gold_overrulings.csv` has the columns `overruled_doc_id,overruling_doc_id,point,source,verified_by`. A person fills it by reading the judgments; `data/corpus_manifest.csv` has the `named_case`, `doctrine` and `role` columns and the doc ids of both ends of each doctrine (filter `role` = overruled or overruling), which is where to look the ids up. Do not paste rows you have not checked in the judgment text. With 6 or more verified rows `harmful@10` is computed on the next `run_ablation`.

## If something goes wrong on the day

| Situation | What to do |
|---|---|
| The page shows a stub banner | A switch is back to `true`: `Select-String -Path common\config.yaml -Pattern "^  (search\|statute\|health\|authority):"` should show four `false`. Or `LEXSHIFT_STUBS` is set in your shell: `Remove-Item Env:LEXSHIFT_STUBS`. |
| The first search takes 2 to 5 seconds | The first query loads the index; later ones are well under a second. Run one before you record. |
| Titles show as ids | `python -m app.docmeta`, then restart the server. |
| The results table is empty | No grades yet: do the grading section, then `run_ablation`. Say "results appear here once the judges finish" and show the Judging page instead; claim nothing. |

## Keys

`/` focuses the search box. In the judging workbench `0` `1` `2` grade, `j` and `k` move, `n` jumps to the next ungraded document.
