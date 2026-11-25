# Default classification and validation

The read-only catalog selects the default classifier for both the CLI and the Python scanner. It verifies declared keys, uses local name and identifier evidence, and measures declared paths to corroborated person entities. An evidenced format can become a specific semantic type, with a parent category. Unresolved types or conflicting evidence stay eligible for specialist review. Field classifications, domain descriptions, data quality, usage readiness, and review history are available in the catalog export.

The scanner uses an installed Qwen2.5 1.5B Instruct Q4_K_M model for a single batch of up to six unresolved fields per database. The prompt uses vocabulary-filtered metadata, structure, and aggregate statistics. Source cell values never enter the prompt or export. The Windows CPU runtime binds to loopback and suppresses server logs. The CLI still completes if the model is unavailable and records its status in the catalog. The local assets are installed from pinned upstream releases. [Qwen weights and license](https://huggingface.co/Qwen/Qwen2.5-1.5B-Instruct-GGUF) · [llama.cpp runtime](https://github.com/ggml-org/llama.cpp/releases/tag/b6500) · [libphonenumber](https://github.com/google/libphonenumber) · [Presidio recognizers](https://microsoft.github.io/presidio/supported_entities/)

From the repository root, after installing the backend requirements:

```powershell
python -m evaluation.local_llm_setup runtime
python -m evaluation.local_llm_setup weights
python -m scripts.scan_data_asset source.sqlite data/catalog.json --owner "Data steward"
python -m scripts.scan_data_asset source.sqlite data/catalog.json --offline
```

The scanner works without descriptions. See the README for the optional data dictionary and specialist correction formats. Earlier classifiers remain available for benchmark reproduction. The catalog describes technical readiness and review status. The data steward is responsible for permitted use and the retention and deletion of exported files.

## Independent evaluation

Download the four named SQLite databases from the Spider mirror's validation database directory into `data/default_validation`. The filenames are `battle_death.sqlite`, `dog_kennels.sqlite`, `hospital_1.sqlite`, and `voter_1.sqlite`. The project supplies its own field annotations. The four databases were held out from development in this repository. Pretraining overlap is unknown. [Original Spider benchmark](https://yale-lily.github.io/spider/) · [SQLite mirror](https://huggingface.co/datasets/target-benchmark/spider-corpus)

```powershell
python -m evaluation.default_holdout freeze
python -m evaluation.default_holdout evaluate
```

The evaluator seals the complete labels, SQLite inputs, scanner revision, scoring protocol, MiniLM assets, GGUF, and runtime binaries before inference. It compares the former evidence default, the new default offline, and the new default with the local model using the same inputs without a data dictionary. Run the two commands in sequence in a fresh output directory. Field results and the shared `metrics.json` are written under `data/default_validation`.

Exact semantics include every field. The legacy taxonomy-based broader metric and the legacy string-based domain and joint scores are preserved. Domain grouping B-cubed F1 compares group memberships across all fields independently of label strings. Additional automated joint accuracy requires exact semantic type, matching known personal-data status, and per-field B-cubed membership F1 of at least 0.85. Group sizes include reviewed fields. Unknown predictions receive zero group credit. Uncertain privacy truth has the same treatment as in the legacy score. Confidence is a heuristic evidence score.
