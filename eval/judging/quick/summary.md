# Pool summary: quick

Generated 2026-10-07 16:25 UTC. Providers: search=real, statute=real, health=real, authority=real.
Systems pooled: b0, b1, full; depth 5; shuffle seed 0.
Weights: b0 = 1.00/0.00/0.00/0.00 (rel/cont/health/auth); b1 = 0.70/0.30/0.00/0.00 (rel/cont/health/auth); full = 0.50/0.20/0.20/0.10 (rel/cont/health/auth).

| qid | split | type | pooled | in every system | in one system only | already judged | to judge now |
|---|---|---|---|---|---|---|---|
| dev01 | dev | A | 10 | 1 | 6 | 0 | 10 |
| dev02 | dev | A | 6 | 4 | 1 | 0 | 6 |
| dev03 | dev | A | 6 | 4 | 1 | 0 | 6 |
| dev04 | dev | B | 7 | 3 | 2 | 0 | 7 |
| dev05 | dev | B | 5 | 5 | 0 | 0 | 5 |
| dev06 | dev | C | 7 | 3 | 2 | 0 | 7 |
| dev07 | dev | C | 6 | 4 | 1 | 0 | 6 |
| dev08 | dev | C | 6 | 4 | 1 | 0 | 6 |
| dev09 | dev | D | 9 | 2 | 5 | 0 | 9 |
| dev10 | dev | D | 8 | 2 | 3 | 0 | 8 |

**70 documents to judge now** (70 pooled over 10 queries), so about 140 individual judgements for two judges.

How to read the overlap: if almost every document is in every system, the systems retrieve the same documents and differ only in ORDER (nDCG will show it, P@k will not). A large 'in one system only' column means the systems disagree about WHAT to retrieve, and the pool is doing real work.

Judging rules: [eval/JUDGING_GUIDE.md](../../JUDGING_GUIDE.md). Judges grade independently, from the sheet only.
