# Scanner Core handover

## Integration boundary

The Scanner Core is a synchronous Python library and command-line tool. The service and web interface are planned. The module directory is named `backend/` because it contains Python scanner code that a future service can import. It has no HTTP service or frontend.

| Entry point | Use |
| --- | --- |
| `python -m scripts.scan_data_asset DATABASE OUTPUT` | Read an SQLite source and write one UTF?8 JSON catalog |
| `scripts.scan_data_asset.AssetScan` | Run a scan in a worker and receive the catalog as a Python dictionary |
| `scripts.scan_data_asset.write_report` | Serialize a catalog with the existing JSON writer |
| `python -m scripts.run_pipeline` | Generate demonstration data and historical pipeline outputs |
| `evaluation/` | Reproduce or inspect research and independent evaluations separately from production |

## Inputs and configuration

| Input | Contract |
| --- | --- |
| Database | Existing authorized SQLite file accessible to the worker. The connector opens it in URI read-only and query-only modes and prohibits attachment |
| Output | Writable JSON destination for CLI scans. Use a separate job directory and a distinct destination for reviewed catalogs |
| Owner and description | Optional operator-supplied asset metadata. Use a neutral description and record an unknown owner when applicable |
| Data dictionary | Optional JSON object of asset, table, and field descriptions. Keys use exact SQLite table and column names |
| Reviews | Optional ordered JSON array of specialist corrections |
| Local assets | spaCy English NER and MiniLM ONNX assets are optional. Install the versions in the [README](../README.md#getting-started) to match the benchmark evidence setup |
| Groq Free | Explicitly select `--free-provider groq`. Put the dedicated Free project's secret in `GROQ_API_KEY` in the ignored `.env` file. The model is fixed at `openai/gpt-oss-120b` |
| Offline operation | Pass `--offline` or use the default CLI with no provider selected |

Run from the repository root so relative paths for `.env`, `.models/`, and optional assets resolve consistently. The production invocation uses the contextual scanner. Alternate engines, experimental domain grouping, Gemini, and custom endpoints are excluded from normal integration. The legacy custom-provider interface reads `LLM_BASE_URL`, `LLM_MODEL`, and `LLM_API_KEY` from the process environment when explicitly selected.

Dictionary example

```json
{
  "description": "Synthetic service catalog",
  "tables": {
    "requests": {
      "description": "Service requests",
      "fields": {
        "fee": "Amount charged for the completed request"
      }
    }
  }
}
```

Review example

```json
[
  {
    "table": "requests",
    "field": "fee",
    "reviewer": "steward-01",
    "reviewed_at": "2026-11-25T12:00:00+03:00",
    "reason": "Confirmed the field definition against the approved dictionary",
    "changes": {
      "data_domain": "finance"
    }
  }
]
```

Review changes support `semantic_type`, `data_domain`, `personal_data`, and `sensitivity`. Keep original and reviewed reports as separate records. Final regulatory decisions and opportunity approval belong to the responsible specialist.

## Python integration

```python
from pathlib import Path

from scripts.scan_data_asset import AssetScan, write_report

catalog = AssetScan(offline=True).scan(
    Path("data/demo/synthetic.sqlite"),
    owner="Demo data steward",
)
write_report(Path("data/demo/integration-catalog.json"), catalog)
```

For Groq Free, construct a provider within the lifetime of the HTTP client.

```python
from pathlib import Path

import httpx
from backend.app.classification.context_provider import FreeCatalogProvider
from scripts.scan_data_asset import AssetScan

with httpx.Client(timeout=35, trust_env=False, follow_redirects=False) as client:
    provider = FreeCatalogProvider(client, "groq", env_path=Path(".env"))
    catalog = AssetScan(provider=provider).scan(Path("data/demo/synthetic.sqlite"))
```

Run scans in a job worker. The provider tracks pacing, failures, and quota state for its current instance. Give each job its own client/provider and coordinate cloud concurrency across workers to stay within the project quota. Handle source connection and configuration errors at the worker boundary. A successful scan can contain both model-assisted and locally resolved fields. Surface this distinction to operators.

## Output contract

| JSON key | Contents |
| --- | --- |
| `schema.asset`, `schema.tables` | Asset scope, owner, SQL columns, primary keys, unique constraints, foreign keys |
| `relationships`, `profiles` | Discovered edges, table/column profiles, and privacy-safe structural evidence |
| `classifications` | One decision per field under `table_name` and `column_name`, with semantic type and path, domain, privacy, evidence, confidence, and review dimensions |
| `domains` | Domain descriptions, membership reasons, cross-domain links, quality and usage constraints |
| `quality`, `opportunities` | Quality checks and opportunity readiness, prerequisite checks, and usage restrictions |
| `context_runtime`, `context_summary` | Runtime mode and aggregate context status. Individual fields expose `context_status` |
| `review_history` | Applied specialist corrections and their reasons |
| `timing_seconds`, `native_predictions` | Timing and adapter diagnostics |

Use `personal_linkage` to distinguish `direct`, `linked`, `none`, and `uncertain`. Read `review_required` and `review_dimensions` for routing. The heuristic `confidence` measures semantic evidence and is unsuitable as a joint reliability or regulatory approval score. See the [synthetic excerpt](examples/scanner-output.json).

Catalogs include source metadata and can be sensitive even without raw cell values. Enforce asset authorization, protected job storage, retention and deletion policy, and least-privilege access in the service layer. The scanner does not manage retention or perform automatic deletion. Cloud mode sends allowlisted evidence derived locally. Enable it only for approved assets and configured privacy controls.

## Verification

Run `python -m pytest -q`. Optional regression cases require their corresponding model or experiment assets. The handover regression run used the installed optional assets. The [published metric snapshot](../evaluation/results/scanner_core_metrics.json) and [model comparison](../evaluation/GROQ_MODEL_COMPARISON.md) summarize results and limits. Full working databases, raw local exports, model assets, and credentials stay out of Git.
