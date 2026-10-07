# Data

`data/raw/` and `data/processed/` are not committed: they are rebuilt (see the Makefile targets `unpack`, `download`, `build-index`, `build-statutes`, `build-citations`, `build-health`). What is tracked is the small
hand-built tables and the corpus itself in packed form, so that a fresh clone needs no download: **`make unpack`** restores `data/processed/judgments.jsonl` from `data/corpus/judgments.jsonl.xz` (41 MB, SHA-256 checked).

| Path | Tracked | Owner | What |
|---|---|---|---|
| `data/raw/` | no | M1 | The AWS download: the catalog (`catalog/`), each judgment's text (`text/<year>/`); the PDFs are deleted after reading |
| `data/corpus/judgments.jsonl.xz`, `judgments.jsonl.sha256` | **yes** | M1 | The corpus, packed: 4,819 judgments (`python -m m1_index.ingest pack` / `unpack`) |
| `data/corpus_manifest.csv` | **yes** | M1 | Every judgment in the corpus, its title, date, size and, for the named cases, the doctrine and role that put it there |
| `data/processed/judgments.jsonl` | no | M1 | One judgment per line (cleaned text, zones, metadata), unpacked from the tracked copy or rebuilt by `ingest build` |
| `data/processed/doc_statutes.jsonl` | no | M2 | Statute references per judgment |
| `data/processed/citations.jsonl` | no | M3 | Case-citation edges with the treatment label and confidence |
| `data/processed/doc_health.jsonl` | no | M3 | `health`, `authority` and evidence per judgment |
| `data/processed/index/index.pkl.gz` | no | M1 | The compact search index (52.7 MB), built by `make build-index` |
| `data/processed/doc_meta.jsonl` | no | M4 | Optional: title, date and bench per judgment, for the demo |
| `data/statute_map.csv` | yes | M2 | Typed IPC to BNS (and key CrPC to BNSS) mapping, every row with its sources |
| `data/treatment_gold.csv` | yes | M3 | Hand-labelled citation windows |
| `data/labelling/` | yes | M3 | Labelling sheets, adjudications and the frozen few-shot pool |
| `data/llm_labels/m3_llm_labels.jsonl` | yes | M3 | Frozen Gemini treatment labels (hash keys, no text): rebuilds need no API key |
| `data/sample/` | yes, if used | M1 | A small shareable sample of the corpus (see OQ-1 in `DECISIONS.md`) |

Record formats and vocabularies are in [../docs/CONTRACTS.md](../docs/CONTRACTS.md).

## Source and licence

**Indian Supreme Court Judgments**, AWS Open Data registry:
<https://registry.opendata.aws/indian-supreme-court-judgments/>.

Confirmed from the registry page on 2026-10-06: public S3 bucket `indian-supreme-court-judgments` in region `ap-south-1`;
no AWS account needed (`aws s3 ls --no-sign-request s3://indian-supreme-court-judgments/`); licence **CC-BY-4.0**; updated
bi-monthly; judgments from 1950 to 2025; raw JSON metadata, structured parquet metadata and judgments as zip files, in
English and regional Indian languages.

**Verified by M1 (2026-10-07), recorded in DECISIONS.md D-037:** the bucket is read over plain HTTPS without AWS tooling. Per year there is `metadata/parquet/year=Y/metadata.parquet` (title, petitioner,
respondent, judge, citation, case id, decision date, disposal nature, path) and the judgments are PDFs at `data/pdf/year=Y/english/<path>_EN.pdf` (a `S_` prefix on the path marks the supplementary SCR volumes).
The English set is **38,147 judgments, 19.5 GB** (the catalog lists 38,152, five have no English PDF). The corpus holds the criminal-law part of 2005 to 2025 plus the named doctrine cases (4,819 judgments); the
selection rules are in `m1_index/selection.py`.

Attribution (CC-BY-4.0): this project uses the Indian Supreme Court Judgments dataset listed in the AWS Open Data registry
(link above). Judgments are published court records; we store no personal data beyond what the courts publish. Copy the
exact attribution line the dataset's own page asks for into the report once M1 has confirmed it.

## Other datasets (optional, not required for the MVP)

Credit any dataset you add here and in the report. The brief lists IL-PCSR (gated, non-commercial licence: verify before
use), LeCNet, ILDC and the Stanford Overruling Dataset as optional extras; none is used yet.

## Ethics

Prefer the open AWS dataset over crawling. If anything is ever fetched from a website, obey `robots.txt`, rate-limit
requests to the same host, and record it in `DECISIONS.md`.
