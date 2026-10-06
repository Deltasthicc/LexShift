# Report draft (prose that can be written before the evaluation exists)

Written 2026-10-07 from the code and the files in this repository, to be edited by the team. It follows
[REPORT_SKELETON.md](REPORT_SKELETON.md) (read that for the rules and the page budget). Three conventions:

* `<FILL: file>` is a result, a count or a fact that has to be taken from the named file after it has been generated. Nothing in
  the draft states a measured number that is not in a committed file.
* Sentences about what the system does describe the code. Sentences about how well it works are left for section 5, because no
  retrieval-quality result exists yet.
* The five rubric parts are marked so a reader can find them: relevance to the track, use of IR, evaluation, novelty, report quality.

---

## 1. Problem and track relevance

A lawyer or a student who searches Supreme Court judgments gets cases ranked by how well their text matches the query. A match can
still be unsafe to cite, for two reasons. First, the statute may have been replaced: the Bharatiya Nyaya Sanhita (BNS) replaced the Indian
Penal Code (IPC) on 1 July 2024, section numbers moved (murder is IPC 302 and BNS 103), collided (BNS 302 is not murder) or disappeared,
and both codes stay in force because the date of the offence decides which one applies. An IPC-era judgment is therefore not stale
merely for being old. Second, a later bench of equal or larger strength may have overruled, doubted or criticised the judgment.

LexShift is a vertical search engine for this one domain. It keeps ordinary relevance (BM25) and adds three signals that come from
the structure of the domain: statutory continuity between the code the query is about and the code the judgment interpreted, the
judicial treatment the judgment received from later benches, and the authority it carries in the citation graph. Each result
shows the evidence behind its status (the mapped section, the citing sentence) with a confidence. The output is treatment signals
with evidence, not legal advice, and the system never declares a judgment unusable. This is Track 6, search over a professional
domain's own structure: zones, metadata, citations and authority rather than flat text.
`<FILL: one sentence tying this to the track's stated theme, from the assignment text>`

**Prior work and what we did not check.** Indian Kanoon offers a "Reliability of a Precedent" feature and commercial tools mark
overruled cases. We have not verified whether they aggregate treatment over all citing cases or use it inside the ranking, and we
do not claim they do not. `<FILL: what the team actually looked at, with the date>`

**Papers and sources actually read.** `<FILL: exact titles and years; the planning documents name the HoH benchmark on outdated
information in retrieval (ACL 2025), IL-PCSR, LeCNet and the Stanford Overruling Dataset as candidates: list one only if a team
member read it>`

**Data.** Indian Supreme Court Judgments, AWS Open Data, licence CC-BY-4.0 (credited in the references).
`<FILL: size and years of the subset actually used, from data/README.md and DECISIONS.md>`

## 2. How IR was used

Figure 1 is `docs/figures/pipeline.png` (regenerate with `python -m eval.figures`). The ranking function is
`final(q, d) = w_r*rel(q,d) + w_s*cont(q,d) + w_h*health(d) + w_a*auth(d)`, each signal in [0, 1], the weights tuned on the dev
queries only.

| IR concept (course) | Where in the code | What it does here |
|---|---|---|
| Tokenisation, case folding, stop words, Porter stemming | `m1_index/tokenizer.py` | the index terms; NLTK supplies the stemmer and the stop-word list only |
| Inverted and positional index, document frequency | `m1_index/index.py` | postings with positions, so phrase and proximity queries can be answered |
| Zone index | `m1_index/zones.py`, `index.py` | facts, arguments and holding scored separately; the zone boundaries are a stated limitation (section 6) |
| Parametric index | `m1_index/searcher.py` | year and bench-size filters |
| Boolean, phrase and proximity queries; intersection by increasing document frequency | `m1_index/query_parser.py` | AND, OR, NOT, `/s`, `/p`, `/k`; checked against a brute-force scan on the sample |
| tf-idf (lnc.ltc), BM25, heap top-K | `m1_index/scoring.py` | the relevance signal `rel` and the candidate list |
| Normalisation to a controlled vocabulary, query expansion | `m2_statute/mapping.py`, `query_parser.py`, `matcher.py` | statute mentions become offence ids; a BNS query is expanded to the IPC section it replaces |
| Jaccard matching, proximity windows | `m3_treatment/resolver.py`, `windows.py` | resolves a cited case name to a corpus judgment; cuts the window around a citation |
| Citation graph, PageRank as a static quality score g(d) | `m3_treatment/graph.py`, `scores.py` | our own power iteration over positive and neutral citations, weighted by bench strength |
| Net score: relevance combined with static quality scores | `m4_rank/fusion.py` | the weighted sum above; the per-signal contributions are returned with every result |
| Score normalisation | `m4_rank/normalize.py` | min-max over the candidates for `rel` and `auth`; the calibrated signals pass through unchanged (DECISIONS.md D-006) |
| Pooling, graded relevance, P@k, Recall@k, MAP, nDCG, Cohen's kappa, bootstrap | `eval/pool.py`, `metrics.py`, `agreement.py`, `make_qrels.py`, `run_ablation.py` | the judging tool and the evaluation |

**Libraries and what they do in IR terms** (from `requirements.txt`): `nltk` (Porter stemmer and stop-word list, in the analysis
chain only; the index, BM25 and the Boolean engine are our own); `scikit-learn` (tf-idf and logistic regression for the offline treatment
baseline, never in the live path); `google-genai` (the offline few-shot treatment labels, cached, never imported at demo time);
`pyyaml` (configuration); `matplotlib` (the graphs); `pytest` (tests). The live path calls no network service and no language model.

**Real intermediate output** (paste from the tools, do not retype): postings and scores for a query (M1); the parsed statutes and the
continuity explanation (M2); a citation window with its label and confidence and the resulting health (M3); the per-signal
breakdown of one result (`python -m app.cli "<query>" --verbose`, or the Compare screen of `python -m app.server`).
`<FILL: one block per module, produced with every provider real>`

## 3. Beyond IR

The treatment classifier is trained and prompted offline and its outputs are frozen files. Citation windows are found only where a
specific earlier case is cited (so "objection overruled" is not read as overruling); a reversal on appeal is excluded; and a negative
label lowers a judgment's health only if the citing bench is at least as large as the cited bench. The statute layer is a typed
concordance (equivalent, modified punishment, modified elements, split, merged, omitted, new) whose weights feed the continuity
signal. Health, authority and continuity are then inputs to the ranking, not badges next to it.
`<FILL: gold-set size, the two labellers and their kappa, the model and prompt, per-class precision, recall and F1 (reports/classifier_f1.md), the number of concordance rows and how each was verified>`

## 4. Novelty and creativity

Against the obvious baseline (BM25 plus citation authority) and against existing tools, the contributions are: (1) judicial
treatment, weighted by bench strength and filtered for appeal history, used inside the ranking function; (2) cross-code statutory
continuity, so a BNS query can reach IPC-era precedents through a typed mapping, penalised in proportion to how much the law changed,
with an offence-date control; (3) evidence and a confidence on every result. **Each is a design claim until section 5 shows it:**
write only the ones the evaluation supports, and say plainly for each where it did not help.

## 5. Evaluation

**Setup (can be written now).** Three systems are compared: B0 (BM25 only), B1 (plus statutory continuity) and full (plus health and
authority). The judged set is written by hand, never generated: `<FILL: n>` queries (dev and test) of four types: A, a BNS query needing
an IPC precedent; B, changed or omitted provisions; C, doctrines with overruled cases; D, bare-number collisions. Relevance is graded
0, 1 or 2 by two judges over the union of the top-20 of every system, from blind sheets that show no score, rank or system name; agreement
is reported as percent agreement and Cohen's kappa and every disagreement is adjudicated by reading the judgment again. The weights are
tuned on the dev queries only, and the headline numbers are reported on the test queries. Metrics: P@5, Recall@10, MAP, nDCG@10 and
harmful@10 (judgments from the hand-verified overruling list in the top 10), with paired-bootstrap intervals against B0.

**Results.** Embed `eval/results/ablation_test.md` and `ablation_test.png`, the per-type table and `per_query_test.csv`. Do not retype
a number. State what the intervals allow with this few queries, where the full system helps, where it does not, and why.
`<FILL: eval/results/*>`

**Sanity checks and failures.** The three live checks of the video script (a BNS query that plain BM25 misses; the date changing the
ranking; a known-overruled case dropping with its evidence) and two or three real failures with the document and the reason.
`<FILL: the actual outputs>`

**Component evaluations.** M2 extractor precision on hand-checked judgments; M3 citation resolution rate and per-class F1; M1 against a
library BM25. `<FILL: from each module's reports>`

**Threats to validity (can be written now).** The judged set is small, so intervals are wide and a difference may be noise. Pooling bias:
documents outside the pool count as not relevant, so report `judged@10` for each system. The judges know what the system is for. The gold
overruling list is short and hand-made, and harmful@10 is only as complete as that list. The corpus is a subset (`<FILL: which>`).
Classifier errors propagate into health. The pooled documents were chosen by the systems being compared.

## 6. Limitations and next steps

State, from what was built and measured: the criminal-law subset only; English only; a small concordance (`<FILL: rows>` against a
planned 20 to 40) with the remaining sections unmapped; partial overruling, stayed provisions and pending larger-bench references are
not modelled; the zone boundaries in M1 are fixed paragraph numbers, so text outside every zone is invisible to BM25
(docs/INTEGRATION_REVIEW.md, M1 finding 9); citation resolution is incomplete (`<FILL: rate>`); no dense retrieval; the corpus size
(`<FILL>`) bounds what the evaluation can show.

Next steps if continued: more sections and the CrPC to BNSS and Evidence Act to BSA mappings; point-level health (penalise only on the
point the overruling discusses); a dense or hybrid retriever fused with BM25; learning to rank over the four signals; a larger judged
set and a second pooling round; a tiered index.

## 7. Work division and AI-use declaration

**Work division** (information only): M1 corpus and index; M2 statute layer; M3 citations and treatment; M4 fusion, evaluation, the
demo and the delivery. `<FILL: owner names; they are deliberately not stored in the repository>`

**AI-use declaration.** Claude Code (Claude Sonnet 5.5 for the shared skeleton and M4, Claude Opus 5.5 as M3's coding assistant) generated
code, tests, documents and tooling, listed entry by entry in `AI_USE_LOG.md`. The 30 candidate queries in `eval/examples` were AI-suggested as
a starting point and are not part of the judged set. A language model (`gemini-2.5-flash`) labels citation windows offline for the
treatment signal, with cached outputs, and is scored against a hand-labelled gold set. **Every relevance grade, the gold overruling list and the
treatment gold set are assigned by people.** `<FILL: which parts of the AI-generated code each member reviewed, from the Human review column; entries still marked pending must be reviewed or the declaration says so>`

## Appendix (outside the page limit)

Reproduction: `pip install -r requirements.txt`, `python -m nltk.downloader stopwords`, `python -m pytest`, `python eval/smoke.py`, the module
build commands, `python -m eval.pool`, `python -m eval.make_qrels`, `python -m eval.run_ablation --tune --split test`, `python -m eval.figures`,
`python -m eval.submission_check`. Also: the full judged query list, the weights file, the classifier prompt and the concordance table.
