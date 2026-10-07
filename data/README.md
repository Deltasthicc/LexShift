# Data

Nothing in `data/raw/` or `data/processed/` is committed: they are rebuilt by the pipeline (see the Makefile targets
`download`, `build-index`, `build-statutes`, `build-citations`, `build-health`). Only the small hand-built tables are
tracked.

| Path | Tracked | Owner | What |
|---|---|---|---|
| `data/raw/` | no | M1 | The AWS download |
| `data/processed/judgments.jsonl` | no | M1 | One judgment per line (cleaned text, zones, metadata) |
| `data/processed/doc_statutes.jsonl` | no | M2 | Statute references per judgment |
| `data/processed/citations.jsonl` | no | M3 | Case-citation edges with the treatment label and confidence |
| `data/processed/doc_health.jsonl` | no | M3 | `health`, `authority` and evidence per judgment |
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

**Not stated on the page, so not yet verified:** the folder layout, the parquet schema, the size, and whether the judgment
files are PDFs or text. M1 verifies these on a small sample first and records the result in `DECISIONS.md`.

Attribution (CC-BY-4.0): this project uses the Indian Supreme Court Judgments dataset listed in the AWS Open Data registry
(link above). Judgments are published court records; we store no personal data beyond what the courts publish. Copy the
exact attribution line the dataset's own page asks for into the report once M1 has confirmed it.

## Other datasets (optional, not required for the MVP)

Credit any dataset you add here and in the report. The brief lists IL-PCSR (gated, non-commercial licence: verify before
use), LeCNet, ILDC and the Stanford Overruling Dataset as optional extras; none is used yet.

## Ethics

Prefer the open AWS dataset over crawling. If anything is ever fetched from a website, obey `robots.txt`, rate-limit
requests to the same host, and record it in `DECISIONS.md`.
