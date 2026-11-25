# Person-anchor dependency verification

The earlier relationship graph depended on a final verified person-name classification to establish many person anchors. The revised scanner can establish an additional anchor from a keyed entity, a verified inbound relationship, a name hypothesis corroborated by its local profile, and two different locally validated identifier types. Known organizations and shared mailbox signals bar the alternative path. Existing confirmed paths take precedence. Fully measured reference links can be automatic. Non-key attributes supported only by the additional path remain reviewable.

## Independent paired comparison

The sealed benchmark contains 104 fields in four fresh synthetic schemas. The same live Groq responses were used for both logic paths. The comparison disables only the added anchor mechanism for the baseline. Prompts, direct PII decisions, semantic classification, domain grouping and metrics were shared.

| Metric | Previous logic | Additional anchors |
|---|---:|---:|
| Exact semantic accuracy | 84.6% | 84.6% |
| Domain grouping F1 | 76.8% | 76.8% |
| Direct PII precision | 89.5% | 89.5% |
| Direct PII recall | 94.4% | 94.4% |
| Overall personal-data F1 | 81.9% | 87.3% |
| Person-linked F1 | 76.5% | 84.9% |
| Automated joint accuracy | 32.7% | 34.0% |
| Automated coverage | 52.9% | 51.0% |

Two recovery anchors affected the municipal services and freight audit schemas. Person-linked true positives increased from 26 to 31, false negatives fell from 16 to 11, and neither path produced a person-linked false positive. Both paths made 18 correct automated decisions. The rate difference comes from the candidate automating 53 fields compared with 55 in the baseline.

The live run took 122.01 seconds. Nine Groq Free requests used 6,365 input and 5,255 completion tokens at $0. One field batch failed and 16 fields fell back in both paths. Replay made no additional cloud calls. The benchmark artifacts, including dataset and configuration fingerprints, are in `data/groq_anchor_holdout`. To reproduce in a clean output directory, run the `prepare`, `freeze` and `run` actions in `evaluation.groq_anchor_holdout`.

The regression test simulates an unverified person-name field and verifies that two relationship hops remain discoverable while an inferred downstream attribute retains specialist review.

