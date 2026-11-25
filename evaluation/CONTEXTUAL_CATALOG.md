# Contextual catalog

The contextual scan is the default catalog command. It combines local content evidence, independent entity recognition, and measured database relationships. It uses the existing catalog export for discovery, business domains, ownership, quality, opportunities, and specialist corrections. An optional instruction model proposes meanings and person roles from schema context. Observed formats and declared constraints still control accepted identifiers. A reference to an owner or reviewer can be person-linked while the surrounding object records remain a separate scope.

## Run the catalog

Install the backend dependencies and the pretrained English entity model where desired. The scanner uses the installed `en_core_web_md` package or the model already staged by the OpenMetadata evaluation. The catalog command supports SQLite and opens one read-only snapshot.

```powershell
python -m pip install -r backend/requirements.txt
python -m spacy download en_core_web_md
python -m scripts.scan_data_asset source.sqlite data/catalog.json
```

Optional local inference uses a pinned llama.cpp release and GGUF artifact. Setup verifies both checksums. On Windows the runtime needs OpenMP. The setup reuses the existing OpenMP DLL when it is available. The scanner records completed proposals, verified structural fields, and fallback per field.

```powershell
python -m evaluation.local_llm_setup context-runtime
python -m evaluation.local_llm_setup context-weights
python -m scripts.scan_data_asset source.sqlite data/catalog.json --model .models/local-llm/Qwen3.5-4B-Q4_K_M.gguf
```

The validated Windows Vulkan build can be installed with `python -m evaluation.local_llm_setup context-vulkan`. Pass `--llama-server .models/local-llm/b8400-vulkan/llama-server.exe --gpu-layers 99` to request GPU offload.

Use the same CLI with `--provider` for an approved OpenAI-compatible HTTPS Chat Completions endpoint that supports structured JSON responses. Set `LLM_BASE_URL`, `LLM_MODEL`, and `LLM_API_KEY` through the execution environment. Production database rows, freeform descriptions, and unrecognized metadata tokens stay local. The request contains vocabulary-filtered hints, structural relations and bucketed aggregates. The HTTP client disables redirect following and environment proxies. The system treats metadata as input data. Choose the provider's retention settings with the data steward before any real use. [llama.cpp b8400](https://github.com/ggml-org/llama.cpp/releases/tag/b8400) · [Qwen GGUF](https://huggingface.co/ggml-org/Qwen3.5-4B-GGUF) · [spaCy English model](https://spacy.io/models/en)

## Evaluation

Development selected the offline path before the final seal. On the 94-field development comparison, this path achieved 76.6% exact semantic accuracy, 91.1% overall personal-data F1, 87.1% person-linked F1, and 82.5% joint accuracy on 40 automated decisions. It scanned in 8.1 seconds. Actual Qwen3.5 inference on the Iris Xe processed all 67 routed fields and took 188.0 seconds of scan time. Its exact accuracy was 73.4%, person-linked F1 77.1%, and automated joint accuracy 67.4%. The CLI therefore only calls an inference model when requested.

Development examples use previously evaluated cases. The independent acceptance suite uses the schema definitions of four other Spider databases and new synthetic rows. The fixture builder reads source schema metadata only. It creates separate field labels, hashes the input files and uses the established exact semantic, privacy, and name-independent domain grouping metrics. Domain grouping is evaluated by membership rather than the literal group name. All exact semantic labels stay in the denominator. [Spider publication](https://aclanthology.org/D18-1425/)

For reproduction, copy the four source SQLite schemas into `data/contextual_holdout/schema_sources`, and put the corresponding source URLs in `data/contextual_holdout/<database>.source`. The database names are `customer_deliveries`, `insurance_and_eClaims`, `product_catalog` and `station_weather`. Run `prepare` to generate the synthetic inputs. The runner accepts `--selected offline` or `--selected local` to seal the selected approach and its effective assets before final inference.

```powershell
python -m evaluation.contextual_eval prepare
python -m evaluation.contextual_eval freeze --selected offline
python -m evaluation.contextual_eval final --selected offline
```

The benchmark exports field classifications and metrics under `data/contextual_holdout`. The source downloads are available from the project mirror. [Schema sources](https://huggingface.co/datasets/target-benchmark/spider-corpus/tree/main/train_database)
