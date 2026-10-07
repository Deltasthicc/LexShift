# Ablation results: dev split, 10 queries, depth 20

Generated 2026-10-07 17:02 UTC. Providers: search=real, statute=real, health=real, authority=real.

| config | weights rel/cont/health/auth | P@5 | P@10 | R@10 | MAP | nDCG@10 | harmful@10 | judged@10 |
|---|---|---|---|---|---|---|---|---|
| b0 | 1.00/0.00/0.00/0.00 | 0.740 | 0.440 | 0.810 | 0.709 | 0.727 | n/a | 0.580 |
| b1 | 0.70/0.30/0.00/0.00 | 0.760 | 0.470 | 0.866 | 0.712 | 0.736 | n/a | 0.590 |
| full | 0.50/0.20/0.20/0.10 | 0.800 | 0.480 | 0.883 | 0.729 | 0.732 | n/a | 0.600 |

Weights source: b0: starting weights (untuned placeholders); b1: starting weights (untuned placeholders); full: starting weights (untuned placeholders).
Relevant means grade >= 1; nDCG gain `exp`. Documents without a judgement count as grade 0; `judged@10` is the share of the top 10 that has one.
Gold overruling list: 0 rows (so harmful@10 is n/a).

## Difference from b0 (paired bootstrap over queries, 95% interval, 10000 resamples)

| config | metric | mean difference | 95% interval | queries |
|---|---|---|---|---|
| b1 | P@5 | +0.020 | [-0.040, +0.080] | 10 |
| b1 | nDCG@10 | +0.009 | [-0.097, +0.106] | 10 |
| b1 | harmful@10 | n/a | n/a | 0 |
| full | P@5 | +0.060 | [-0.020, +0.140] | 10 |
| full | nDCG@10 | +0.004 | [-0.114, +0.109] | 10 |
| full | harmful@10 | n/a | n/a | 0 |

With this few queries the interval is wide; read it as that reminder, not as a significance test.

## nDCG@10 by query type

| type | queries | b0 | b1 | full |
|---|---|---|---|---|
| A | 3 | 0.860 | 0.732 | 0.756 |
| B | 2 | 0.729 | 0.718 | 0.716 |
| C | 3 | 0.794 | 0.794 | 0.755 |
| D | 2 | 0.427 | 0.674 | 0.674 |
