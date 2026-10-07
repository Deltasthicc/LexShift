# M4 demo: 90 seconds

What M4 owns and what to show: **fusion ranking** (four signals, one score, every number explained), **evaluation** (how we will know it helps)
and **the interface** that makes both visible. Do not demo the other modules' internals: each owner shows their own part (M1 has the
Index page, `#/index`). Everything below is a live screen; no number is read from this file.

## Before you start (1 minute, not part of the 90 seconds)

```bash
python -m m1_index.index build        # once on a fresh clone, about 20 seconds
python -m eval.submission_check       # what is real and what is still a stub
python -m app.server --open           # add LEXSHIFT_STUBS=... if a module is not ready, see below
```

The page always shows a **stub banner** when any signal is a stand-in. Do not hide it and do not read a stand-in as a result: say
"health and authority are placeholders until M3's run is merged". If every provider is real, the banner is gone and you can say
what the treatment signal shows.

Queries that work on the current corpus (200 judgments, all 2025): `punishment for murder under section 103 BNS` with offence date
`2025-01-10`, and `section 103` with the two dates `2020-06-01` and `2025-02-01`. Avoid typing `BNS 103` or `IPC 302` on their own:
M2's pushed parser does not read an act followed by a bare number (docs/INTEGRATION_REVIEW.md, M2 finding 9).

## The script

| Time | On screen | Say |
|---|---|---|
| 0:00 to 0:10 | Search page, query box | "M4 combines four signals into one ranking and measures whether that beats plain BM25. The formula is on the Method page: relevance, continuity, treatment and authority, each between 0 and 1." |
| 0:10 to 0:35 | Run `punishment for murder under section 103 BNS`, date 2025-01-10. Point at one result's four bars, then open **Score breakdown** | "Every result shows its four contributions and why. Here continuity says BNS 103 maps to IPC 302 as an equivalent provision, so an IPC-era judgment is not penalised for its age. Nothing here is hard-coded: it is the real search, the real statute parser and the fusion function." |
| 0:35 to 0:55 | Click the ranking ladder: **Relevance**, then **+ Continuity**, then **+ Treatment, authority** | "This is the ablation we evaluate: B0, B1 and full. Watch the list re-order as each signal is added; that movement is exactly what the evaluation measures." |
| 0:55 to 1:10 | Run `section 103` with 2020-06-01, then with 2025-02-01 (or press `m` for Compare) | "The same words, two offence dates, two different codes: the date decides between IPC 103 and BNS 103, and the ranking changes with it." |
| 1:10 to 1:30 | **Evaluation** page, then **Judging** | "We compare B0, B1 and full on 30 hand-written queries, 10 to tune on and 20 to report, with P@5, Recall@10, MAP, nDCG@10 and harmful@10. Grades come from two judges on blind sheets (this screen: no scores, no system names), with agreement reported as kappa. Weights are tuned on the 10 dev queries only. The result table appears here once grading is done; until then this page says so rather than showing a number." |

## If something is not ready on the day

| Situation | What to do |
|---|---|
| Statute is still a stub, or M2's real function errors on the map | The banner names it. Skip the continuity sentence, show the BM25-only list and the formula, and say continuity is the next signal in. Do not claim a result. |
| Health and authority are stubs | Say so in one sentence. Show that the two bars exist and are labelled stand-in. Do not open the evidence drawer as if it were real. |
| Everything is real | Search a doctrine query such as `consensual same-sex relations section 377` (only once the older judgments are in the corpus), open the evidence of a result with lowered treatment, and let the reader jump to the sentence. |
| The evaluation table exists | Replace the last row: show `eval/results/ablation_test.md` and say the one number you can defend, with its interval. |

## Keys that save time on stage

`/` focus the search box, `1` `2` `3` switch B0, B1, full, `m` Compare, `j` and `k` move between results, `e` open the score breakdown, `?` list all.
