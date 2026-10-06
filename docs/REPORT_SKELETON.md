# Report skeleton (PDF, 8 pages or fewer excluding references and appendix)

Follows the structure the assignment requires. Every `<FILL: ...>` is for the team to complete **from a file in this repository**.
[REPORT_DRAFT.md](REPORT_DRAFT.md) already holds the prose that does not depend on results; the pipeline diagram is `docs/figures/pipeline.png`
(`python -m eval.figures`).
Do not write a number that is not in `eval/results/`, a module's output file, or the logs: an unmeasured claim costs more than
a missing one. Where the system does not help, say so; the rubric asks for a judged comparison, not a win.

| Section | Pages | Rubric item it serves |
|---|---|---|
| 1 Problem and track relevance | 1 | Relevance to the track (5) |
| 2 How IR was used | 2 | Use of IR principles (30) |
| 3 Beyond IR | 0.5 | Use of IR principles (30) |
| 4 Novelty and creativity | 0.75 | Novelty (10) |
| 5 Evaluation | 2 | Evaluation (15) |
| 6 Limitations and next steps | 0.75 | Report quality (10) |
| 7 Work division and AI-use declaration | 0.5 | Required, not marked |

---

## 1. Problem and track relevance

* **The user need.** A lawyer or student searching Supreme Court precedents cannot tell whether a case that matches the query is
  still safe to cite. It goes stale in two ways: the statute it interpreted was replaced (the BNS replaced the IPC on
  1 July 2024; numbers moved, collided or disappeared, and both codes are live at once because the offence date decides), or a
  later bench of equal or larger strength overruled, doubted or criticised it.
* **Why this is Track 6.** A vertical search engine for one professional domain that uses the domain's structure (zones,
  metadata, citations, authority), not flat text. `<FILL: one sentence tying it to the track's stated research theme>`
* **Prior work, stated honestly.** Indian Kanoon has a free "Reliability of a Precedent" feature and paid tools flag overruled
  cases (cite the sources). We did not verify whether those aggregate across all citing cases or use treatment in ranking, and
  we say so. `<FILL: what the team actually checked on those tools, if anything>`
* **Papers and sources referred.** List **only what the team actually read**, with exact titles and years. Candidates named in
  the planning documents, to be confirmed before citing: the HoH benchmark on outdated information harming RAG (ACL 2025,
  arXiv 2503.04800); IL-PCSR (arXiv 2511.00268); LeCNet (JUST-NLP 2025); the Stanford Overruling Dataset; a BM25 and a PageRank
  reference; the course textbook chapters used for the index and scoring.
* **Dataset.** Indian Supreme Court Judgments, AWS Open Data, CC-BY-4.0 (credit it in the references).
  `<FILL: corpus size and subset actually used, from DECISIONS.md D-011 / OQ-2>`

## 2. How IR was used

* **Pipeline diagram.** Export the Mermaid diagram in [ARCHITECTURE.md](ARCHITECTURE.md) to an image (offline stage on the left,
  live demo on the right). Add the ranking function `final = w_r*rel + w_s*cont + w_h*health + w_a*auth`.
* **Table: IR concept, where in the code, why chosen.** Start from the table in [ARCHITECTURE.md](ARCHITECTURE.md) and update the
  *Status* column to what really shipped. One short row per concept: tokenisation and stemming, inverted and positional index,
  zone index, parametric index, Boolean and proximity queries (with the df-ordered intersection), phrase queries, tf-idf
  (lnc.ltc), BM25, heap top-K, normalisation to a controlled vocabulary and query expansion (BNS 103 reaches IPC 302), PageRank
  as a static quality score g(d), Jaccard matching, net score, pooling, MAP/nDCG/P@k.
* **Real intermediate output.** One short block each (from the CLI, not retyped): postings and scores for a query (M1), the
  statute mapping and continuity explanation (M2), a citation window with its label and confidence and the resulting health
  (M3), the per-signal breakdown of one result (M4, `python -m app.cli ... --verbose`).
* **Libraries and what they do in IR terms** (required by the assignment): for each library, one line, for example "rank_bm25:
  used only as a sanity check against our own BM25, never in the live path". `<FILL: from requirements.txt and the module READMEs>`

## 3. Beyond IR

* The treatment classifier: how citation windows were found, the gold set size, the labelling guide, the two labellers and
  their kappa, the model and prompts, caching, and **per-class** precision, recall and F1 (not accuracy alone; overruled is
  rare). `<FILL: table from M3>`
* The bench check (a negative treatment counts only if the citing bench is at least as large as the cited bench) and the
  appeal-history filter (a reversal on appeal is not an overruling).
* The typed concordance (equivalent, modified_punishment, modified_elements, split, merged, omitted, new), with every row
  verified in two sources.
* How each of these feeds the ranking (continuity, health and authority are signals inside the score).

## 4. Novelty and creativity

State what is new against **two** baselines: the obvious one (BM25 plus citation authority, which the assignment says scores low
on its own) and the existing tools. The contributions, each of which must be backed by the evaluation in section 5:

1. Aggregated judicial treatment, weighted by bench strength, used **inside** the ranking function rather than shown as a badge.
2. Cross-code statutory continuity: a BNS query retrieves IPC-era precedents through a typed mapping, penalising only in
   proportion to how much the law changed, with an offence-date toggle.
3. Every result carries its evidence sentences and a confidence; the system never declares a case "bad law".

Do not claim more than the evaluation shows.

## 5. Evaluation

* **Setup.** The judged set (`eval/queries.jsonl`): number of queries, the dev/test split, the four types, how they were written.
  The qrels: pooling depth and systems pooled, two judges, grade scale, agreement (`eval/judging/*/agreement.md`: percent
  agreement and kappa), how disagreements were resolved. Say that the judged data was written by people and that weights were
  tuned on dev only. `<FILL: numbers from check_data and agreement.md>`
* **Systems.** B0 BM25 only, B1 plus continuity, full (plus health and authority); the weights and where they came from
  (`common/weights_tuned.yaml`, tuned on dev).
* **Main table (test split).** Paste or embed `eval/results/ablation_test.md` and the chart `ablation_test.png`: P@5, Recall@10,
  MAP, nDCG@10, harmful@10 for each system. `<FILL: do not retype numbers; include the generated table>`
* **Differences with uncertainty.** The paired-bootstrap intervals against B0 from the same file; with this few queries the
  intervals are wide, so say what that implies.
* **By query type.** The per-type table: where full helps, where it does not (for example type D or the stayed-provision case).
* **Sanity checks** (real runs, from the video script): a BNS query that plain BM25 misses but the mapping finds; the offence-date
  toggle changing the ranking; a known-overruled case dropping with its evidence. `<FILL: the actual outputs>`
* **Component evaluations.** M2 extractor precision on the hand-checked judgments; M3 citation resolution rate and classifier
  per-class scores; M1 sanity comparison against a library BM25.
* **Threats to validity.** Pooling bias (unpooled documents count as non-relevant; report `judged@10`); a small judged set;
  judges who know the system's purpose; the gold overruling list is small and hand-made; the corpus subset; the classifier's
  errors propagate into health.
* **Failure analysis.** Two or three real failures, with the document, what the system did and why.

## 6. Limitations and next steps

Limitations, to be confirmed against what was built: criminal-law subset only; a small concordance (20 to 40 mapped sections)
with the rest unmapped; partial overruling and pending larger-bench references are not modelled; stayed provisions (for example
the operation of the sedition provision) are neither "overruled" nor healthy; OCR and PDF noise; unresolved citations
(`<FILL: rate>`); classifier errors; English only; no dense retrieval; a small evaluation set.

Roadmap if continued as the course project: more sections and the CrPC to BNSS and Evidence Act to BSA mappings; point-level
health (penalise only on the point the overruling discusses; the `offence_ids` argument already exists); a dense or hybrid
retriever fused with BM25; learning-to-rank over the four signals; a larger judged set and a second pooling round; a tiered
index.

## 7. Work division and AI-use declaration

* **Work division** (information only, no percentages): one or two lines per module (M1 corpus and index, M2 statute layer, M3
  citations and treatment, M4 fusion, evaluation and delivery) with the owner's name. Names are deliberately not stored in the
  repository: add them here at submission time.
* **AI-use declaration.** Start from [AI_USE_LOG.md](../AI_USE_LOG.md) and complete it: the coding assistant used (Claude Code,
  Claude Sonnet 5.5) and for what (repository skeleton, the M4 code and tests, the judging tools; other modules as logged); the
  LLM used for treatment labels (model, prompts, cached outputs) and which part of the pipeline it touches; that the example
  queries were AI-suggested and then reviewed; that **every relevance grade, the gold overruling list and the treatment gold
  set were assigned by people**; what was human-reviewed. `<FILL: from AI_USE_LOG.md, updated>`

## Appendix (does not count towards the page limit)

Reproduction commands (setup, the pipeline, `make smoke`, `make eval`), the full judged query list, the weights file, the
classifier prompt, and the concordance table.
