# LexShift task runner. `make` is optional: every target is a plain python command you can run yourself
# (the README lists them). Activate your virtualenv first.
PY ?= python

.PHONY: help setup test smoke demo eval tune pool qrels check-data conformance feasibility final-check figures ui docmeta download build-index build-statutes build-citations build-health \n	m3 m3-extract m3-label-dry m3-label m3-citations-baseline m3-gold-sample m3-gold-merge m3-evaluate m3-test

help:
	@echo "setup            install requirements.txt"
	@echo "test             run the unit tests"
	@echo "smoke            contract + end-to-end check (the merge gate for main)"
	@echo "demo             ranked search: make demo QUERY='BNS 103 murder' ARGS='--offence-date 2025-01-10'"
	@echo "eval             ablation table on the test split"
	@echo "tune             tune fusion weights on the DEV split only"
	@echo "pool             build the blind judge sheet: make pool ROUND=round1"
	@echo "qrels            reconcile the two judges into eval/qrels.tsv: make qrels ROUND=round1"
	@echo "check-data       check the hand-made queries, qrels and gold list against the plan"
	@echo "conformance      check M1, M2 and M3 artefacts and functions against the shared contracts"
	@echo "feasibility      count what the corpus holds for each judged query (never a grade)"
	@echo "final-check      audit the submission checklist (ARGS=--run adds pytest, both smoke tests and the demo)"
	@echo "figures          draw the pipeline diagram for the report (docs/figures)"
	@echo "ui               the web interface at http://127.0.0.1:8765 (ARGS='--port 9000 --open')"
	@echo "docmeta          derive case titles for the demo from judgments.jsonl"
	@echo "download         M1: fetch the AWS Open Data judgments"
	@echo "build-index      M1: the search index, from data/processed/judgments.jsonl (once, about 20 s)"
	@echo "build-statutes   M2: doc_statutes.jsonl"
	@echo "build-citations  M3: citations.jsonl"
	@echo "build-health     M3: doc_health.jsonl"
	@echo "m3               M3: the whole pipeline (extract, citations, health) from the committed label cache, no API key"
	@echo "m3-extract       M3: mentions, resolution and windows -> m3_mentions.jsonl and reports/resolution.md"
	@echo "m3-label-dry     M3: count the windows to label and estimate requests and tokens, call nothing"
	@echo "m3-label         M3: Gemini labels into the cache (needs GEMINI_API_KEY; LIMIT=N caps new windows)"
	@echo "m3-citations-baseline  M3: citations.jsonl labelled by the tf-idf + logistic regression baseline instead"
	@echo "m3-gold-sample   M3: blank labelling sheets in data/labelling (N=250 DOUBLE=60)"
	@echo "m3-gold-merge    M3: merge the two labellers' sheets, Cohen's kappa, data/treatment_gold.csv"
	@echo "m3-evaluate      M3: per-class precision, recall and F1 of the LLM and the baseline -> reports/classifier_f1.md"
	@echo "m3-test          M3: the M3 unit tests"

setup:
	$(PY) -m pip install -r requirements.txt

test:
	$(PY) -m pytest

smoke:
	$(PY) eval/smoke.py

demo:
	$(PY) -m app.cli "$(QUERY)" $(ARGS)

eval:
	$(PY) -m eval.run_ablation --split test

tune:
	$(PY) -m eval.run_ablation --tune

ROUND ?= round1

pool:
	$(PY) -m eval.pool --round $(ROUND) $(ARGS)

qrels:
	$(PY) -m eval.make_qrels --round $(ROUND)

check-data:
	$(PY) -m eval.check_data

conformance:
	$(PY) -m eval.conformance

feasibility:
	$(PY) -m eval.feasibility $(ARGS)

ui:
	$(PY) -m app.server $(ARGS)

docmeta:
	$(PY) -m app.docmeta

download:
	$(PY) -m m1_index.ingest download

# Only the index is built here. `python -m m1_index.ingest build` is not part of this target: with an empty data/raw it rewrites
# data/processed/judgments.jsonl with zero records (docs/INTEGRATION_REVIEW.md, M1 finding 13).
build-index:
	$(PY) -m m1_index.index build

build-statutes:
	$(PY) -m m2_statute.extractor build

build-citations:
	$(PY) -m m3_treatment.citations build

build-health:
	$(PY) -m m3_treatment.scores build

# M3, one target per pipeline stage (m3_treatment/README.md). Only m3-label uses the network.
N ?= 250
DOUBLE ?= 60

m3:
	$(PY) -m m3_treatment.pipeline build

m3-extract:
	$(PY) -m m3_treatment.pipeline extract

m3-label-dry:
	$(PY) -m m3_treatment.pipeline label-llm --dry-run

m3-label:
	$(PY) -m m3_treatment.pipeline label-llm $(if $(LIMIT),--limit $(LIMIT))

m3-citations-baseline:
	$(PY) -m m3_treatment.pipeline citations --labels baseline

m3-gold-sample:
	$(PY) -m m3_treatment.gold sample --n $(N) --double $(DOUBLE)

m3-gold-merge:
	$(PY) -m m3_treatment.gold merge $(ARGS)

m3-evaluate:
	$(PY) -m m3_treatment.pipeline evaluate

m3-test:
	$(PY) -m pytest tests/test_m3_citations.py tests/test_m3_classifier.py tests/test_m3_gold.py tests/test_m3_graph.py tests/test_m3_pipeline.py tests/test_m3_resolver.py tests/test_m3_text_windows.py

final-check:
	$(PY) -m eval.submission_check $(ARGS)

figures:
	$(PY) -m eval.figures
