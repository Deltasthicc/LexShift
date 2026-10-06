# PROJECT BRIEF — LexShift: Precedential-Health-Aware Indian Supreme Court Search

**Course:** CSD358 Information Retrieval, Shiv Nadar University — Midsem IR Hackathon (25% of course grade)
**Track:** T6 — Vertical search for law, finance or science
**Team:** 4 members. The whole team agreed on Track 6.
**Window:** 36 hours from track announcement. A working partial implementation is enough. The project may continue as the CSD358 course project, so the hackathon version is milestone 1.

> Status legend used below: ✅ = checked against a source during planning; ⚠️ = NOT verified, check it first.
>
> **Precedence.** This brief fixes the goal, rubric, constraints, evaluation ideas and risks. Where it disagrees with the
> Team Build Guide of 6 October 2026 on repository layout, module ownership, function signatures, file formats or the
> scoring formula, **the Build Guide wins** (written up in [docs/CONTRACTS.md](docs/CONTRACTS.md); the reconciliation is
> decision D-001 in [DECISIONS.md](DECISIONS.md)). Sections 9 and 11 below are kept for history and are superseded on those points.

---

## 1. One-paragraph pitch

Lawyers and students cannot easily tell whether a precedent is still safe to cite. Two things erode a precedent: (a) **statutory change** — the IPC/CrPC were replaced by the BNS/BNSS on 1 July 2024, so section numbers moved and sometimes the substance changed; (b) **judicial treatment** — later benches follow, distinguish, criticise, doubt or overrule earlier cases. We build a search engine over Supreme Court judgments where this "precedential health" is **part of the ranking function**, not a warning badge bolted on afterwards.

```
Final score(q, d) = textual_relevance(q, d)      # BM25 / tf-idf cosine (+ optional dense)
                  + statutory_continuity(q, d)   # typed IPC<->BNS mapping
                  + judicial_treatment(d)        # later-case treatment x bench strength x recency
```

Every result shows the score components and the **evidence** behind its status (the statute mapping type; the actual sentences from later judgments), with a confidence value. The system never declares a case "bad law".

## 2. Why this is a defensible T6 + novelty story (read before designing anything)

The assignment's rubric: IR principles 30, Novelty 10, Working system 20, Evaluation 15, Relevance to track 5, Report 10, Video 10. It warns that "building [a sample idea] exactly as written will score low on novelty" — the sample T6 idea is "a legal precedent finder that ranks judgments by tf-idf plus citation authority". So plain BM25 + PageRank is explicitly NOT enough.

Corrections we already made to the original idea (do not regress on these):

1. **Indian Kanoon already has a free "Reliability of a Precedent" feature** ✅ that labels cited text as "Relied by Party / Accepted by Court / Negatively viewed by Court / No clear sentiment" (indiankanoon.org/free_features/). Paid tools such as SCC Online also flag overruled cases. So a warning badge is NOT novel. Our novelty must be: (i) per-precedent **aggregation** of treatment across all later citers, weighted by bench strength and recency, **used inside ranking**; (ii) **cross-code statutory continuity** (query by BNS section, retrieve IPC-era precedents, down-weight only where the law actually changed); (iii) showing evidence + confidence. ⚠️ We did not verify whether Indian Kanoon's feature aggregates across citers or feeds ranking, nor its court coverage — cite it as prior work in the report and compare honestly.
2. **IPC -> BNS does not make an IPC judgment stale.** BNS commenced 1 July 2024 ✅, but §358 BNS (and §531(2)(a) BNSS) preserve liability for offences committed earlier, so pre-July-2024 offences are still tried under the IPC ✅ (Bar & Bench summary of Vijay Sharma v. State of Rajasthan, Rajasthan HC). Many BNS provisions are re-numbered copies, so earlier interpretations still apply. => model "statutory continuity", never "dead law".
3. **No single "offence ID" per section.** The mapping is typed: `EQUIVALENT / MODIFIED / SPLIT_MERGED / REPEALED / NEW` ✅. Examples ✅: IPC 302 -> BNS 103 (and BNS 302 is a *different* offence, religious sentiments); IPC 34 -> BNS 3(5); IPC 120B -> BNS 61; rape IPC 375–376 split into BNS 63/64; sedition IPC 124A replaced by a different offence BNS 152; adultery 497, attempt to suicide 309 and 377 removed; new offences such as mob lynching BNS 103(2), organised crime 111, terrorism 113.
4. **A later case is not automatically stronger law.** Distinguish followed / distinguished / criticised / doubted / explicitly overruled / merely referred, and use bench strength (a 3-judge bench cannot be overruled by a 2-judge bench; a smaller bench disagreeing should be "doubted / refer to larger bench", not "overruled").
5. **Precedential health is a ranking feature**, so the contribution is genuinely IR.

## 3. Hard constraints

- **Hardware:** RTX 5090 Ti is for **offline** work only (training the treatment classifier, computing embeddings, precomputing edge labels and indexes). The **live demo runs on a mid-range laptop CPU**, offline, no internet, no paid API, no live LLM. The professors may run it themselves.
- **No faked demo.** "A demo that is faked, hard-coded or shown only as screenshots earns 0 for working system." Everything shown must come from real code on real inputs. Precomputed artefacts are fine (they are the product of the offline pipeline); canned results are not.
- **Frontend is not graded.** CLI, Jupyter, Streamlit or web earn the same marks. Do not spend the 36 hours on UI. A thin Streamlit page or CLI that exposes intermediate outputs is enough.
- **IR must be real, not a label.** Implement and show: inverted index with postings, positional index/phrase queries, zone index, parametric index, Boolean and proximity queries, tf-idf/cosine, BM25, heap-based top-K, static quality score g(d) and net score. Libraries are allowed but the report must explain them in IR terms. Extras that earn points: BM25 ✅, dense retrieval, learning-to-rank, PageRank ✅ (all named as bonus in the brief).
- **Corpus must be big enough that ranking matters** (or the small size must be justified).
- **Data ethics:** respect robots.txt, add delays if crawling, no personal data collection, credit every dataset. Prefer the open AWS dataset over crawling Indian Kanoon.
- **No copying** of existing GitHub projects/papers/blogs; using libraries, public datasets and AI help is fine **when declared**.
- **AI use is allowed and not penalised**, including Claude Code, but must be declared in the report. Keep an `AI_USE_LOG.md` from hour 0.
- **Legal disclaimer:** output is "treatment signals with evidence", not legal advice.

## 4. Deliverables (one submission per team via the course form)

1. **GitHub repo + README:** setup, how to run, where the data comes from, what works and what is still planned.
2. **Demo video, 5–8 min, unlisted YouTube/Drive, NO slides.** Must show: (1) problem + why T6 (<= 1 min); (2) system running end to end on real queries, including at least one limitation; (3) the pipeline with real intermediate output (postings, weights, scores), not only the final screen; (4) evaluation: P/R/P@k vs a baseline; (5) each member explaining the component they own.
3. **Report PDF, <= 8 pages** excluding references/appendix: (1) problem + track relevance + papers referred; (2) how IR was used, where in the code, why, with a pipeline diagram; (3) beyond-IR techniques; (4) novelty vs obvious baseline and existing tools; (5) evaluation on a small judged query set with P/R/P@k and a baseline comparison (graphs/tables); (6) limitations + roadmap; (7) work division (info only, no marks) + AI-use declaration.

## 5. Data

| Resource | What we know | Use |
|---|---|---|
| **AWS Open Data: Indian Supreme Court Judgments** (registry.opendata.aws/indian-supreme-court-judgments/) | ✅ 1950–2025, CC-BY-4.0, bi-monthly updates, raw metadata JSON + structured **parquet**, judgments as zips in English and regional languages, public S3 bucket (no AWS account needed). ⚠️ Judgment count, text format (PDF vs text), field list, exact bucket name/CLI command — read the registry page and inspect. | **Primary corpus.** |
| IL-PCSR (Exploration-Lab/IL-PCSR on HF) | Reported: 6,271 queries, 936 statutes, 3,183 precedents, train/dev/test, has jurisdiction/date/rhetorical_roles fields, gated, CC-BY-NC-SA 4.0 (⚠️ these field/licence details came from a reviewer, verify). Queries are full judgments with citations masked. | Optional: extra judged relevance data / rhetorical-role (zone) ideas. Too small to be the main corpus. |
| LeCNet (JUST-NLP 2025) | ✅ 26,308 case nodes, 67,108 citation edges, Indian judiciary; **no treatment/overruled labels**. ⚠️ Court coverage and hosting unclear. | Optional citation-graph sanity check. |
| ILDC (35k SC cases, Malik et al. ACL 2021) | Named in the assignment as sample data. ⚠️ Whether it has a citation graph is unverified. | Fallback corpus. |
| Stanford Overruling Dataset | ✅ 2,400 US sentences, binary overruling vs not (attorney-annotated, Casetext). | Auxiliary signal for the classifier only; domain shift to Indian text is large. |
| IPC<->BNS concordance | ✅ Official comparison tables exist (MHA Bharatiya Nyaya Sanhita text; PRS Legislative Research brief). Popular summaries: lawsikho.com/blog/ipc-to-bns-conversion. ⚠️ No clean machine-readable dataset was found. | Build a typed mapping table ourselves (see 7.3), starting from the most-cited sections in the corpus. |

## 6. Architecture

```
OFFLINE (5090 Ti + CPU)                                    LIVE DEMO (laptop CPU, offline)
raw SC judgments (parquet + text)                          query (free text / Boolean / "BNS 103" / filters)
  -> clean text, zones, metadata                              -> query parser (Boolean, proximity, phrase, section refs)
  -> statute citation extractor (act-aware)                   -> candidate gen: inverted index (BM25 + tf-idf)
  -> case citation extractor + resolver (cite graph)                              [+ optional dense via precomputed vectors]
  -> treatment classifier on citing contexts (GPU)            -> concordance expansion (IPC<->BNS) + continuity weight
  -> per-precedent health score h(d)                          -> health score lookup h(d)
  -> positional/zone/parametric indexes, champion lists       -> net score fusion + top-K heap
  -> (optional) embeddings                                    -> result view: score breakdown + evidence sentences
  => frozen artefacts in artifacts/ (target < ~2 GB)
```

## 7. Component specs

### 7.1 Document model and indexes (IR principles: "what is a document", tokenisation, postings)
- Document = one judgment. Parse into zones where possible: header/metadata, facts, issues, reasoning/analysis, held/order. Heuristic headings (e.g. "JUDGMENT", "ORDER", "Held"). ⚠️ Inspect the real text before committing to zone rules.
- Fields (parametric index): year, court/bench strength (number of judges), judges, citation string(s), statutes cited (normalised IDs), cases cited (resolved doc IDs).
- Build from scratch (to show the mechanics): dictionary + positional postings, case folding, legal-aware tokenisation (keep "302", "Sec.", "u/s", "v."), stop words, optional stemming/lemmatisation comparison, Boolean AND/OR/NOT with postings intersection ordered by increasing df, proximity ("murder /5 intention"), phrase queries via positional index (exact statute names), tf-idf with lnc.ltc, BM25, heap top-K, index elimination or champion lists/tiered index (e.g. head-note/held zone as tier 1).
- Also compare against a library baseline (e.g. rank_bm25) as a sanity check, and explain what it does in IR terms.

### 7.2 Statute-citation extraction (act-aware)
- Handle patterns such as "Section 302 IPC", "u/s 302 of the Indian Penal Code", "ss. 302/34 IPC", "Sections 302 and 34", "S. 103 BNS", "Section 482 CrPC", "Section 528 BNSS". Normalise act names via an alias dictionary (IPC / I.P.C. / Indian Penal Code; BNS / Bharatiya Nyaya Sanhita; CrPC / Cr.P.C.; BNSS; Evidence Act / BSA).
- **Disambiguate bare "Section N"** from nearby act mentions; keep an `act = UNKNOWN` bucket and report its rate. BNS 103 != IPC 103 != BNS 302.
- Scope for v1: **IPC <-> BNS only** (optionally CrPC <-> BNSS, Evidence Act <-> BSA as roadmap).

### 7.3 Typed concordance and statutory continuity
- Table rows: `(ipc_section, bns_section(s), change_type, note, source)` with `change_type` in `EQUIVALENT | MODIFIED | SPLIT_MERGED | REPEALED | NEW`.
- Prioritise by corpus frequency: build and hand-verify the top ~100–150 most-cited IPC sections first; mark the rest `UNMAPPED` rather than guessing.
- Continuity weight c in [0,1] for a (query statute, precedent statute) pair. Starting point (tunable on the dev queries): EQUIVALENT = 1.0; MODIFIED = text similarity (cosine/BM25) between the two section texts, clipped; SPLIT_MERGED ~ 0.8–0.9; REPEALED/NEW = 0 for cross-code matching.
- **Offence-date context toggle:** if the user says the offence was committed before 1 July 2024, IPC-era precedents get full continuity (IPC still governs); if after, continuity comes from the mapping. This directly encodes the §358 point and is a good demo moment.
- Query behaviour: a "BNS 103" query expands to IPC 302 via the concordance and retrieves both sets; the plain-BM25 baseline should fail on this (the text says "302").

### 7.4 Case-citation graph
- Extract citations (SCC / AIR / SCR / INSC neutral citations / "X v. Y"), resolve to corpus doc IDs, and store edges with citing-sentence context windows. ⚠️ Metadata may already carry citation strings and cites/cited-by; inspect before writing regexes. Report the **resolution rate**; unresolved citations must not be silently dropped.

### 7.5 Judicial-treatment classifier (the GPU part, offline)
- Input: citing-context sentences around the mention of the cited case. Labels: `FOLLOWED/APPLIED`, `DISTINGUISHED`, `CRITICISED/DOUBTED`, `OVERRULED` (explicit), `NEUTRAL/REFERRED`.
- Pipeline: (1) high-precision rule patterns (lexicon of "overruled", "per incuriam", "no longer good law", "not good law", "doubted", "distinguished", "followed", "relied upon", "approved") **bound to the cited case's name/citation within the same or adjacent sentence**; (2) exclude non-precedent uses — "objection overruled", "contention overruled", orders overruling a trial-court ruling, "overruled" as a verb about a party's argument; handle negation ("was not overruled", "cannot be said to be overruled"); (3) hand-label ~500–1000 edges across classes; (4) fine-tune a small encoder offline on the 5090 Ti (InLegalBERT / legal-bert / DeBERTa-v3-small / MiniLM — choose by quick pilot); optionally use rule output as weak labels and the Stanford overruling set as auxiliary data; (5) **precompute labels + confidence for all edges** and ship them (no model needed live; optionally export ONNX for the live "explain this edge" feature).
- Output per edge: label, confidence, the evidence sentence(s). Overruling must be tied to **bench strength** (smaller bench "overruling" a larger one is flagged, not trusted).

### 7.6 Precedential health score h(d) (static quality score g(d) in course terms)
- Interpretable and bounded, e.g. `h(d) = authority(d) * (1 - negative(d))` with:
  - `authority` = weighted count (or PageRank — bonus) of FOLLOWED/APPLIED citers, weight = bench strength x recency x confidence;
  - `negative` = weighted share of OVERRULED/CRITICISED/DOUBTED citers (OVERRULED > DOUBTED > CRITICISED), same weights, capped to avoid one weak citer zeroing a case.
- Keep the formula in one config file; tune lambda weights on the dev queries; report ablations. Edge cases to show honestly: partial overruling (on one point only), overruling pending a larger-bench reference, provisions stayed rather than struck down.

### 7.7 Ranking and output
- `final = lambda1 * norm(relevance) + lambda2 * continuity + lambda3 * health` (normalise relevance, e.g. min-max or reciprocal-rank fusion over top-N candidates). Optional: dense similarity from precomputed embeddings fused with BM25; learning-to-rank as a bonus if time permits.
- Result card: title/citation, court, year, bench, per-component score bar, statute mapping type(s), top evidence sentences from later judgments (with links to the citing case), confidence, and the limitation note.

## 8. Evaluation plan (15 marks + shapes the novelty argument)

**Systems compared**
- B0: BM25 only. B1: tf-idf cosine (lnc.ltc). B2: BM25 + literal section-string matching (no mapping). B3: BM25 + typed concordance. B4: BM25 + treatment-sentiment filter only (an "Indian-Kanoon-like" baseline). **Full:** relevance + continuity + health.

**Judged query set (~40–50, built by the team)**
- Natural-language and section-based queries across crimes where change matters: murder (IPC 302 / BNS 103), cheating (420 / 318), dowry death (304B / 80), rape (375–376 / 63–64), common intention (34 / 3(5)), conspiracy (120B / 61), sedition (124A / 152), attempt to suicide (309), 377, adultery (497), mob lynching (new), plus ordinary doctrine queries as controls.
- Graded relevance (0/1/2) via pooling of the union of top-10 from all systems, **plus a "currency" tag** per result (safe to cite / caution / avoid — with reason). Do not derive these labels from the same mapping the system uses (circularity).

**Metrics:** P@5, P@10, Recall@10, nDCG@10, MAP, and **Stale@k** (share of top-k results that are overruled/changed-law). Treatment classifier: per-class P/R/F1 on a held-out labelled edge set. Overruling recall on a **gold list of known overrulings** (team must verify each against the judgments before use), starter ideas: ADM Jabalpur v. Shivkant Shukla -> overruled by K.S. Puttaswamy (2017); Suresh Kumar Koushal v. Naz Foundation -> overruled by Navtej Singh Johar (2018); Sowmithri Vishnu (adultery) -> overruled in Joseph Shine v. UoI (2018); P. Rathinam (s.309) -> overruled by Gian Kaur (1996); Rajesh Sharma (498A guidelines) -> set aside in Social Action Forum for Manav Adhikar (2018) ⚠️ verify; Kedar Nath Singh / s.124A is **not** overruled (operation stayed in 2022 ⚠️ verify) — a good "hard case" for the limitation segment.

**Sanity checks to show in the video:** "BNS 103" returns ~nothing under BM25 but returns IPC 302 precedents with ours; toggling the offence-date context changes the ranking; a known-overruled case drops in rank and shows its evidence.

## 9. Suggested 4-way work split (adjust to skills) — superseded by M1–M4 in README.md

- **A — Index & query engine:** ingestion, text cleaning, zones/metadata, inverted/positional/zone/parametric indexes, Boolean/proximity/phrase parser, BM25/tf-idf, top-K, tiered/champion lists.
- **B — Statutes:** act-aware extractor, typed concordance table (hand-verified top sections), continuity weights, offence-date toggle.
- **C — Citations & treatment (GPU):** citation extraction + resolver, rule patterns, labelling, classifier fine-tune on the 5090 Ti, precompute edge labels, health score.
- **D — Ranking, evaluation, demo, report:** fusion + tuning, judged-query set and metrics, baselines/ablation tables and graphs, thin CLI/Streamlit demo, README, video script, report, AI-use log.

## 10. Rough 36-hour plan (relative; compress if the clock already started)

- **H0–1:** open the dataset, check text format, fields, size, licence and how often BNS appears; confirm citation fields; run a BM25 baseline on a handful of queries. Decide corpus subset (e.g. criminal cases 1990/2000–2025) so the index stays laptop-friendly.
- **H1–10:** B0/B1 baselines + indexes (A); extractor + first concordance rows (B); citation extraction + start labelling (C); judged-query draft (D).
- **H10–22:** classifier training + precompute (C); continuity + health into the ranking (B/D); first ablation table (D).
- **H22–30:** tuning, error analysis, CLI/Streamlit demo showing intermediate outputs, clean-machine test of the README.
- **H30–36:** final metrics, video recording (live, no slides), 8-page report with work division and AI-use declaration, submit.

## 11. Repository layout (suggested) — superseded by the layout in README.md

```
README.md  PROJECT_BRIEF.md  AI_USE_LOG.md  DECISIONS.md
config/            # weights, label lexicon, paths (one place for lambdas and health formula)
data/              # raw/ (gitignored), interim/, concordance/ipc_bns.csv
src/
  ingest/  index/  query/  statutes/  citations/  treatment/  ranking/  eval/  demo/
artifacts/         # frozen offline outputs (index, edge labels, health scores, optional embeddings)
eval/              # judged_queries.jsonl, qrels, gold_overrulings.csv, results/
notebooks/         # exploration only
tests/
Makefile           # setup | download | build-index | train | demo | eval
```

## 12. Decision log (how we got here, so nobody re-litigates)

- All six tracks were ranked under "5090 Ti offline only, demo on mid-range laptops". T4 (crawling) and T2 (agentic) were weakest on demo risk; T1 (RAG) hurt by live generation; T5 (Indic) and T6 were the top two; the team chose **T6**.
- A first T6 problem statement used IL-PCSR (statute-aware precedent retrieval). A team member proposed the **staleness** idea (statute staleness + judicial staleness), which the team preferred; staleness was re-framed from a "warning feature" into the **core ranking signal**.
- Review fixes (all adopted): Indian Kanoon already has precedent-reliability labels; IPC judgments are not automatically stale; typed concordance instead of one offence ID; distinguish followed/distinguished/criticised/overruled with bench strength; never auto-declare "bad law"; show evidence + confidence.

## 13. Open risks to verify early

1. Dataset text quality/format and size; whether judgments include usable citation metadata. ⚠️
2. How many 2024–25 judgments cite BNS/BNSS. If few, run the main demo on IPC-era cases and treat BNS queries as the cross-code feature. ⚠️
3. Case-citation resolution rate; fallback is metadata-based matching on citation strings and case names.
4. Label quality and class imbalance for treatment (OVERRULED is rare): report per-class numbers, don't hide them behind accuracy.
5. Concordance coverage: hand-verified top sections only; unmapped sections must be shown as unmapped.
6. Indian Kanoon feature coverage and behaviour — cite as prior work, don't over-claim novelty. ⚠️
7. Laptop footprint: keep artefacts small; test on a clean machine with the README commands only.

## 14. Sources used during planning

- Assignment: CSD358 IR Mid-term Assignment 2026 (rubric, deliverables, rules).
- Indian Kanoon free features: https://indiankanoon.org/free_features/
- AWS Open Data, Indian Supreme Court Judgments: https://registry.opendata.aws/indian-supreme-court-judgments/
- Bar & Bench, IPC/CrPC to BNS/BNSS transition: https://www.barandbench.com/columns/clarifying-the-ipc-bns-bnss-transition-and-interplay
- LawSikho IPC->BNS conversion: https://lawsikho.com/blog/ipc-to-bns-conversion
- MHA BNS text: https://www.mha.gov.in/sites/default/files/BhartiyaNyayaSanhita_24022024.pdf ; PRS legislative brief: https://prsindia.org/billtrack/prs-products/prs-legislative-brief-1702470430
- LeCNet (JUST-NLP 2025): https://preview.aclanthology.org/setup/2025.justnlp-main.4
- Stanford Overruling Dataset: https://reglab.stanford.edu/data/the-overruling-dataset-a-benchmark-for-detecting-legal-decisions-that-have-been-overruled/
- IL-PCSR: arXiv 2511.00268 (HF: Exploration-Lab/IL-PCSR)
