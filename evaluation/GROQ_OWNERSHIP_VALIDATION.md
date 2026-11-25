# Contact ownership and relationship evidence

The candidate detects shared mailbox aliases locally and provides Groq with coarse, verified relationship evidence. Contact format and subject ownership remain separate decisions. A structurally verified link can support a privacy classification even when the semantic type remains uncertain. The transport now counts field response validation failures. No raw values are sent.

## Independent comparison

Four new synthetic schemas contribute 116 fields. The fixtures, engine, prompt and original scoring protocol were sealed before inference. The previous scanner's reconstructed backend matched its prior seal. Both Groq runs used the same free model and no data dictionary.

| Metric | Local only | Previous Groq | Candidate |
|---|---:|---:|---:|
| Exact semantic accuracy | 76.7% | 81.9% | 81.9% |
| Domain grouping F1 | 92.8% | 90.9% | 93.5% |
| Direct PII precision | 64.3% | 71.4% | 82.4% |
| Direct PII recall | 60.0% | 100.0% | 93.3% |
| Personal-data F1 | 40.0% | 75.2% | 73.6% |
| Person-linked F1 | 26.1% | 70.8% | 65.5% |
| Automated joint accuracy | 59.5% | 60.0% | 75.0% |
| Automated coverage | 31.9% | 43.1% | 37.9% |
| Scan time | 4.53 s | 149.62 s | 112.74 s |

The candidate returned valid decisions for all 74 routed fields. The previous engine used local fallback for 55 of its 74 routed fields. This is an end-to-end comparison. It includes API variation and does not isolate the effect of any one change. The candidate used eight Groq Free requests with zero failures, 6,678 input tokens and 5,181 completion tokens.

The candidate had 3 direct PII false positives and 1 miss. It had 3 false positives and 20 misses for overall personal data and no person-linked false positives with 19 misses. In community press, a missed reader identity coincided with all 10 linked positives being missed. The candidate classified 33 of 44 automated fields correctly on all dimensions. Seven automated errors had a privacy mismatch and six had a group mismatch, with overlap between dimensions.

Run the candidate using the existing Groq Free scanner command. The independent evaluation can be reproduced in a clean output directory with the prepare, freeze and run actions in `evaluation.groq_ownership_holdout`. Outputs and the hash-matched earlier engine sources are in `data/groq_ownership_holdout`. The candidate has not cleared the release targets.

