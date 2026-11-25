# Groq architecture validation

The earlier run recorded two schema retries and two failed batches. Its counters did not preserve the terminal causes, so the 37 fallback fields cannot be attributed to a specific timeout, rate limit, token limit, or malformed response. The new provider counts sanitized failure categories and accepts no partial response. Recoverable field batches can be split once. Successful batches are not sent again. Quota exhaustion stops the provider.

## Fresh sealed holdout

The three synthetic databases contain 84 fields. The baseline and recovery runs reuse the same original field responses. The baseline requested one separate domain response because recovered fields changed the domain input. The graph comparison shares the recovery responses. Confidence is compared on fixed predictions at fixed coverage.

| Metric | No recovery | Recovery | Recovery and graph experiment |
|---|---:|---:|---:|
| Exact semantic accuracy | 86.9% | 88.1% | 88.1% |
| Domain grouping F1 | 81.2% | 84.3% | 80.2% |
| Direct PII precision | 90.0% | 100.0% | 100.0% |
| Direct PII recall | 100.0% | 100.0% | 100.0% |
| Overall personal-data F1 | 84.2% | 84.2% | 84.2% |
| Person-linked F1 | 80.7% | 79.3% | 79.3% |
| Automated joint accuracy | 51.1% | 56.2% | 52.1% |
| Correct automated decisions | 24 / 47 | 27 / 48 | 25 / 48 |
| Automated coverage | 56.0% | 57.1% | 57.1% |
| Field fallback | 17 / 53 routed | 0 / 53 routed | 0 / 53 routed |

One live response failed local field schema validation after the provider schema recovery path. Splitting it into two requests recovered all 17 fields. The recovery path took 148.88 seconds with 10 requests, 6,951 input and 5,273 completion tokens. The baseline replay took 3.66 seconds and made one additional live domain call. The graph replay took 2.84 seconds with no additional requests. Replay times exclude shared inference and cannot be compared to end-to-end live time. Eleven calls across the experiment used the configured Groq Free account at $0. All inference remained synthetic and privacy-filtered.

The graph refinement required a verified operational parent and shared purpose terms. It made no change to correct automated counts on recorded development results or either of the two prior regression holdouts. On fresh fisheries data it incorrectly merged independent landing compliance records into a haul activity, losing two correct automated decisions at identical coverage.

Confidence is an evidence score. It was evaluated without changing any threshold or review decision. For recovery predictions, semantic, domain and privacy correctness AUCs were 0.948, 0.351 and 0.831 across all fields. Joint correctness AUC improved from 0.628 to 0.650 across all fields when using the minimum component score. Among automated decisions it declined from 0.418 to 0.337. The 0.65–0.8 joint bin had 21 correct automated decisions among 33, while the 0.8–0.9 bin had six among 15. The scores are diagnostic and are not calibrated probabilities.

Only recovery and failure telemetry were promoted. Person anchors, default domains and review thresholds were preserved. The graph and confidence experiments are kept in evaluation code. The original source copies retained under `data/groq_architecture_holdout/evaluated_sources` match the historical seal. The 85% release gate remains unmet.

