# M2: statute layer (IPC to BNS continuity)

Branch: `m2-statute`. You work from M1's `judgments.jsonl` and hand M4 the `continuity()` signal.

**Goal.** Decide how much of a precedent's statutory basis carries over to the code that applies to the query.

## Status

**Done, apart from what only people can do.** `stubs.statute` is `false`; `python -m eval.conformance --module m2` passes all of its checks (9 of 9 statute forms read, a bare number takes its code from the
offence date, `doc_statutes.jsonl` covers every judgment of the corpus).

| Piece | State |
|---|---|
| `data/statute_map.csv`: 36 rows (21 IPC to BNS, 15 CrPC to BNSS, typed, weighted) | built; **only the sedition row (IPC 124A to BNS 152) was re-checked here**, against the PRS legislative brief on the Bharatiya Nyaya (Second) Sanhita, and it was wrong: it said `equivalent` 1.0, the brief says sedition is removed and clause 152 only "may have retained aspects" of it, so it is now `modified_elements` 0.5 with that source. The other 35 rows still cite just "MHA" and have to be verified in two official sources by a person (the MHA and PRS comparison tables) |
| Extractor (`extractor.py`) | reads `u/s 302 IPC`, `S. 302 I.P.C.`, `Section 482 Cr.P.C.`, `Sections 302, 307 and 34 of the Indian Penal Code`, `IPC 120-B`, `BNS 3(5)`, `the Code` (by the judgment's date); a bare `Section N` takes its act from the same judgment (see below); a section "of the NDPS Act" or another statute is not counted |
| Offence ids | now derived from the map's note, so one offence has one id across IPC and BNS and CrPC and BNSS (`OFF_MURDER` for IPC 302 and BNS 103, `OFF_ANTICIPATORY_BAIL` for CrPC 438 and BNSS 482): 12,441 of the 65,036 references carry one, it was 1,402 of 32,075 |
| Query parser (`query_parser.py`) | a bare section in a query takes its code from the offence date (a CrPC or BNSS number by the map is procedural, any other substantive); without an offence date it stays UNKNOWN and says so |
| `continuity()` (`matcher.py`) | sub-clauses are ignored when comparing (`BNS 3(5)` is the map's BNS 3); the map's relation wins over offence-id equality; no special case for `STUB-` ids any more |
| Tests | `m2_statute/tests/` (32) and `tests/test_robustness.py`; the old "quadratic extractor" expected failure is gone, the extractor is linear |

**How a bare `Section N` in a judgment gets its act** (module docstring of `extractor.py`): its family (procedural or substantive) is read off the statute map, and it takes the nearest explicit mention of that family in
the judgment; a number the map does not know takes an explicit act mentioned in the same paragraph within 400 characters; otherwise it stays UNKNOWN. **UNKNOWN is still 37.2% of the 190,518 mentions** (it was 68%):
mostly small section numbers of other statutes quoted without their name (`Section 7`, `Section 13`, `Section 27`) and IPC sections the map does not cover (149, 148, 300, 306, 323, 377). They never match a query, so
they only lose a little continuity, and `python -m m2_statute.extractor` prints the rate on every build.

**Not done, needs people:** the 50-judgment hand check of the extractor's precision (`python -m m2_statute.audit_sample` writes the sheet and scores it), the two-source verification of the other 35 map rows, and
a row or two more for provisions the queries touch that are not in the map (IPC 377 and 497, both gone from the BNS, would be `omitted`: say so only after reading the Act).

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
