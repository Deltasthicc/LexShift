# M3: citations and judicial treatment

Branch: `m3-treatment`. M3 reads M1's `judgments.jsonl` and hands M4 two of the four ranking signals: `health()` and
`authority()`.

**Goal.** Find how later judgments treated each earlier one (followed, distinguished, doubted, overruled or neutral),
and turn that into a health score and an authority score for every judgment, each backed by the sentence that supports it.

## Status

The pipeline is built, tested (`make m3-test`, 85 tests) and run end to end on M1's 468-judgment corpus:
`citations.jsonl` and `doc_health.jsonl` cover every judgment, and `health()` and `authority()` serve the live ranking
(`LEXSHIFT_STUBS=none python eval/smoke.py` passes with every provider real). All 269 citation windows that link two
corpus judgments are labelled by Gemini (`gemini-3.5-flash-lite`, zero-shot), run offline once and cached in
`data/llm_labels/m3_llm_labels.jsonl`, so rebuilding needs no API key and the demo never calls a model. On a larger
run that added Koushal, Navtej Singh Johar and Joseph Shine from the AWS bucket, `health(Koushal)` is 0.1, with the
reasoning sentence of the five-judge Navtej bench as its evidence (D-033).

The web interface shows every stage below on the **Treatment** page (`python -m app.server`, then Treatment, tabs 1 to 5).

## The corpus, by the numbers

Measured on the 468 judgments of 2024 and 2025 (`reports/resolution.md` and the Treatment page):

| Stage | Result |
|---|---|
| Mentions found | 22,861, of which 7,372 are a judgment's references to itself and are dropped |
| Citations kept | 15,489, in 421 judgments |
| By kind | case name 9,297 · later short form 4,070 · reporter citation 4,001 · full citation 3,856 · back-reference (supra) 1,637 |
| Resolved to a corpus judgment | 269 (1.7%): 201 by reporter citation, 68 by party name and year |
| Why the rest stay unresolved | they cite High Court, foreign or older Supreme Court judgments; 98% of the unresolved citations that carry a year cite one before 2024 |
| Appeal history, excluded | 133 |
| Labels on the 269 resolved windows | neutral 161 · followed 106 · distinguished 2 |
| Health | 1.0 for all 468 judgments: no valid negative treatment exists inside a two-year corpus |
| Authority | PageRank separates them; 53 judgments carry treatment evidence |
| Resolver spot check | 173 of 174 checkable reporter-citation links point to the judgment whose SCR citation the text gives |

## What M3 built

- **Text cleaning** (`text.py`): margin letters and running page heads are removed, so a header such as
  `[2024] 1 S.C.R. 404` is not read as a citation.
- **Citation extractor** (`citations.py`): SCR, SCC, SCC OnLine, AIR, SCALE, JT, Cri LJ and neutral (INSC) citations,
  and "X v. Y" case names. Five mention kinds: `full`, `cite`, `name`, `supra` ("Koushal (supra)") and `alias`
  ("the decision in Koushal"). The short forms point back to their full mention and inherit its resolution. This
  matters because courts mostly state treatment in a short form: "Koushal stands overruled".
- **Resolver** (`resolver.py`): links each mention to a `doc_id`. The order is reporter key, then SCR page range with
  a name check, then Jaccard similarity on party-name tokens plus the year. Unresolved mentions are kept with
  `cited_doc = null` and counted, never dropped; the rates go to `reports/resolution.md`.
- **Citation windows** (`windows.py`): the citing sentence plus one sentence either side (at most 1,500 characters),
  with the cited case marked `[[ ]]`. This window, not the whole judgment, is what gets classified.
- **Appeal-history filter** (`windows.py`): when the cited case is the judgment under appeal (same parties,
  "impugned judgment", "set aside"), the mention is tagged `is_appeal_history` and excluded. A reversal on appeal is
  not an overruling of a precedent.
- **Classifiers** (`classifier.py`): Gemini on the marked window, offline, every answer cached under a key that
  includes the model; and a tf-idf + logistic regression baseline (`make m3-citations-baseline` builds
  `citations.jsonl` from it instead).
- **Bench check** (`classifier.py`): a negative label is valid only if the citing bench is at least as large as the
  cited bench, because a smaller bench cannot overrule a larger one. Bench size comes from M1, or else from the coram
  line; when it is unknown the negative does not count, and it is still shown.
- **Scores** (`graph.py`, `scores.py`): `health(d)` is the strongest valid negative (overruled 0.1, doubted 0.6,
  otherwise 1.0, from `common/config.yaml`); `authority(d)` is PageRank by our own power iteration (damping 0.85) over
  followed and neutral edges, times a bench-size weight `log(1 + bench) / log(1 + 7)`, normalised to [0, 1]. At query
  time both are lookups in `doc_health.jsonl`.
- **Point-level health** (stretch, `scores.py`): with M2's offence ids, a negative lowers health only for queries about
  the offence the overruling discusses.
- **Gold-set tooling** (`gold.py`, [LABELLING_GUIDE.md](LABELLING_GUIDE.md)): a cue-word stratified sampler (50
  windows each from overrule, doubt, distinguish, follow and no-cue buckets), labelling sheets for two labellers (60
  windows shared), merge with adjudication, and Cohen's kappa.
- **Classifier evaluation** (`pipeline.py evaluate`): per-class precision, recall and F1 of the LLM and the baseline
  against the hand-labelled `data/treatment_gold.csv`, written to `reports/classifier_f1.md`. The labels people write
  are the only ones the classifiers are scored against.

## Pipeline commands

Everything runs offline; only `m3-label` uses the network. Each make target is a plain python command.

| Make target | Command | What it does |
|---|---|---|
| `make m3` | `python -m m3_treatment.pipeline build` | the whole pipeline: extract, citations, health, from the label cache |
| `make m3-extract` | `python -m m3_treatment.pipeline extract` | mentions, resolution and windows into `m3_mentions.jsonl`; writes `reports/resolution.md`; checks M1's fields first |
| `make m3-label-dry` | `python -m m3_treatment.pipeline label-llm --dry-run` | counts the windows to label and estimates requests and tokens, calls nothing |
| `make m3-label` | `python -m m3_treatment.pipeline label-llm` | Gemini labels into the cache; needs `GEMINI_API_KEY` (in `.env`); `LIMIT=N` caps new windows |
| `make build-citations` | `python -m m3_treatment.citations build` | extract, then `data/processed/citations.jsonl` from the labels |
| `make m3-citations-baseline` | `python -m m3_treatment.pipeline citations --labels baseline` | `citations.jsonl` labelled by the baseline instead |
| `make build-health` | `python -m m3_treatment.scores build` | PageRank and health into `data/processed/doc_health.jsonl` |
| `make m3-gold-sample` | `python -m m3_treatment.gold sample --n 250 --double 60` | labelling sheets in `data/labelling/` (`N=` and `DOUBLE=` to change the sizes) |
| `make m3-gold-merge` | `python -m m3_treatment.gold merge` | checks the sheets, Cohen's kappa, `disagreements.csv`, `data/treatment_gold.csv` (`ARGS=--allow-incomplete` merges the labelled rows so far) |
| `make m3-evaluate` | `python -m m3_treatment.pipeline evaluate` | per-class precision, recall and F1 into `reports/classifier_f1.md` |
| `make m3-test` | `python -m pytest tests/test_m3_*.py` | the 85 M3 unit tests |

`label-llm` is resumable: the cache is append-only, so an interrupted run continues where it stopped. Settings (model,
temperature, batch size, pacing, scope, thresholds) are under `m3_treatment:` in `common/config.yaml`.
`citations.jsonl` and `doc_health.jsonl` are not committed: after a fresh clone, or whenever M1 rebuilds
`judgments.jsonl`, run `make m3` (`health()` warns when they come from another corpus).

## Pipeline

```
judgments.jsonl
  -> clean_text (margin letters, running heads)                                     text.py
  -> mentions: full | cite | name | supra | alias                                   citations.py
  -> resolve: reporter key > SCR page range (+name) > party-name Jaccard + year     resolver.py
  -> window (sentence +/- 1, target marked [[ ]]) + appeal-history + self filter     windows.py
  -> label: Gemini (cached) or baseline; bench check -> valid_negative              classifier.py
  -> citations.jsonl
  -> PageRank over followed/neutral edges -> authority; strongest valid negative -> health     graph.py, pipeline.py
  -> doc_health.jsonl  ->  health(), authority()  (lookups only)                    scores.py
```

## M3 hands over

`citations.jsonl` (every mention with its window, label, confidence and bench sizes), `doc_health.jsonl`, the label
cache, `reports/resolution.md`, `health()`, `authority()`, and the gold-set and evaluation tooling.
Contract: [../docs/CONTRACTS.md](../docs/CONTRACTS.md). Decisions: D-016 to D-024 and D-033 in [../DECISIONS.md](../DECISIONS.md).

## IR concepts

- **Citation graph and PageRank as a static quality score g(d):** authority is a query-independent prior, computed
  once offline and added to the query-dependent relevance in the net score.
- **Proximity windows:** only the sentences around a specific cited case are classified, so a word like "overruled"
  in an unrelated objection is never read as treatment of this case.
- **Jaccard matching:** the resolver's fallback compares the sets of party-name tokens of the mention and of each
  candidate judgment, with the year as a filter.
- **Classifier evaluation:** per-class precision, recall and F1 against human labels, with Cohen's kappa for agreement
  between the two labellers.

## Design rules

No raw keyword matching for treatment; "set aside" on appeal is not an overruling; newer is not stronger (recency never
changes a score); a smaller bench cannot overrule a larger one. The LLM runs offline only and nothing in the live demo
calls one. The model and the prompts are declared in `AI_USE_LOG.md`. Name-only resolution is the step to watch: on
this corpus, links made by reporter citation agree with the cited SCR citation 173 times out of 174.
