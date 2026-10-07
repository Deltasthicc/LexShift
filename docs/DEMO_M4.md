# M4 demo: 90 seconds

What M4 owns and what to show: **fusion ranking** (four signals, one score, every number explained), **evaluation** (how we will know it helps) and **judging** (how the grades that evaluation
needs get made). The other modules' internals are shown by their owners on their own pages (Index M1, Statutes M2, Treatment M3). Everything below is a live screen; no number is read from this file.

## Before you start (1 minute, not part of the 90 seconds)

```bash
make data                       # a fresh clone only: unpack the corpus, titles, search index, statute file (about 3 minutes, no network)
python -m eval.submission_check # what is real and what is still a stand-in
python -m app.server --open     # http://127.0.0.1:8765
```

The page shows a **stand-in banner** while any signal is a stand-in (today: Treatment and Authority, because M3's labelling run for the 4,819-judgment corpus needs an API key). Do not hide it and do not
read a stand-in as a result: say "treatment and authority are placeholders until M3's labelling run is merged; relevance and continuity are real". If every provider is real the banner is gone.

## The script (about 90 seconds)

| Time | On screen | Say |
|---|---|---|
| 0:00 to 0:10 | **Search** page, the formula strip under the search box | "M4 combines four signals into one ranking and measures whether that beats plain BM25. Relevance from M1, continuity from M2, treatment and authority from M3, each scaled to 0 to 1 and weighted." |
| 0:10 to 0:35 | Type `punishment for murder under section 103 BNS`, offence date `2025-01-10`, Search. Open the second result (a judgment that continuity scored 1.00) and read its breakdown table | "Every result shows its four contributions and why. Here continuity says BNS 103 maps to IPC 302 as an equivalent, because the offence date picks the BNS and this precedent was decided under the IPC. That is the sentence in the *Why* column, and it comes from the mapping table, not from a model." |
| 0:35 to 0:55 | Click the three segments above the list: **BM25 only**, **+ Continuity**, **All four** | "This is the ablation we evaluate: B0, B1 and full. Watch the list re-order as each signal is added; the arrows say how far each judgment moved against plain BM25. That movement is what the evaluation measures." |
| 0:55 to 1:10 | Run the chips `IPC 302` (2020) and then `BNS 103` (2025) | "The same offence under two codes. The offence date selects the code, and continuity ties them together through the typed mapping, so an IPC-era precedent is still found for a BNS query, and is down-weighted only in proportion to how much the law changed." |
| 1:10 to 1:30 | **Ranking** page (weights, evaluation data), then **Open the judging workbench** | "We compare B0, B1 and full on 30 hand-written queries, 10 to tune the weights on and 20 to report, with P@5, recall, MAP, nDCG@10 and harmful@10. The grades come from two judges on blind sheets: no scores, ranks or system names. The first round is pooled from the real systems, 680 documents; the tables appear here once the two judges are done. Nothing is claimed before that." |

## What is honest to say if asked

* **"Is relevance good?"** Not measured yet: there are no grades. The ranking is real code on the real 4,819-judgment corpus; its quality is what the judging round will measure. A visible limitation: for a query that is only
  `BNS 103`, BM25 puts a 2025 judgment that mentions "BNS" very often first, and only continuity pulls the IPC 302 precedents up. The ladder shows that.
* **"Why is treatment a stand-in?"** M3's code and 160,705 extracted mentions are real; the labels for the new corpus need one offline Gemini run (1,010 windows). Until then health defaults to 1.0 for everyone and is flagged.
* **"Did you tune on the test queries?"** No: `python -m eval.run_ablation --tune` reads the dev split only, and the test split is run once, after.

## If something is not ready on the day

| Situation | What to do |
|---|---|
| Statute is a stand-in or errors on the map | The banner names it. Skip the continuity sentence, show the BM25-only list and the formula, and say continuity is the next signal in. Do not claim a result. |
| Health and authority are stand-ins (today) | Say so in one sentence. The two bars exist and are labelled stand-in. Do not open evidence as if it were real. |
| Everything is real | Search `consensual same-sex relations section 377` (the corpus holds both *Koushal* and *Navtej*), open the evidence of a result with lowered treatment, and let the reader jump to the sentence. |
| The evaluation table exists | Replace the last row: show `eval/results/ablation_test.md` and say the one number you can defend, with its interval. |

## Keys

`/` focuses the search box; in the judging workbench `0` `1` `2` grade, `j` and `k` move, `n` jumps to the next ungraded document.
