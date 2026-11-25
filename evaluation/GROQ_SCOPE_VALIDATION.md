# Groq subject-scope validation

The candidate separates contact format from contact ownership, corroborates person and organization roles locally, limits multi-hop attribute classification, and uses a second sanitized schema-wide call to propose domain merges. Domain merges require a verified relationship. The evaluator and thresholds for scoring were unchanged.

## Sealed holdout

The four new English synthetic databases contain 110 fields, including 18 direct identifiers. The comparison uses the same data and no dictionaries. The previous Groq backend was reconstructed in process and matched the earlier seal's hashes. The scanner entry point and evaluator were shared. The previous run fell back on 36 of 72 routed fields after two failed batches. The candidate completed all 72.

| Metric | Local only | Previous Groq | Candidate |
|---|---:|---:|---:|
| Exact semantic accuracy | 79.1% | 82.7% | 83.6% |
| Domain grouping F1 | 94.0% | 94.0% | 93.1% |
| Direct PII precision | 68.4% | 66.7% | 76.2% |
| Direct PII recall | 72.2% | 77.8% | 88.9% |
| Personal-data F1 | 47.1% | 61.9% | 63.8% |
| Person-linked F1 | 29.2% | 55.2% | 50.9% |
| Automated joint accuracy | 50.0% | 52.5% | 54.4% |
| Automated coverage | 52.7% | 53.6% | 51.8% |
| Scan time | 2.57 s | 91.14 s | 110.92 s |

The candidate incurred no failed API calls. Eight free requests used 5,893 input and 5,242 completion tokens. Candidate false positives and false negatives were 5 and 2 for direct PII, 5 and 29 for overall personal data, and 0 and 27 for person-linked data. Of the 26 wrong automated decisions, 18 had a privacy error, 10 a grouping error, and one a semantic error. Fields can fail multiple dimensions.

Per-database metrics, field errors, and the evaluation seal are in the local `data/groq_scope_holdout` directory. To reproduce the candidate in a clean output directory, run `python -m evaluation.groq_scope_holdout prepare`, then `freeze`, then `run`. This requires the configured Groq Free account. The previous engine comparison used hash-verified sources saved under `prior_sources`. All 62 tests passed. The 85% release gate remains unmet, and the candidate is suitable only for assisted evaluation with specialist review.

