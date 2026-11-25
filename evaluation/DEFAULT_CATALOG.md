# Default classification and validation

Run the read-only SQLite scanner from the repository root after installing the backend requirements.

```powershell
python -m scripts.scan_data_asset source.sqlite data/catalog.json --owner "Data steward"
```

The default scanner uses local content and schema evidence to establish the purpose of a field. It separately checks the validity of sampled identifiers. A field can hold personal identifiers and still contain invalid values. The catalog shows validity issues and makes unresolved classifications available for specialist review. Person-linked results cite measured paths over declared relationships. The export includes the asset and its read-only access scope, inventory, field evidence, domain descriptions and boundaries, data quality, opportunity readiness, and review history. It omits source values and numeric extrema from the profile.

The normal command runs offline from the existing backend installation. MiniLM improves metadata evidence when present. A data dictionary is optional. See the README for the dictionary and specialist correction formats. The data steward controls permitted use and how long catalog and review files are stored.

## Final release benchmark

Use the Spider SQLite mirror's validation database directory. Copy the following SQLite files to `data/default_release_validation`. Alongside each SQLite file, save its source URL as `<name>.source`. The sources are also recorded in the seal written by the runner. [Spider publication](https://aclanthology.org/D18-1425/) · [SQLite inputs](https://huggingface.co/datasets/target-benchmark/spider-corpus/tree/main/validation_database)

- `course_teach.sqlite`
- `cre_Doc_Template_Mgt.sqlite`
- `museum_visit.sqlite`
- `poker_player.sqlite`
- `real_estate_properties.sqlite`
- `singer.sqlite`
- `tvshow.sqlite`

Install the pinned MiniLM assets for both scanners to reproduce the benchmark, then run the following commands in a fresh output directory.

```powershell
python -m evaluation.release_holdout freeze
python -m evaluation.release_holdout evaluate
```

The runner seals source and label hashes, configuration, scanner revision and evaluation code. Both scanners receive the same 122 fields, with no data dictionary. The runner verifies the seal before and after the scans, and reads labels for scoring only after both scans finish. Per-field classifications and pooled and per-database metrics are under `data/default_release_validation`. The project supplies classification annotations. These are public schemas held out from the project's development. Pretraining overlap is unknown.

Legacy exact, broader, domain, and joint scores remain in the results. Exact semantic accuracy includes out-of-taxonomy types. B-cubed domain F1 compares memberships across all fields independently of label names. The additional automated joint score requires exact semantic type, matching known personal-data status, and a per-field domain membership F1 of at least 0.85. Reviewed fields are included when calculating group sizes. Unknown groups receive zero credit in the joint score. Uncertain privacy truth has the same treatment as in the legacy score. Confidence is a heuristic evidence score.

## Earlier contextual comparison

The four-database comparison at `de71bf4` measured the former scanner and the candidate with and without Qwen2.5 1.5B Instruct Q4_K_M. It used `battle_death`, `dog_kennels` and `voter_1` from the SQLite mirror's validation directory and `hospital_1` from its training directory. Use that commit and `python -m evaluation.default_holdout freeze` followed by `evaluate` to reproduce it. The model processed 21 fields across four loopback requests in 116.2 seconds and made no net gain on the pooled classification metrics. That comparison informed the release decision to run offline by default. [Qwen weights and license](https://huggingface.co/Qwen/Qwen2.5-1.5B-Instruct-GGUF) · [llama.cpp runtime](https://github.com/ggml-org/llama.cpp/releases/tag/b6500)

Local identifier checks reuse [libphonenumber](https://github.com/google/libphonenumber) for phone number plans and [Presidio](https://microsoft.github.io/presidio/supported_entities/) for US SSN validation.
