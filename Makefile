# LexShift task runner. `make` is optional: every target is a plain python command you can run yourself
# (the README lists them). Activate your virtualenv first.
PY ?= python

.PHONY: help setup test smoke demo eval tune pool qrels check-data conformance feasibility final-check figures ui docmeta download build-index build-statutes build-citations build-health

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
	@echo "build-index      M1: judgments.jsonl and the search index"
	@echo "build-statutes   M2: doc_statutes.jsonl"
	@echo "build-citations  M3: citations.jsonl"
	@echo "build-health     M3: doc_health.jsonl"

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

build-index:
	$(PY) -m m1_index.ingest build
	$(PY) -m m1_index.index build

build-statutes:
	$(PY) -m m2_statute.extractor build

build-citations:
	$(PY) -m m3_treatment.citations build

build-health:
	$(PY) -m m3_treatment.scores build

final-check:
	$(PY) -m eval.submission_check $(ARGS)

figures:
	$(PY) -m eval.figures
