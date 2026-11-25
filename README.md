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

## Elm Challenge 1 catalog

The catalog is for data stewards and specialists exploring an authorized SQLite asset. Use the read-only scanner to export schema, relationship checks, field types and meanings, sensitivity, domains, quality findings, and potential uses.

```powershell
python -m scripts.scan_data_asset sample.sqlite data/catalog.json --owner "Data steward" --description "Customer service requests"
python -m scripts.scan_data_asset sample.sqlite data/catalog_with_dictionary.json --dictionary descriptions.json
python -m scripts.scan_data_asset sample.sqlite data/catalog_reviewed.json --dictionary descriptions.json --reviews reviews.json
```

Install the backend dependencies first. The default scanner combines local field-purpose validation with measured relationship evidence. See [default scanner setup and validation](evaluation/DEFAULT_CATALOG.md). MiniLM assets are optional for scanning. The owner and exported asset description are operator-supplied. Omit the owner when it is unknown. The data dictionary accepts descriptive text only and is optional. Use the source's exact table and field names. Descriptions provide evidence and can leave a field unresolved.

```json
{
  "description": "Customer services and finance",
  "tables": {
    "requests": {
      "description": "Service requests recorded by the contact centre",
      "fields": {"q7": "Payment amount recorded for the completed request"}
    }
  }
}
```

The catalog distinguishes direct PII from inferred person-linked data. Linking uses measured matches along declared references to unique keys. Empty joins provide no affirmative linkage. Partial matches name the relationships and require review. Domain explanations distinguish descriptions, semantic evidence, and verified references. The semantic path shows the category and supported subtype. Pending reviews identify fields requiring specialist attention.

For corrections, supply an ordered JSON array. Each entry has `table`, `field`, `reviewer`, `reviewed_at` with a time zone, `reason`, and a `changes` object with any of `semantic_type`, `data_domain`, `personal_data`, and `sensitivity`. Export to a new file and retain the original report and correction file. The reviewed export records the old and new judgments while retaining the detector evidence. Use neutral reviewer identifiers and reasons without personal data. Regulatory decisions and final approval belong to the responsible specialist.

Use synthetic or explicitly authorized sources. The scanner opens SQLite read-only, performs local inference, and exports structural and aggregate evidence. Keep source databases, dictionaries, catalogs and review files in the authorized workspace. For this evaluation, retain synthetic exports for at most 30 days unless a shorter organizational policy applies, then have the workspace owner remove the local copies. Keep any approved long-term review record separately under the owner's retention policy. The scanner does not perform automatic deletion.

Run `pytest -q -s tests/test_elm_acceptance.py` for the fixed representative acceptance checks. Exact historical scores and their sealed artifacts remain pinned to the historical revision `431e34a`. Run the old sealed evaluation from that revision if you need to reproduce those hashes.

### English scanner comparison

The archived `--engine english` scanner uses English metadata normalization and local content summaries. The previous scanner is available with `--engine enhanced`. The existing MiniLM weights are optional for scanning. Install the pinned assets above before reproducing this comparison. Inferred domains outside the fixed list are marked for review. The catalog exports privacy roles and path evidence while keeping source values local.

```powershell
python -m evaluation.english_fixture
python -m scripts.scan_data_asset data/english_acceptance/english_business.sqlite data/english_acceptance/before.json --engine enhanced
python -m scripts.scan_data_asset data/english_acceptance/english_business.sqlite data/english_acceptance/after.json --engine english
python -m evaluation.english_score
```

The first command creates a new fixture directory and refuses to replace a frozen fixture. Scoring verifies the database and label hashes. The 48-field English fixture tests the supplied Elm workflow with valid and malformed identifier controls, ambiguous metadata, a broken join, and unsupported types. Its results apply to these synthetic scenarios.

### Evidence scanner

The archived `--engine evidence` mode reports semantic verification, business grouping, and privacy separately. It reuses the existing detector and MiniLM candidates. Records can carry provisional type and domain suggestions while verified decisions retain their evidence. It runs locally against a read-only SQLite snapshot. See [public validation](evaluation/PUBLIC_VALIDATION.md) for the frozen comparison.
