# M2: statute layer (IPC to BNS continuity)

Branch: `m2-statute`. You work from M1's `judgments.jsonl` and hand M4 the `continuity()` signal.

**Goal.** Decide how much of a precedent's statutory basis carries over to the code that applies to the query.

## What you build

- [ ] `data/statute_map.csv` for the 20-40 most-cited IPC offences plus key CrPC to BNSS bail sections. **Verify every row in
      two independent sources and record the source.** `mapping.py`
- [ ] Starting weights per relation (M4 tunes them; they live in `common/config.yaml`): equivalent 1.0, modified_punishment
      0.9, modified_elements 0.5, split / merged 0.7 per part, omitted 0.1, new 0. Store split/merge as many-to-many with
      direction
- [ ] Statute-citation extractor for judgments: handles `u/s 302/34 IPC`, `Section 302 read with 34`, `S. 302 I.P.C.`,
      `Sections 302 and 307 of the Indian Penal Code`. "The Code" is resolved by judgment date. Writes
      `doc_statutes.jsonl`. `extractor.py`
- [ ] Query statute parser: finds section mentions; picks the code from the offence date (before 1 July 2024 means IPC,
      otherwise BNS) or an explicit act; resolves collisions such as BNS 302 versus IPC 302. `query_parser.py`
- [ ] `continuity()`: best match between query and judgment offence ids, scored by the relation weight, with an explanation
      such as `BNS 103 -> IPC 302 (equivalent)`. `matcher.py`
- [ ] Stretch: pull IPC and BNS section texts and use cosine / Jaccard similarity to suggest the relation type automatically

## You hand over

`statute_map.csv`, `doc_statutes.jsonl`, `parse_query()`, `continuity()`. Contract:
[../docs/CONTRACTS.md](../docs/CONTRACTS.md). `QueryStatutes` is a v0.1 proposal: amend it early if you need more fields.

## IR concepts you explain in the video

Normalisation to a controlled vocabulary, query expansion, parametric filtering, and (stretch) Jaccard and cosine
similarity.

## Done when

Extractor precision is at least 0.9 on 50 hand-checked judgments, and `continuity()` gives sensible values for all 30
evaluation queries.

## Watch out for

Unverified mapping rows; bare section numbers with no act (keep an `UNKNOWN` bucket and report its rate); sections cited only
as "r/w 34". Unmapped sections stay unmapped: never guess. Design rule: old IPC judgments are not dead, so penalise only in
proportion to how much the law changed (examples from the brief: IPC 302 is BNS 103, and BNS 302 is a different offence).

## Hour 0-3 tasks

1. Commit a header-only `statute_map.csv` (already in place) and pick the first 10 rows to verify.
2. Make `parse_query()` and `continuity()` handle one section (IPC 302 / BNS 103) for real, then flip `stubs.statute` to
   `false` once `python eval/smoke.py` passes.
