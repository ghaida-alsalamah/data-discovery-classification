# Domain definitions and database-first evaluation

## What the sealed labels measure

The reliability taxonomy has named broad business domains and a fixed parent mapping for its closed label set. The later independent fixturing scripts instead assign an open operational group to each table and copy it to its fields. They intentionally distinguish grouping from semantic type and privacy. The newer fixtures do not define a consistent parent taxonomy or a shared annotation rule for granularity. Their labels mix entities (holders and suppliers), workflows (bookings and service), data subjects (staff), and organizational purposes (oversight or compliance).

This creates two kinds of disagreement. Suppliers merged with equipment and claims assigned to an asset catalog are clear scope errors. Grouping guests and bookings under hospitality is defensible as a broad parent, while the sealed leaf labels require them to be separate. Treating a landing document as part of the haul lifecycle is plausible in a process view, while the ground truth treats it as a distinct compliance purpose. Neither example changes the sealed labels, official memberships, or the 0.85 per-field joint threshold.

Elm Challenge 1 asks for meaningful groups with boundaries, relationships and explanations. A hierarchy can provide those views if the catalog explains the level and supports specialist review. The current evaluation directly measures the leaf partition. It does not adjudicate broad parent groups because the open-domain fixtures have no separately sealed parent labels. The experiment exposes parents as diagnostics and scores only leaf membership. Its leaf assignments are table-level, so it does not establish correctness for mixed-purpose tables.

## Linkage root causes

The recovery comparison recorded 23 linked true positives and seven misses in both runs. False positives rose from four to five. The extra false positive was an issuance date in a landing-compliance record. There was a fully measured two-hop path through the haul and its skipper, and the model called the date linked. The path proves traceability to a staff member. The field describes a compliance record, and the annotation treats the skipper as an operational participant rather than the subject.

The other four false positives shared that ownership problem. Two were attributes of the haul and two were indirect references to it. The seven false negatives were one unresolved hometown, two unresolved booking attributes, three free-text attributes with unresolved scope, and one payment method marked nonpersonal. The relevant person and process relationships existed in the schemas. No missed foreign key or incorrect anchor was identified as the direct cause of the decline. The field evidence is in `data/groq_architecture_holdout/domain_linkage_audit.json`. Direct PII precision and recall logic were left unchanged.

## Domain confidence

The direction of the ROC AUC calculation is correct. Higher scores are compared with lower scores using membership correctness under the original evaluator, including half credit for ties. The scores weight assignment methods. A verified edge shows that a join is possible and does not establish the purpose of a cluster. A semantically reliable field can still belong to a wrongly split or merged group. The grouping correctness label depends on the full predicted cluster rather than the strength of a single local cue.

On the preserved recovery run, domain score bins showed 14/19 correct at 0.40–0.64, 20/22 at 0.65–0.79 and 20/43 at 0.80–0.89. The 0.351 AUC reflects a ranking failure, not a sign error. Reversing the score after seeing this holdout would not establish generalization. No domain score was combined with other confidence scores for production decisions.

## Database-first experiment

The experimental provider sees an allowlisted schema graph, column storage types, primary keys, and verified links. It proposes broad and leaf partitions before field classification. Declared joins, terminology and table boundaries remain evidence rather than standalone acceptance conditions. Strictly validate partition representatives and nesting and retain the prior grouping on failure. The test compares the production pass with the leaf partition on identical real field responses. Production recovery, person anchors and review thresholds remain unchanged.

The separate development run improved grouping F1 from 82.4% to 100% on the education fixture and declined from 100% to 88.1% on community care. A third response did not pass hierarchy validation, so its prior grouping was preserved. Three Groq Free calls took 19.1 seconds and returned 1,930 input and 1,293 completion tokens.


## Fresh sealed comparison

The holdout covered 86 fields in three new schemas. Both paths used the same field responses. One field batch was split and all 17 affected fields were recovered, leaving no final field fallback. Leaf assignments used the original grading.

| Metric | Production grouping | Database-first hierarchy |
|---|---:|---:|
| Exact semantic accuracy | 86.0% | 86.0% |
| Broader semantic accuracy | 87.2% | 87.2% |
| Literal domain label accuracy | 0.0% | 0.0% |
| Domain membership F1 | 87.6% | 91.2% |
| Direct PII precision | 83.3% | 83.3% |
| Direct PII recall | 83.3% | 83.3% |
| Overall personal-data F1 | 68.4% | 68.4% |
| Person-linked F1 | 61.5% | 61.5% |
| Automated joint accuracy | 50.0% | 52.4% |
| Correct automated decisions | 21 / 42 | 22 / 42 |
| Automated coverage | 48.8% | 48.8% |

The experiment improved grouping F1 on medical equipment dispatch from 73.7% to 91.0%, declined on building access from 100% to 91.4%, and used the production grouping on translation services after validation failed. The two accepted outputs assigned every table a singleton at both levels. The observed gain is therefore an improvement in partition granularity in one schema rather than evidence that a business hierarchy was learned. High-confidence semantic errors were 0 of 23 in both runs.

The production run used 11 requests and 12,116 returned tokens. Scanner time was 155.9 seconds. The hierarchy added three live calls with 3,393 returned tokens and took 31.0 seconds end to end with field inference replayed. The 22.4 seconds measured for its live requests excludes the shared field inference. Comparisons and the separate development run stayed at $0 on Groq Free.

On the fresh baseline, domain score ROC AUC was 0.219 across all fields and 0.192 among automated fields. With hierarchy assignments, the same evidence score reached 0.460 and 0.367 respectively. These scores are uncalibrated and neither result supports a production confidence gate. Separate confidence outputs are retained, and review decisions were not changed to obtain the results.

The experimental pass was not promoted. It improved one correct automated decision at fixed coverage but did not generalize consistently across the three schemas. No production engine files were changed for this investigation. The original run configuration, per-field outputs and results are in `data/groq_hierarchy_holdout`. The exact evaluated runner is retained alongside the seal. The current evaluation runner emits only separate component diagnostics. The full existing test suite passed 69 tests.

