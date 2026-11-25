# Automated decision audit

The frozen person-anchor run made 53 automated decisions on 104 fields. Eighteen were correct on semantic type, domain membership and personal-data status together. The audit considered all 35 incorrect automated decisions with the original scoring protocol.

- 29 had only a domain error, five had a domain and privacy error, and one had only a privacy error. There were no exact semantic errors within the automated errors.
- Of the 34 domain errors, 19 came from a split expected purpose and 15 from a merged purpose. An expected membership domain split into two directory groups. A trade lifecycle split into transaction and payment groups. Some activity, staff and reference tables instead collapsed into the same group. These are membership differences under the original evaluator. They are independent of display wording.
- Privacy errors exposed both missed activity attributes and shared organization contacts incorrectly marked as direct personal identifiers.
- Fallback covered 16 fields. The scanner classified 12 correctly by semantic type, made seven automated decisions and got none jointly correct. On 52 successfully routed fields, 40 semantic types were correct and 10 of 23 automated decisions were jointly correct. On 36 structural fields verified locally, all semantic types were correct and eight of 23 automated decisions were jointly correct. These strata contain different field mixes and do not identify a causal effect of routing.
- Semantic confidence ranked exact semantic correctness well in this sample, with ROC AUC of 0.962. Joint correctness AUC was 0.631 across all fields and 0.433 among automated fields. Scores of 0.95 or higher had 15 of 15 correct semantic labels and one of seven correct automated decisions. High semantic confidence provides little assurance about grouping or privacy. These heuristic scores are not probabilities.

The low joint result follows from the conjunction of three decisions and the stricter grouping test. A field must clear 0.85 membership F1 for its particular group intersection. The aggregate grouping metric averages across fields and can hide wrong clusters. The per-field audit and contingency counts are in `data/groq_anchor_holdout/automated_error_audit.json`. Recreate the audit using `python -m evaluation.automated_decision_audit`.

## Focused change

The revised domain pass uses allowlisted field-purpose hints, locally derived scopes and verified joins. It uses stable partition assignments and avoids combining separate groups merely because their local display labels collide. It can consider compatible directories without a direct foreign key. Cross-scope proposals are split to prevent entity directories from being absorbed into activity records. The person-anchor logic, field inference and review thresholds are unchanged.


## Independent comparison

The fresh holdout contains 114 fields across four databases. Labels and configuration were sealed before inference. The two versions share real field responses, including failures. Each version uses its native domain pass. The candidate did not clear the release criterion.

| Metric | Local only | Previous Groq pass | Candidate Groq pass |
|---|---:|---:|---:|
| Exact semantic accuracy | 75.4% | 80.7% | 80.7% |
| Domain grouping F1 | 87.7% | 88.8% | 87.5% |
| Direct PII precision | 70.6% | 76.2% | 76.2% |
| Direct PII recall | 66.7% | 88.9% | 88.9% |
| Overall personal-data F1 | 56.5% | 80.0% | 80.0% |
| Person-linked F1 | 49.1% | 78.9% | 78.9% |
| Joint automated accuracy | 36.2% | 48.2% | 40.0% |
| Correct automated decisions | 17 / 47 | 27 / 56 | 24 / 60 |
| Automated coverage | 41.2% | 49.1% | 52.6% |

The candidate made two more correct automated decisions in property restoration and five fewer in volunteer transport. The other two databases each had the same correct automated count in both Groq runs. The volunteer transport change split a trip lifecycle between separate groups. Municipal lending and equipment calibration illustrate continued difficulty merging related purposes at the right level.

The live candidate path took 128 seconds and used 10 free API requests with 6,886 input and 4,236 completion tokens. Two failed field batches sent 37 fields to fallback in both comparisons. The comparator made four additional domain calls with two failures and reused the candidate field results. Results are end-to-end and include domain API response variation. Total API cost was $0.

The previous domain pass remains the default. The candidate is available for evaluation through the experimental purpose-domain option. The benchmark source now enables that option explicitly for new runs. Saved metrics and the historical seal in `data/groq_joint_holdout` describe the exact pre-flag snapshot. The release gate remains unmet.

