# Team workflow

## Branches

One long-lived branch per module owner, plus `main` for integration.

| Branch | Module | What it is for |
|---|---|---|
| `m1-index` | `m1_index/` | Corpus ingestion, text processing, inverted and positional index, query parser, BM25 and tf-idf, `search()` |
| `m2-statute` | `m2_statute/` | IPC to BNS (and key CrPC to BNSS) mapping, statute-citation extractor, query statute parser, `continuity()` |
| `m3-treatment` | `m3_treatment/` | Case-citation extraction and resolution, treatment classifier and gold set, citation graph, `health()` and `authority()` |
| `m4-rank` | `m4_rank/`, `eval/`, `app/` | Fusion ranking, ablations, judged queries and metrics, the demo, and the README, report and video drafts |
| `main` | everything | Integration. Always runnable. Never commit to it directly |

Each branch starts from the same skeleton on `main` (contracts, stubs, config, tests), so every owner can work and test
alone against the stubs.

## Rules

1. **Stay inside your module.** If you need a change in another module or in `common/`, ask the owner first.
2. **Contracts do not change quietly.** Signatures and file formats are in [CONTRACTS.md](CONTRACTS.md). A change needs a
   yes from every affected owner, then update `common/schema.py` and the doc in the same commit.
3. **Stubs first, real second.** Keep your stubbed switch `true` in `common/config.yaml` until your real function passes
   `python eval/smoke.py`; flip it to `false` in that same commit.
4. **Merge to `main` only when `python eval/smoke.py` and `pytest` both pass.** Merge `main` into your branch regularly
   so integration problems show up early.
5. **Never tune on test queries.** Weights are tuned on DEV only. Judged queries and the gold lists are written by hand, not
   generated.
6. **Nothing faked.** If something does not work yet, say so and show a real limitation. Never hard-code a result.
7. **Log decisions and AI use.** Non-obvious decisions go in [DECISIONS.md](../DECISIONS.md) with date and evidence;
   substantial AI-generated code, labels or text goes in [AI_USE_LOG.md](../AI_USE_LOG.md).
8. **Add a library to `requirements.txt` before you import it.**

## Commits

Small, working, one idea each, with a clear message, for example `m1: positional postings with phrase queries`.

## Daily rhythm (36-hour plan)

| Hours | What happens | Checkpoint |
|---|---|---|
| 0-3 | Agree schemas and `doc_id`; stubs run end to end; M1 ships the 200-document sample | Stubs run end to end |
| 3-12 | Everyone builds on the sample; M3 and M4 start gold labels and query writing | |
| 12 | Every module runs on the sample through the real interfaces | Checkpoint 1 |
| 12-22 | Full corpus; finish mappings, gold set and qrels; replace remaining stubs | |
| 22 | Feature freeze; full pipeline merged on `main` | Checkpoint 2 |
| 22-28 | Ablations B0 to full, weight tuning on dev, bug fixes, test-set numbers | |
| 28-36 | Report (8 pages or fewer), video (5-8 min), README checked on a clean machine, submit | |

Cut list if time runs short, in this order: tiered index, section-text similarity, point-level health, Streamlit UI (use
the CLI), type D queries.
