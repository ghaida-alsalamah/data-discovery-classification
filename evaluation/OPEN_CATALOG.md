# Open catalog and frozen validation

The closed semantic vocabulary put a hard ceiling on strict accuracy, and most privacy evidence came from exact patterns or declared subject paths. The open catalog uses a local instruction model to interpret the schema and aggregate observations and can propose types outside the built-in vocabulary. The label is provisional when independent evidence cannot confirm it. Format tests protect keys and validated identifiers. Person-link decisions require measured paths to an evidenced person entity. Domain grouping, read-only access, profiling, quality checks, opportunities and specialist correction reuse the catalog workflow.

This approach follows the zero-shot table annotation direction explored by ArcheType. It uses its own aggregate-only prompt and SQLite relationship validation. It does not train a model. [ArcheType paper](https://arxiv.org/abs/2310.18208)

On Windows, from the repository root:

```powershell
python -m evaluation.local_llm_setup runtime
python -m evaluation.local_llm_setup open-weights
python -m scripts.scan_data_asset source.sqlite catalog.json --engine open --owner "Data steward"
```

The default open-mode asset is Qwen3-4B-Instruct-2507 in the pinned Unsloth Q3_K_M quantization. A compatible locally available GGUF can be selected explicitly with `--model`. The Windows CPU runtime is llama.cpp b6500, with the release OpenMP DLL. The server binds loopback, disables proxy trust and suppresses runtime logs. Prompts contain bounded schema hints and aggregate value statistics. Source cell values are processed in the scanner only. [Model card and license](https://huggingface.co/Qwen/Qwen3-4B-Instruct-2507) · [Quantized distribution](https://huggingface.co/unsloth/Qwen3-4B-Instruct-2507-GGUF)

The four external SQLite inputs are from the Spider benchmark mirror. Copy `flight_2.sqlite`, `network_1.sqlite`, `student_transcripts_tracking.sqlite`, and `world_1.sqlite` to `data/open_validation`. Labels in the runner are separate project annotations over complete schemas. Spider provides the database inputs, with no native gold semantic, domain or privacy annotations used here. [Original Spider benchmark](https://yale-lily.github.io/spider/) · [SQLite mirror](https://huggingface.co/datasets/target-benchmark/spider-corpus)

```powershell
python -m evaluation.open_holdout freeze
python -m evaluation.open_holdout evaluate
```

The freeze fingerprints engine, scorer, inputs, model, and runtime. Both modes are compared without a dictionary, and the seal is verified again before scores are written. Legacy exact scores keep every field. The runner separately reports exact matches on declared extensions and novel labels. Old broad and joint metrics retain the historic taxonomy mapping. Schema grouping comparisons use name-independent B-cubed F1. Runtime fallbacks are reported explicitly.

The open mode is opt-in. Elm's asset identity, inventory and integrity, domain groups and explanations, and quality-aware opportunities remain in the same exports. A specialist can review provisional types and record corrections. No Phase 4 work is included.
