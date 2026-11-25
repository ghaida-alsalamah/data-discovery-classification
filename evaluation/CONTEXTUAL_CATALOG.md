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

## Independent results

The final run sealed the offline default selected from development at `f17accc`. It used 129 fields across four databases. No data dictionary was supplied.

| Metric | Previous default | Contextual default |
|---|---:|---:|
| Exact semantic accuracy | 72.1% | 72.1% |
| Broader semantic accuracy | 82.9% | 82.9% |
| Domain grouping F1 | 84.6% | 84.6% |
| Direct PII precision and recall | 100% / 100% | 100% / 100% |
| Overall personal-data F1 | 65.7% | 65.7% |
| Person-linked data F1 | 60.0% | 60.0% |
| Automated coverage | 38.8% (50/129) | 46.5% (60/129) |
| Group-membership joint accuracy | 28.0% (14/50) | 28.3% (17/60) |
| Legacy literal domain accuracy | 12.4% | 12.4% |
| Legacy automated joint accuracy | 22.0% | 18.3% |
| Total scan time | 2.4 s | 3.3 s |

The test contained five direct identifiers, all in customer deliveries. Both engines found all five and reported zero direct-PII false positives. Both missed all 22 person-linked labels in insurance. The person entities there have internal keys and general free text. The offline path lacked corroborating identity evidence to anchor the relationships.

| Database | Fields | Exact semantics | Domain grouping F1 | Personal-data F1 | Automated fields | Joint successes |
|---|---:|---:|---:|---:|---:|---:|
| Customer deliveries | 51 | 92.2% | 92.1% | 95.8% | 25 | 15 |
| Insurance claims | 30 | 90.0% | 78.3% | 0.0% | 18 | 2 |
| Product catalog | 29 | 48.3% | 71.6% | Undefined | 16 | 0 |
| Station weather | 19 | 26.3% | 90.4% | Undefined | 1 | 0 |

The 85% target was unmet. Twenty-two fields had expected semantic types outside the legacy taxonomy. Semantic coverage and person linkage varied substantially by database. Greater automated coverage produced three more fully correct fields, with low joint accuracy across the automated subset. The current result supports steward-reviewed discovery.

The Qwen3.5 development run used 15.2 seconds of startup and 188.0 seconds of scan time, with about 5.8 GiB peak server working set on Iris Xe. An external-provider evaluation requires an approved HTTPS inference endpoint and its credentials. A higher-capacity local model evaluation would need a GPU host with at least 16 GiB of dedicated VRAM for a quantized 8B-14B model and its context. Neither resource was available for this run.

## Groq Free cataloging

Use a dedicated Groq Free organization and turn on Zero Data Retention in its Data Controls. Store the key as `GROQ_API_KEY` in the ignored workspace `.env`, then run:

```powershell
.\.venv\Scripts\python.exe -m scripts.scan_data_asset data\synthetic.sqlite data\groq_catalog.json --free-provider groq
```

The scanner sends compact, allowlisted metadata and bucketed observations. Raw samples, dictionary descriptions, and evaluation labels stay local. Classification resumes with local evidence for fields whose cloud request fails. The integration uses a fixed model on the standard endpoint. The organization must remain on the Free plan for the $0 budget to hold. Logs and reports must stay local if the catalog contains confidential metadata.

For a synthetic-only fallback run, explicitly pass `--free-provider gemini` with a `GEMINI_API_KEY` tied to an unbilled AI Studio Free project. Google may use free-tier input and output for product improvement. The scanner does not automatically switch providers.

Run the development comparison with `python -m evaluation.contextual_eval groq --out data/groq_development`. For a fresh independent run from a clean output directory, run `python -m evaluation.groq_independent prepare`, then `freeze`, then `run`. The runner writes per-database predictions, metrics, and a seal under `data/groq_independent`. The seal covers the fixture contents and checked-in implementation inputs. Hosted provider weights and service capacity may change.
