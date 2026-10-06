# CLAUDE.md: LexShift

Good-law-aware search over Indian Supreme Court judgments (CSD358 IR hackathon, Track 6). Read this first, then
[PROJECT_BRIEF.md](PROJECT_BRIEF.md), [docs/CONTRACTS.md](docs/CONTRACTS.md), [DECISIONS.md](DECISIONS.md),
[AI_USE_LOG.md](AI_USE_LOG.md) and the README of the module you are working in. Then continue from the last commit.

## Ranking function

`final = w_r*rel + w_s*cont + w_h*health + w_a*auth`, each signal in [0, 1], weights tuned on DEV queries only.
Modules: **M1** `m1_index` (rel, `search()`), **M2** `m2_statute` (cont, `parse_query()`, `continuity()`),
**M3** `m3_treatment` (health and auth, `health()`, `authority()`), **M4** `m4_rank` + `eval/` + `app/` (fusion, evaluation,
demo). Branches: `m1-index`, `m2-statute`, `m3-treatment`, `m4-rank`; `main` is integration only.

## Non-negotiables

1. **Stay in your module.** Work on your own branch and inside your own folder. Ask before touching another module or
   `common/`. Signatures and file formats are contracts: do not change them without the affected owners' agreement.
2. **Nothing faked or hard-coded.** Every number, result and demo output comes from real code on real data. If something does
   not work yet, say so and show a real limitation. Stubs (`stubs/fixed.py`) exist only for integration and are always
   flagged; there is no silent fallback from a real function to a stub.
3. **IR is real.** Implement the IR pieces ourselves and explain them (inverted and positional index, zones, Boolean and
   proximity queries, tf-idf lnc.ltc, BM25, heap top-K, static quality score and net score). Libraries only where the brief
   allows, and record what each does in IR terms.
4. **Offline demo.** The live path runs on a laptop CPU, offline, no paid API, no live LLM. GPU and LLM work is offline and its
   outputs are frozen files.
5. **Never tune on test queries.** Judged queries, qrels and the gold overruling list are written by hand; never generate the
   labels the system is scored against.
6. **Wording.** Never write "dead law" or "bad law" in any output. Use "treatment signals", show evidence and a confidence,
   include the not-legal-advice note.
7. **Honesty about uncertainty.** Anything marked unverified in the brief is verified before it is built on, and the outcome is
   written to DECISIONS.md. Never state an unmeasured number.

## How to work

- Plan briefly, build in small testable steps, run the tests and the real pipeline after each step, and do not claim something
  works until you have run it. Commit small and often with a clear message.
- Boring and reproducible: Python 3.11, shared `requirements.txt` (add a library there before importing it), config in
  `common/config.yaml`, fixed seeds.
- Before merging to `main`: `python -m pytest` and `python eval/smoke.py` both pass. Flip your `stubs:` switch to `false` in the
  commit that makes your real function pass the smoke test.
- Record non-obvious decisions in DECISIONS.md (date, evidence). Append substantial AI-generated code, labels or text to
  AI_USE_LOG.md (what, where, which files).
- If a choice changes scope, grading risk or the legal framing, stop and ask rather than deciding silently.

## Commands

```bash
python -m pytest                 # unit tests
python eval/smoke.py             # contract + end-to-end check (merge gate)
LEXSHIFT_STUBS=none python eval/smoke.py   # same, with every provider real
python -m app.server             # the web interface at http://127.0.0.1:8765
python -m eval.conformance       # M1 to M3 artefacts and functions against the shared contracts
```

Windows note: stdout may not be UTF-8. Scripts that print non-ASCII should avoid assuming it.
