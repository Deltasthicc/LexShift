# AI use log

Kept from hour 0. Append an entry whenever AI generates substantial code, data labels or text. This file becomes the
AI-use declaration in the report. Rules: say what was generated, where it landed, and what a human checked. Never let a model
generate the labels the system is scored against (judged queries, qrels, the gold overruling list, the treatment gold set).

| Date | Tool and model | What was generated | Where | Human review |
|---|---|---|---|---|
| 2026-10-06 | Claude Code (Claude Sonnet 5.5) | Repository skeleton from the Team Build Guide: shared dataclasses and contract checkers, config, fixed-value stubs, provider wiring, module skeletons (signatures and docstrings only, no logic), module READMEs, docs, Makefile, unit tests, smoke test | `common/`, `stubs/`, `m1_index/` to `m4_rank/` (skeletons), `eval/smoke.py`, `docs/`, `tests/`, `README.md`, `CLAUDE.md`, `DECISIONS.md` | Pending: the M4 owner reviews the whole skeleton; each other owner reviews their module's skeleton before building on it. Update this cell when done |
| 2026-10-06 | Claude Code (Claude Sonnet 5.5) | Sanitised copy of the project brief (retitled, team names removed, precedence note added) | `PROJECT_BRIEF.md` | Content otherwise unchanged from the team's original brief |
