# Shared contracts

These are what make four people's work mergeable. They come from the Team Build Guide (6 October 2026), section 4,
and are executable in [`common/schema.py`](../common/schema.py) and [`common/contracts.py`](../common/contracts.py).
Agree changes in the group chat and get a yes from every affected owner before editing either file.

Items marked **proposed** were not fixed by the Guide; they are v0.1 proposals (see D-004 in
[DECISIONS.md](../DECISIONS.md)) that an owner may amend before their module merges to main.

## Conventions

| Thing | Rule |
|---|---|
| `doc_id` | The dataset's own case identifier, fixed in hour 0 by M1. In practice the dataset's file stem, `<year>_<volume>_<first page>_<last page>_<language>` (for example `2025_1_1_11_EN`); M3's resolver reads the year, volume and pages from it |
| `offence_id` | `OFF_<NAME>`, for example `OFF_MURDER` |
| Act codes | `IPC`, `BNS`, `CRPC`, `BNSS` (plus `UNKNOWN` for a bare section that could not be resolved) |
| Dates | ISO strings, `YYYY-MM-DD` in every file (not `02 January 2025`). BNS/BNSS apply to offences on or after 2024-07-01 |
| Files | UTF-8, LF line endings. JSON Lines for records, CSV/TSV for tables |
| Stubs first | Hours 0-3: every owner's functions exist as fixed-value stubs. Later only the body changes, never the signature |
| Python | 3.11. One shared `requirements.txt`; add a library there before importing it |

## Data files

| File | Owner | One record contains |
|---|---|---|
| `data/processed/judgments.jsonl` | M1 | `doc_id`, `title`, `date`, `bench_size`, `judges[]`, `reporter_citations[]`, `zones{headnote, facts, arguments, holding}`, `text` |
| `data/statute_map.csv` | M2 | `old_act`, `old_section`, `new_act`, `new_section`, `relation`, `weight`, `source`, `note` |
| `data/processed/doc_statutes.jsonl` | M2 | `doc_id`, `refs[{act, section, offence_id, count, zone}]` |
| `data/processed/citations.jsonl` | M3 | `citing_doc`, `cited_doc` (null if unresolved), `cited_raw`, `window` (the cited mention inside `[[ ]]`), `is_appeal_history`, `label`, `confidence`, `citing_bench`, `cited_bench`, `valid_negative` |
| `data/processed/doc_health.jsonl` | M3 | `doc_id`, `health`, `authority`, `evidence[{citing_doc, label, sentence}]` |
| `data/treatment_gold.csv` | M3 | `window_id`, `window`, `gold_label`, `labeller` |
| `eval/queries.jsonl` | M4 | `qid`, `text`, `offence_date`, `split` (dev or test), `type` (A to D) |
| `eval/qrels.tsv` | M4 | `qid`, `doc_id`, `grade` (0, 1, 2). **Proposed:** tab-separated with a header row |
| `eval/gold_overrulings.csv` | M4 | **Proposed:** `overruled_doc_id`, `overruling_doc_id`, `point`, `source`, `verified_by`. Hand-verified; used only for `harmful@k` |
| `eval/judging/<round>/` | M4 | **Proposed:** `sheet_template.csv` (`qid`, `query`, `type`, `offence_date`, `doc_id`, `title`, `date`, `bench_size`, `excerpt`, `grade`, `note`), `judge1.csv` and `judge2.csv` (the template with `grade` filled), `disagreements.csv`, `provenance.csv`, `agreement.md`, `summary.md`. See [eval/JUDGING_GUIDE.md](../eval/JUDGING_GUIDE.md) |
| `data/processed/doc_meta.jsonl` | M4 (derived, optional) | **Proposed:** `doc_id`, `title`, `date`, `bench_size`, so the demo can show titles without loading full text |

Vocabularies:

* `relation` in `statute_map.csv`: `equivalent | modified_punishment | modified_elements | split | merged | omitted | new`.
  Split and merge are many-to-many with direction: one row per (old, new) pair.
* `label` in `citations.jsonl`: `followed | distinguished | doubted | overruled | neutral`.
* `grade` in `qrels.tsv`: **2** relevant and good law; **1** relevant but the law materially changed or the precedent was
  criticised; **0** irrelevant, or overruled on the queried point.
* Query `type`: **A** BNS query needing an IPC precedent; **B** changed or omitted provisions; **C** doctrines with
  overruled cases; **D** bare-number collisions.

## Function signatures

```python
# M1  m1_index
search(query: str, k: int = 100, filters: dict | None = None) -> list[Hit]
#   Hit = {doc_id, rel, zone_scores}        rel is raw BM25 (unbounded); sorted best first

# M2  m2_statute
parse_query(query: str, offence_date: str | None = None) -> QueryStatutes
continuity(qs: QueryStatutes, doc_id: str) -> tuple[float, str]        # score in [0,1], explanation

# M3  m3_treatment
health(doc_id: str, offence_ids: list[str] | None = None) -> tuple[float, list[dict]]   # score in [0,1], evidence
authority(doc_id: str) -> float                                          # in [0,1]

# M4  m4_rank
rank(query: str, offence_date: str | None = None, k: int = 10, config: str = "full") -> list[Result]
#   Result = {doc_id, final, rel, cont, health, auth, explanation}
```

`QueryStatutes` (**proposed**): `query`, `offence_date`, `governing_act` (the code that applies, from an explicit act
or the offence date; `None` if unknown), `refs[StatuteRef]`, `notes[]`, and a derived `offence_ids`.

Evidence items (`{citing_doc, label, sentence}`) may carry **optional extra keys**. M3 adds `confidence`, `citing_bench` and, on
negative labels, `offence_ids` (the offences of the citing judgment, used for point-level health). Consumers must ignore keys
they do not know and may display the ones they do: the demo shows `confidence` and `citing_bench`. `sentence` is M3's citation
window (the citing sentence plus its neighbours, up to 1,500 characters), so it is shown in full.

`Result` carries four **additive** fields beyond the Guide's seven, which never replace a contract field:
`evidence` (for the demo), `raw` (signals before normalisation), `contributions` (weight x normalised value; sums to
`final`), `stubbed` (signals served by fixed-value stubs).

## How the stubs and the real modules are wired

[`common/providers.py`](../common/providers.py) picks, per group, the real function or the fixed-value stub in
[`stubs/fixed.py`](../stubs/fixed.py), from the `stubs:` switches in [`common/config.yaml`](../common/config.yaml)
(override per run with `LEXSHIFT_STUBS=none|all|search,health`).

| Switch | Real functions behind it | Owner |
|---|---|---|
| `search` | `m1_index.search` | M1 |
| `statute` | `m2_statute.parse_query`, `m2_statute.continuity` | M2 |
| `health` | `m3_treatment.health` | M3 |
| `authority` | `m3_treatment.authority` | M3 |

There is no automatic fallback from a real function to a stub. Flip your switch to `false` in the same commit that makes
your function pass `python eval/smoke.py`. Anything computed while a stub is active is flagged (`Result.stubbed`, the CLI
banner, and `eval/run_ablation.py` refuses to write results unless told `--allow-stubs`).

## Smoke test (the merge gate)

`python eval/smoke.py` checks the data files of every real provider against the schema and every provider against the
contract checkers in `common/contracts.py`, then `rank()` for `b0`, `b1` and `full`. Merge to `main` only after it passes
on the 200-document sample. It prints `[SKIP]` for what is not implemented yet and says so; a pass in stub mode proves
the interfaces line up and nothing about retrieval quality.
