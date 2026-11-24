# Data discovery and classification

From the project directory with Python 3.11 and an activated virtual environment:

```sh
python -m pip install -r backend/requirements.txt
hf download sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2 tokenizer.json onnx/model.onnx --revision e8f8c211226b894fcb81acc59f3b34ba3efd5f42 --local-dir .models/minilm
python -m scripts.run_pipeline --model-path .models/minilm --offline
python -m scripts.evaluate
python -m pytest -q
```

The pipeline writes the synthetic SQLite source, schema, relationships, profiles,
classifications, domains, quality report, opportunities and evaluation labels to
`data/`. Only the separate evaluator
reads the labels and writes `evaluation.json`. Change the destination with
`--output-dir` for the pipeline and `--data-dir` for evaluation.

Inference runs locally. The full-precision ONNX export of MiniLM embeds schema
metadata only and caches the taxonomy vectors for each engine instance. Presidio uses local Arabic and
English tokenization and pattern recognizers. Person-name shape detection is
heuristic and does not establish identity. Use `--without-embeddings` for an
explicit Presidio-and-rules run when model weights are unavailable. The export
records which components ran.

Full-column counts are exact. Length, format, numeric and detection statistics
use a reproducible stratified sample distributed over non-null values (500 by default,
configurable with `--sample-size`). Profiles and classifications export counts,
masked structural patterns and evidence summaries. Format and checksum failures
remain evidence of possibly personal data.

Confidence is a heuristic evidence score. Configure review with
`--review-confidence` and `--review-margin`. Prototype sensitivity levels are
`internal` for routine data, `confidential` for personal data, `restricted` for
higher-impact identifiers, bank accounts and salary, and `undetermined` when
personal status is uncertain. These are prototype labels for human review.

Phase 3 writes `domains.json`, `quality_report.json`, and `opportunities.json`.
Quality reports use exact null, duplicate and orphan counts where applicable.
Format and representation checks report sample counts with explicit denominators.
Duplicate checks apply only to declared uniqueness or primary key constraints.
Severity uses affected fractions and critical checks. Readiness checks required
fields, direct declared joins, significant quality issues and review flags.
Readiness describes technical suitability. Confirm permitted use separately.

The pipeline uses deterministic rules by default. To opt into reasoning, set
`LLM_BASE_URL` (compatible API root ending in `/v1`), `LLM_API_KEY` and `LLM_MODEL`
in the process environment, then omit `--offline`. See `.env.example`. The provider
receives opaque schema identifiers, aggregate counts, taxonomy labels and verified
links. Its structured proposals must pass local reference and prerequisite
validation. Request failures or rejected responses leave deterministic results
in place. The output records which method generated each result.
