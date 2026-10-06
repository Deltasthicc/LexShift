# Submission checklist

One submission per team through the course form: **repo link, video link, report PDF**. Tick every box before submitting.

## Repository and README (rubric: working system, 20)

- [ ] `main` has every module merged, and `python -m pytest` and `python eval/smoke.py` pass on it.
- [ ] `LEXSHIFT_STUBS=none python eval/smoke.py` passes: every provider is real. (`config.yaml` has no switch left at `true`
      unless it is documented as not built yet in the README status table.)
- [ ] **Clean-machine test:** clone the repository into a new folder, create a new virtual environment, and follow the README
      quick start with nothing else installed. Everything the README says works, with the commands it gives.
- [ ] The README states: what LexShift is, how to set up, how to run the demo, how to reproduce the evaluation, where the data
      comes from (with attribution), what works, and what is still planned. The status table is up to date.
- [ ] `common/weights_tuned.yaml` (tuned on dev) and the `eval/` inputs (`queries.jsonl`, `qrels.tsv`, `gold_overrulings.csv`,
      the judging rounds) are committed, so the table can be regenerated.
- [ ] `eval/results/` holds the final table, per-query CSV and chart, with **no `stub_*` files**.
- [ ] The demo shows no `STUB MODE` banner when run from a clean clone with the real artefacts.
- [ ] `DECISIONS.md` records every decision and every verified or falsified assumption; open questions are closed or listed.
- [ ] `AI_USE_LOG.md` is complete and its review columns say who reviewed what.
- [ ] No secrets, API keys, personal data or large raw dumps are committed (`git status` clean; `data/raw` ignored).
- [ ] Artefacts are small enough for a laptop (target under about 2 GB) and the demo runs offline on a mid-range CPU.

## Demo video (rubric: video, 10)

- [ ] 5 to 8 minutes, **unlisted** YouTube or Drive link that plays in a private window; no slides.
- [ ] Shows: the problem and why Track 6 (about a minute); the system running end to end on real queries **including one
      limitation**; the pipeline with real intermediate output (postings, weights, scores); the evaluation against a baseline;
      every member explaining their own component. Details in [VIDEO_SCRIPT.md](VIDEO_SCRIPT.md).

## Report PDF (rubric: report quality, 10; evaluation, 15; novelty, 10)

- [ ] At most 8 pages excluding references and appendix, following [REPORT_SKELETON.md](REPORT_SKELETON.md): problem and track
      relevance (with the papers actually read), how IR was used (with a pipeline diagram and where in the code), beyond IR,
      novelty against the obvious baseline and existing tools, evaluation (judged queries, P@k, recall, MAP, nDCG, baseline
      comparison, graphs or tables), limitations and roadmap, work division, AI-use declaration.
- [ ] Every number comes from a generated file; nothing is from memory; small-sample caveats are stated.
- [ ] The dataset is credited (CC-BY-4.0) and any other source is cited.

## Ethics and rules

- [ ] Dataset credited; no personal data collected beyond what the courts publish; if anything was fetched from a website,
      `robots.txt` was obeyed and requests were rate-limited (and recorded in `DECISIONS.md`).
- [ ] All AI use is declared: the coding assistants, the LLM used for labelling, and which parts were human-reviewed.
- [ ] Nothing is copied from existing projects, papers or blogs; libraries and datasets are credited.
- [ ] The work was built inside the 36-hour window and is not an earlier project.
- [ ] Output wording: "treatment signals with evidence", never "bad law" or "dead law", and the not-legal-advice note is shown.

## If time runs short (cut in this order)

Tiered index, section-text similarity, point-level health, the Streamlit page (the CLI is enough), type D queries.
