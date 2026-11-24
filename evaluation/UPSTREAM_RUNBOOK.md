# Local pretrained classification

Use Python 3.11 from the repository root. Install the backend requirements and prepare the existing MiniLM assets with the instructions in [README](../README.md). The pretrained models load on CPU and process the selected source values in memory.

```powershell
python -m pip install -r backend/requirements.txt "huggingface-hub==0.36.2"
python -m scripts.install_upstream_models pii
python -m scripts.install_upstream_models doduo
python -m scripts.scan_data_asset synthetic.sqlite result.json --engine pii
$env:PYTHONPATH = (Resolve-Path .deps/upstream-neural-v2).Path
```

Use `--engine current` for the current engine, `doduo` for its native semantic predictions and the current engine’s production decisions, or `upstream` to run both pretrained models. Each scanner runs discovery, profiling, field classification, domain grouping, quality checks, and opportunity analysis over a read-only SQLite connection. Each result contains model labels and aggregate evidence. Dataset and schema names appear explicitly, so name assets appropriately before distributing reports.

For OpenMetadata’s optional comparator, install `openmetadata-ingestion==2.1.1.0` and its classifier dependencies into `.deps/upstream-om` and install its English spaCy model before the scan. The comparator imports the released classifier and emits two views of its native results, raw label scores and direct-identifier labels meeting the fixed threshold. See the [OpenMetadata ingestion license](https://github.com/open-metadata/OpenMetadata/blob/main/ingestion/LICENSE).

The standalone benchmark loaded the released PII modules without starting OpenMetadata's unrelated catalog profiler registry. With the isolated dependency folder populated, this reproduces that import and runs the same comparison runner.

```python
import sys
import types
from pathlib import Path

dependencies = Path(".deps/upstream-om").resolve()
sys.path.append(str(dependencies))
metadata = types.ModuleType("metadata")
metadata.__path__ = [str(dependencies / "metadata")]
sys.modules["metadata"] = metadata

from evaluation.upstream_compare import run

holdout = Path("data/upstream/fresh/databases")
run("openmetadata", sorted(holdout.glob("*.sqlite")), Path("data/upstream/final/openmetadata"))
```

## Benchmark

Run these commands once per experiment checkout. The holdout generator refuses an existing fixture directory to preserve the sealed inputs and independent labels. Use an empty output directory per model run.

```powershell
python -m evaluation.upstream_score --seal
python -m evaluation.upstream_holdout
$fixtures = @(Get-ChildItem data/upstream/fresh/databases -Filter *.sqlite | ForEach-Object FullName)
python -m evaluation.upstream_compare current data/upstream/final/current @fixtures
python -m evaluation.upstream_compare pii data/upstream/final/pii @fixtures
python -m evaluation.upstream_compare doduo data/upstream/final/doduo @fixtures
python -m evaluation.upstream_score --fresh
```

Development benchmarking uses the prior nine synthetic SQLite fixtures from generalization, reliability, and Metacrafter. Use the same runner and place outputs in `data/upstream/development/<mode>`. Run `python -m evaluation.upstream_score` to pool their existing labels. The scorer reports measurement per dataset and pooled, including supported and unsupported labels, confusion matrices, personal-data errors, abstention and review. See [the rules for scoring native labels](UPSTREAM_SCORING.md).

## Attribution

The PII adapter uses PII Engineer’s multilingual GLiNER2 v2.1 weights and ports the span inference glue from Gantz AI’s source at commit `4ff53986a53351b3a516872a557832b44b166628`. The Apache 2.0 license is in [licenses/PII-Engineer.txt](../licenses/PII-Engineer.txt). DoDuo uses Megagon Labs’ released VizNet checkpoint and model and dataset code directly. Its Apache 2.0 license remains with the source checkout. The optional OpenMetadata comparator imports the installed ingestion distribution, which carries its own license.

[PII Engineer](https://github.com/gantz-ai/pii.engineer) · [Model card](https://huggingface.co/pii-engineer/PII-Engineer-Multi-NER-v2.1) · [DoDuo](https://github.com/megagonlabs/doduo)
