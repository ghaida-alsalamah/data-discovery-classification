# Controlled Groq model comparison

Production uses `openai/gpt-oss-120b` on Groq with low reasoning effort. The evaluation tests that model, `openai/gpt-oss-20b`, and `qwen/qwen3.8-27b`. The configured project listed all three with 131,072-token contexts and returned a correct result in the same one-field strict-schema smoke test. Groq documents the same Free ceilings for the three candidates at 30 requests per minute, 1,000 requests per day, 8,000 tokens per minute and 200,000 tokens per day. GPT-OSS maximum output is 65,536 tokens and Qwen maximum output is 16,384 tokens. The scanner's request budget is lower. Muse Spark Open was excluded because its listing was Enterprise/limited preview. [Groq limits](https://console.groq.com/docs/rate-limits) · [Model catalog](https://console.groq.com/docs/models) · [Structured outputs](https://console.groq.com/docs/structured-outputs)

The experiment changes the model ID in an evaluation-only subclass. It uses the same API, low reasoning effort, instructions, JSON schemas, context, local logic, validation and recovery. Field evidence is identical across models. The same domain prompt can receive different inputs because the scanner summarizes each model's preceding field outputs. Qwen had an additional paced diagnostic of at least 30 seconds between logical calls. No paid service or different inference backend was used. Production backend, CLI and evaluator hashes matched the prior sealed run.

## Development and repeats

The 94-field development comparison spans education, community care and dog kennels. GPT-OSS 120B returned all 67 routed fields. GPT-OSS 20B returned all 67 after recovery salvaged 12 fields. Qwen passed its smoke test and completed 22 routed fields, then fell back on 45 after a 429. A 30-second paced run still encountered 429 and returned the same routing counts. The schema quota probe reported tokens per minute while the public header reported full token headroom. The contradictory telemetry does not establish which internal allowance was binding. The incomplete Qwen result is operational evidence and does not support a model-quality ranking across the entire set.

| Development metric | GPT-OSS 120B | GPT-OSS 20B | Qwen 3.8 27B with fallback |
|---|---:|---:|---:|
| Exact semantic accuracy | 74.5% | 76.6% | 79.8% |
| Domain membership F1 | 95.4% | 89.1% | 93.2% |
| Direct PII precision / recall | 100% / 100% | 100% / 100% | 93.3% / 100% |
| Overall personal-data F1 | 80.4% | 91.3% | 88.9% |
| Person-linked F1 | 72.5% | 87.5% | 85.2% |
| Automated joint accuracy | 79.6% | 68.2% | 77.5% |
| Correct automated decisions | 39 / 49 | 30 / 44 | 31 / 40 |
| Automated coverage | 52.1% | 46.8% | 42.6% |
| Live requests | 9 | 15 | 4 |
| End-to-end scan time | 112.3 s | 160.5 s | 47.0 s |

GPT-OSS 20B was the only alternative to complete the full development comparison, and was selected for the sealed holdout. It had complementary privacy results on development, while production had better membership and made more correct automated decisions. The repeat schema was preselected as the last development schema. For 20B, both runs completed all 35 routed fields. They agreed on semantic type for 31/35 and privacy linkage for 32/35. Group memberships agreed for all 49 fields overall. The 120B repeat fell back on all 35 routed fields after schema and quota failures, so it does not measure response consistency on those fields. [Reasoning settings](https://console.groq.com/docs/reasoning)


## Sealed holdout and free-quota limit

The frozen holdout contains 90 fields across three unrelated synthetic schemas. GPT-OSS 20B completed all 57 routed fields. Its field recovery salvaged one 18-field batch. GPT-OSS 120B could not produce a live holdout field response. Two standard attempts stopped on HTTP 429. A scheduled retry honored a 196-second wait and still hit the quota during recovery. A production-sized synthetic probe returned a daily token-limit 429 with a 556-second retry interval, despite full reported per-minute token headroom. The three 120B attempts are preserved as quota/fallback evidence. Their results are the production pipeline in local fallback and cannot be attributed to the 120B model. There is no clean live-versus-live holdout estimate.

| Holdout metric | Production pipeline, all fields fell back | GPT-OSS 20B live |
|---|---:|---:|
| Exact semantic accuracy | 84.4% | 85.6% |
| Broader semantic accuracy | 88.9% | 90.0% |
| Literal domain accuracy | 0.0% | 0.0% |
| Domain membership F1 | 89.1% | 89.1% |
| Direct PII precision | 80.0% | 84.6% |
| Direct PII recall | 100.0% | 91.7% |
| Overall personal-data F1 | 81.9% | 80.0% |
| Person-linked F1 | 78.6% | 76.4% |
| Automated joint accuracy | 51.2% | 45.0% |
| Correct automated decisions | 22 / 43 | 18 / 40 |
| Automated coverage | 47.8% | 44.4% |
| Final fallback, routed fields | 57 / 57 | 0 / 57 |

For the 20B run, joint automated counts were 6/15 for home telecommunications, 3/15 for publishing rights, and 9/10 for industrial waste collection. The same counts under local fallback were 7/18, 6/15, and 9/10. The 20B run took 136.5 seconds with 11 requests, 6,931 input tokens and 4,255 completion tokens. It recorded three schema rejections and one terminal field-validation failure before recovery. The scheduled production attempt took 214.3 seconds including quota wait, with three HTTP calls. All requests remained on Groq Free and cost $0.

For the predeclared ownership probe, 20B correctly linked 7/13 subject attributes and correctly excluded 3/10 participant-reachable operational fields. Fallback scored 6/13 and 3/10. On the same 22 common Groq-completed development fields, raw semantic exact counts were 10, 12 and 12 for 120B, 20B and Qwen. Local reconciliation gave 13, 14 and 14 respectively. Raw exact privacy-linkage counts were 12, 9 and 6 and final counts were 10, 13 and 11. This illustrates that model output and local decision logic both affect the result. The structured production contract does not expose model reasoning traces. Verified field outcomes are the evidence here.

For 20B on the sealed set, the existing semantic score ranked semantic correctness with AUC 0.991 across all fields. Its automated joint correctness AUC was 0.297. The historical domain and privacy evidence scores had AUCs of 0.478 and 0.827 overall. Per-bin confidence results are retained as diagnostics. Review thresholds did not change.

## Release decision and technical assessment

Retain GPT-OSS 120B and the current production pipeline. The live development comparison showed complementary results, but 20B's privacy gains did not transfer to the point of passing the sealed release criteria. It made fewer correct automated decisions than even the fallback comparator on the fresh set. Qwen did not complete development at either tested pace, so its relative full quality remains unresolved.

Structured generation, the ambiguity of sanitized evidence, disagreement about domain granularity, and the difference between a reachable participant and the actual subject all limit automated correctness. Higher reasoning quality alone has not demonstrated a reliable remedy. The evidence does not establish that the targets are impossible, but it does not support claiming that existing free models and the current evidence are sufficient. A full live comparison requires adequate daily Groq token headroom for the production model. No additional model, paid provider, or architectural modification was promoted.

The existing suite passed 69 tests. Production backend, entry point and evaluation harness matched the previous production seal. Scripts and outputs are in the repository and under `data/groq_model_comparison` and `data/groq_model_holdout`.

