# Targeted catalog verification

## Domain definition and naming

A domain is a coherent group of fields serving a declared information purpose. The annotation guide distinguishes this purpose and its level of detail from entity identity, personal subject, and workflow. The new benchmark uses leaf operational purpose. Existing labels and scoring are preserved. No older benchmark was relabeled or pooled with the new benchmark.

The prior production comparator returned zero literal title matches on 86 fields. A diagnostic compared sets of field memberships and found 52 fields in groups with an exact membership match under different names. All 28 building access fields had identical memberships, with five renamed groups. The other 34 fields had grouping differences. Examples include an inventory group labeled by its premise entity and a registry labeled by its occupant entity. Literal scores measure exact string identity. They do not establish whether generated descriptions are correct. The older ground truth does not include authored descriptions, so description quality could only be reviewed qualitatively. The detailed name and membership audit is under `data/groq_hierarchy_holdout/literal_domain_name_audit.json`.

## Targeted verifier

The experiment reviews a bounded set of ambiguous privacy decisions and connected domain pairs from the production catalog. It receives opaque IDs, allowlisted hints, recognized types, the proposed groups, and verified relationship paths. It distinguishes a subject from a participant, an independent process, or unclear ownership. It can recommend retaining a decision, correcting it, or asking for review. A correction requires structured output and separate local support. Shared model conclusions alone are insufficient. Direct PII is outside its correction scope.

The production classification, relationship recovery, domain assignment, and person-anchor code remain unchanged. No review flag is altered in the comparison. Recommendations are measured separately to avoid manufacturing accuracy by reducing coverage. The verifier output is experimental field data, and the experiment does not regenerate the complete production catalog or explanations.

The development check uses saved production field decisions from three earlier development schemas. The final comparison uses the same live baseline field responses for both paths, including any recovery or fallback. It adds at most one focused verifier call per selected schema. Details of which fields were accepted or recommended for review are in the development and final outputs.


## Results

The original response contract failed validation on all three development schemas after six requests. An explicit JSON contract returned usable decisions in all three development requests, but made no change to correct automated counts on the 94 development fields. The original final runner hit a verifier name collision after saving the production baseline. The collision was corrected for future runs. The explicit-contract evaluator was sealed separately and reused the hash-verified baseline decisions with no repeat field calls or edits to the fixture labels.

The new purpose-standardized benchmark contains 93 fields in three synthetic databases.

| Metric | Production | Explicit verifier |
|---|---:|---:|
| Exact semantic accuracy | 84.9% | 84.9% |
| Broader semantic accuracy | 88.2% | 88.2% |
| Literal domain accuracy | 0.0% | 0.0% |
| Domain membership F1 | 85.2% | 87.0% |
| Direct PII precision | 92.3% | 92.3% |
| Direct PII recall | 100.0% | 100.0% |
| Overall personal-data F1 | 74.0% | 74.0% |
| Person-linked F1 | 62.5% | 62.5% |
| Automated joint accuracy | 43.5% | 43.5% |
| Correct automated decisions | 20 / 46 | 20 / 46 |
| Automated coverage | 49.5% | 49.5% |

The verifier moved five domain memberships in regional health transport and made no supported privacy corrections. Domain F1 was 73.8% in equipment leasing, 77.8% → 84.6% in regional health transport, and 100% in aquaculture supply. Correct automated decisions were unchanged in all sectors, at 5/16, 6/17, and 9/13 respectively. Equipment leasing was the lowest on joint accuracy and person-linked F1 at 31.2% and 46.2%.

The verifier recommended privacy review on 13 fields and domain review on 16, including four automated fields. Review recommendations were recorded without changing the automated cohort. Verifier evidence ranked joint correctness with AUC 0.487 across the 46 automated fields compared with 0.438 for existing semantic confidence. Across all fields the AUC dropped from 0.619 to 0.596. The strongest corroboration bin had one correct result among three automated fields. This is insufficient evidence for a confidence gate or calibrated probabilities.

The production scan used seven calls and 10,901 returned tokens, took 100.1 seconds of scanner time, and completed all 60 routed fields without fallback. The verifier used three additional calls, 3,839 returned tokens, and 26.2 seconds elapsed, with zero request failures. All live calls used Groq Free at $0. The existing suite passed 69 tests. The candidate remains evaluation-only because it did not improve correct automated decisions or linkage. No production scanner or Phase 4 files were changed.

