# Pretrained classification evaluation

The PII Engineer integration produced identical final decisions to the current engine on the sealed 72-field holdout and added 614 seconds of model inference on the Intel Core i7-1255U. The direct NER model alone missed five of twelve direct identifier fields and marked seventeen other fields as direct. Keep the current engine as the default. The opt-in local scanner preserves discovery, profiling, quality and opportunity assessment and reports direct identifier evidence separately from person-linked data.

| Sealed holdout metric | Current | Current + PII Engineer |
| --- | ---: | ---: |
| Exact semantic accuracy | 59.7% | 59.7% |
| Broader semantic category accuracy | 73.6% | 73.6% |
| Strict field domain accuracy | 29.2% | 29.2% |
| Field domain accuracy with unsupported domains mapped to unknown | 58.3% | 58.3% |
| Direct PII precision / recall / F1 | 90.9% / 83.3% / 87.0% | 90.9% / 83.3% / 87.0% |
| Broad personal precision / recall / F1 | 86.4% / 63.3% / 73.1% | 86.4% / 63.3% / 73.1% |
| Unknown or unsupported type precision / recall | 23.8% / 100% | 23.8% / 100% |
| Review / automated coverage | 80.6% / 19.4% | 80.6% / 19.4% |
| Joint accuracy among automated decisions | 78.6% | 78.6% |
| Strict semantic errors at confidence ≥0.85 | 0 of 6 | 0 of 6 |
| Total scanner time, excluding initialization | 14.8 s | 624.2 s |

The NER scanner used about 1.8 GiB of resident memory during observed Windows runs. Native PII Engineer direct precision, recall and F1 were 29.2%, 58.3%, and 38.9%. Typed recall was 50.0%. It classified meter counts, fees, and rent as phone numbers, and city or division names as person names. The current engine falsely treated a municipal visitor pass as a government identifier. Of the 11 broader personal-data misses, two were direct identifiers and nine were person-linked fields. Three uncertain personal-data labels were excluded from binary metrics.

| Holdout sector | Fields | Exact semantics | Strict field domain | Broad personal F1 |
| --- | ---: | ---: | ---: | ---: |
| Facilities | 24 | 75.0% | 37.5% | 60.0% |
| Library | 24 | 54.2% | 50.0% | 75.0% |
| Municipal services | 24 | 50.0% | 0.0% | 76.9% |

The current engine scored 60.6% exact semantics, 70.0% broader semantics, 33.6% strict domain accuracy, and 52.1% broad personal F1 across 414 historical development fields in nine sectors. DoDuo had 14 mapped exact hits (3.4%) and covered 87 truth fields (16.1% exact on that subset). On the 112-field e-commerce and education diagnostic subset, adding PII Engineer also left exact semantics, domain accuracy, broad personal F1, and direct PII F1 unchanged. Native direct precision and recall were 25.0% and 71.4%. OpenMetadata's standalone comparator on the nine development sectors produced four direct-tag false positives and missed all 52 direct fields under the fixed cutoff. The open-set unknown score excludes unsupported types from exact credit and separately measures abstention. The native benchmark and crosswalk used in scoring are documented in [UPSTREAM_SCORING.md](evaluation/UPSTREAM_SCORING.md).

DoDuo's published VizNet checkpoint predicted all 72 fields using actual sampled cell values and neighboring columns. Only 17 of the 72 truth fields had an exact crosswalk. It got four of those right, for 23.5% accuracy on covered truth and 5.6% across all fields. Broader mapped accuracy was 11.1%. Forty-eight top labels had no exact mapping. Of the 35 predictions with native score at least 0.85, 31 were exact misses under the crosswalk. Some misses are coverage limits, but it also labeled the known category field `division` as `name` at 0.999 and a meter-count field as `status` at 0.993. The model added 35.7 seconds of CPU inference, excluding initialization. DoDuo neither detected Saudi subtypes nor provided field business domains, so its results did not justify replacing the current engine. Replaying both models' saved predictions through the combined merge also left exact semantics, domain accuracy, broad personal F1, and review coverage unchanged. This replay measures decision logic rather than end-to-end runtime.

OpenMetadata's released standalone PII classifier ran with its English spaCy model and the predefined 0.80 direct-tag cutoff. It emitted zero direct labels on the holdout, missing all 12 direct identifiers. It emitted 26 candidate scores before filtering, including name and phone candidates below the cutoff. These heuristic scores can exceed 1.0 and should not be treated as probabilities. This is a measurement of the standalone classifier and experiment policy. The complete catalog tag workflow was outside the run. Its PII layer does not cover the project's semantic or domain taxonomy, so the data do not justify migrating to the complete platform for this task.

The downstream scanner found two tables per sector and raised 27, 27, and 29 quality issues in facilities, library, and municipal services. Each sector rejected seven opportunities for insufficient data and marked one as requiring preparation or review.

The 47 code and privacy tests passed. A literal scan of the three holdout reports for all four completed comparator modes found zero raw strings of at least ten characters among the 1,950 distinct strings counted across the source databases. Model input spans were evaluated locally. The models received no evaluation labels, and saved evidence consists of label names, counts, confidence scores and existing aggregate profiles.

The custom engine checkpoint is `c091bc6` on `checkpoint/custom-classification`. The upstream integration lives on `upstream-classification`. See [installation and reproduction](evaluation/UPSTREAM_RUNBOOK.md) and [implementation and benchmark audit](evaluation/UPSTREAM_FINDINGS.md).
