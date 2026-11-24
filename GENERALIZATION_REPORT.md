# Independent generalization evaluation

The frozen hybrid engine fell from **94.8% to 57.1% exact semantic accuracy** and from **98.5% to 40.3% personal-data F1**. It still outperformed the existing name-only baseline. Its review flag caught many errors, but only **18 of 56 unreviewed holdout fields** were correct across semantics, domain, and known personal status under the open-set scoring policy.

## Design and scoring

The benchmark uses 168 columns across 12 tables in three independently generated healthcare, e-commerce, and education SQLite databases. The fixture author used the published taxonomy and synthetic business definitions. The databases use seeds 91823, 47051, and 68257. The [fixture generator](evaluation/fixtures.py) uses the standard library and has no application imports. The three dictionaries and all databases were written and SHA-256 sealed before running inference. The holdout deliberately includes unusual Arabic names, ambiguous and misleading columns, identifier-shaped business codes, malformed data, mixed domains, and unsupported types. It is a synthetic, single-author stress test, so its percentages do not estimate production performance.

The [inference runner](evaluation/infer.py) accepts only databases, checks that the evaluated source paths match revision `dd58a8c`, and uses the same MiniLM, Presidio, 500-value sampling limit, and default thresholds for every database. The model and tokenizer hashes, package versions, and input hashes are recorded in provenance. The separate [scorer](evaluation/score.py) verifies the sealed fixtures and loads the labels after prediction. The original demo was rerun through this same inference and scoring path. Two paired e-commerce perturbations were reserved for Phase 3 checks and excluded from the 168-field metrics.

Strict exact scoring preserves all labels, so unsupported types and domains cannot score a literal match. Open-set scoring maps unsupported truth to `unknown` and still penalizes unsupported fields guessed as known types. The category score merges only relationships defined by the frozen taxonomy and uses the same open-set policy. We report supported-known accuracy separately in the machine-readable output. Uncertain personal truth is excluded from the binary metrics (10 holdout fields). Only `yes` predicts positive. A prediction of `uncertain` on a known personal field is a false negative. For joint accuracy, uncertainty on any known personal truth is an error, while genuinely uncertain truth is skipped for that dimension.

## Results

Percentages are micro-averaged by field in the combined rows. Personal metrics are precision, recall, and F1 in that order.

| Dataset | Engine | Fields | Strict exact | Open-set exact | Broader | Strict / open domain | Personal P / R / F1 | Personal FP / FN |
| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| Original demo | Baseline | 58 | 65.5 | 65.5 | 74.1 | 3.4 / 3.4 | 100.0 / 15.6 / 27.0 | 0 / 27 |
| Original demo | Hybrid | 58 | 94.8 | 94.8 | 100.0 | 100.0 / 100.0 | 97.0 / 100.0 / 98.5 | 1 / 0 |
| Healthcare | Baseline | 56 | 21.4 | 33.9 | 33.9 | 0.0 / 73.2 | 66.7 / 5.4 / 10.0 | 1 / 35 |
| Healthcare | Hybrid | 56 | 60.7 | 71.4 | 71.4 | 0.0 / 73.2 | 81.8 / 24.3 / 37.5 | 2 / 28 |
| E-commerce | Baseline | 56 | 26.8 | 32.1 | 35.7 | 5.4 / 5.4 | 33.3 / 4.3 / 7.7 | 2 / 22 |
| E-commerce | Hybrid | 56 | 60.7 | 64.3 | 67.9 | 23.2 / 23.2 | 66.7 / 34.8 / 45.7 | 4 / 15 |
| Education | Baseline | 56 | 26.8 | 41.1 | 42.9 | 0.0 / 69.6 | 100.0 / 6.2 / 11.8 | 0 / 30 |
| Education | Hybrid | 56 | 50.0 | 58.9 | 62.5 | 23.2 / 92.9 | 64.3 / 28.1 / 39.1 | 5 / 23 |
| Combined | Baseline | 168 | 25.0 | 35.7 | 37.5 | 1.8 / 49.4 | 62.5 / 5.4 / 10.0 | 3 / 87 |
| Combined | Hybrid | 168 | 57.1 | 64.9 | 67.3 | 15.5 / 63.1 | 70.3 / 28.3 / 40.3 | 11 / 66 |

| Additional measure | Baseline | Hybrid |
| --- | ---: | ---: |
| Ambiguous names, strict exact (37 fields) | 21.6% | 54.1% |
| Misleading names, strict exact (9 fields) | 0.0% | 55.6% |
| Supported-known exact (141 fields) | 26.2% | 64.5% |
| Open-set unknown precision / recall / F1 | 19.2% / 85.2% / 31.3% | 29.0% / 66.7% / 40.4% |
| Native unknown recognized (6 fields) | 5/6 | 5/6 |
| Unsupported semantic types abstained (21 fields) | 18/21 | 13/21 |
| Human review rate | 78.6% | 66.7% |
| Unreviewed semantic accuracy, open set | 77.8% (28/36) | 85.7% (48/56) |
| Unreviewed joint accuracy, open set | 11.1% (4/36) | 32.1% (18/56) |

The hybrid had 62 unknown predictions, including 44 supported fields. Its 66 personal-data false negatives included 49 marked uncertain and 17 marked no. The strict semantic confusion matrix shows all eight business-identifier fields classified as Saudi residency IDs. As a result, residency-ID recall was 3/3, while precision was 3/11. All 12 primary keys were recognized and six of seven reference identifiers were recognized. Full confusion matrices, per-class precision/recall/F1 and support, false-positive and false-negative field lists, and sector-specific review and unknown metrics are in `data/generalization/metrics.json`.

## Confidence and missed review

Correct open-set semantic classifications averaged **0.770** confidence versus **0.302** for errors (medians **0.974** and **0.124**). The highest score band still had 11 semantic errors. The 0.40–0.60 band had only three observations. These scores are heuristic and the empirical bands are descriptive.

| Confidence | Fields | Open-set semantic accuracy |
| --- | ---: | ---: |
| 0.00–<0.40 | 62 | 29.0% |
| 0.40–<0.60 | 3 | 100.0% |
| 0.60–<0.70 | 10 | 80.0% |
| 0.70–<0.85 | 17 | 88.2% |
| 0.85–1.00 | 76 | 85.5% |

Examples include healthcare `خدمات_المختبر.batch_ref` (business identifier → residency ID, 0.9125, no review), education `attendanceLog.workstation` (business identifier → residency ID, 0.9057, no review), and e-commerce `accountsDirectory.code_or_email` (mixed/unknown → email, 0.9281, no review). E-commerce `orders.amount` received 0.9817 for generic financial amount instead of transaction amount, but was flagged for review. Among unreviewed fields, 38 had at least one scored error, 29 of them with confidence at or above 0.85. The joint count includes domain errors and does not equate them with personal-data misses.

## Leakage and bias audit

- **No label access found in classification or intelligence.** The demo pipeline creates the database and labels together, then classification consumes schema and profiles. The original evaluation script reads the label file separately. No literal lookup of `f01`, `x2`, `attr_03`, `ref_code` or `region_code` was found in the evaluated engines. The production demo CLI depends on the original generator for its source, but the engine APIs work against external schema and profiles. The generator defines the original truths and difficulty tags alongside the fixtures, so this audit cannot rule out prior human adjustment against that benchmark. [Pipeline](scripts/run_pipeline.py#L23) · [Demo field definitions](backend/app/models/synthetic.py#L38) · [Original evaluator](scripts/evaluate.py#L66)
- **Demo-aligned rules and domain granularity matter.** Alias matching and generic context rules favor names such as `name` in a catalog and `amount` or `status` in finance and commerce. The seven supported domains match the demo's sector vocabulary. The classifier assigns the same domain to every column of a table. The grouping engine can accept genuinely mixed field domains, but the end-to-end classifier supplied none on these holdouts. Finance fields in otherwise commerce tables were missed. Person-link logic also depends on recognizable domains, helping explain why dated, linked healthcare and educational records could be treated as uncertain or non-personal. [Taxonomy](backend/app/classification/taxonomy.py#L15) · [Domain inference](backend/app/classification/engine.py#L118) · [Context rules](backend/app/classification/engine.py#L178) · [Personal status](backend/app/classification/engine.py#L66)
- **Abstention exists, but strong-looking evidence can force a specific result.** The main score threshold can return unknown, yet format votes are large and Presidio reuses the detector patterns. Structural matches contribute even with failed checksums. Conflicts and small margins influence review but do not necessarily trigger semantic abstention. Checksum warnings and unknown domain do not themselves force classifier review. That combination explains confident calls on synthetic lookalike codes and mixed fields. [Presidio patterns](backend/app/classification/ai_evidence.py#L25) · [Format votes](backend/app/classification/engine.py#L159) · [Selection and review](backend/app/classification/engine.py#L229)
- **The original arithmetic reproduced, but its coverage overstates generality.** Exact coverage is checked and the original personal-data evaluator treats uncertain as a miss for positive truth. Broader labels collapse distinctions, and the demo has no native unknown or unsupported semantic fields, only five hand-tagged difficult columns, and mostly one domain per table. The name-only domain baseline uses column names; the hybrid also receives table names, values, embeddings, and relationships. The comparison measures the combined benefit of those inputs and cannot isolate the benefit of the model. [Original metrics](scripts/evaluate.py#L19) · [Name-only baseline](backend/app/classification/engine.py#L98)

## Phase 3

End to end, each holdout produced one opportunity requiring review and seven with insufficient prerequisites. No ready opportunity had missing prerequisites or unverified required joins. The frozen domain grouper assigned all healthcare fields to unknown, recognized commerce for one e-commerce table, and workforce for one education table. It reported 66 healthcare, 62 e-commerce, and 71 education issues, including two orphaned healthcare relationships with eight orphans each and one educational relationship with 13 orphans. The undeclared educational course link had no integrity check. Both e-commerce variants retained the end-to-end insufficient status for demand and trends because the required semantic subtype was already missing on the clean run.

A separate [Phase 3 control](evaluation/phase3_check.py) sent verified semantic inputs directly to the downstream API. It did not call classification, and its results were excluded from the benchmark. This confirmed mixed field-domain grouping and isolated readiness changes. Clean service demand and transaction trends were ready. Both changed to preparation or review after damage. Service demand became insufficient when its catalog relationship was removed. The stressed fixture measured 138 missing amounts and 87 missing dates in 383 orders, 74 invalid dates in 296 examined non-null dates, and 76 orphaned catalog references among 383 orders. The checks passed with Phase 3 deterministic mode. Remote reasoning was outside this evaluation. [Readiness prerequisites](backend/app/intelligence/opportunities.py#L129) · [Integrity check](backend/app/intelligence/quality.py#L144)

## Recommendations

1. Add field-level domain inference and an explicit unknown or mixed-type class. Evaluate sector-aware vocabulary and linkage rules separately.
2. Separate correlated pattern votes, incorporate validity and competing identifier interpretations into review, and treat unknown domain as meaningful uncertainty. Measure missed review across all dimensions.
3. Make opportunity requirements distinguish broad semantic evidence that is actionable from exact subtypes that need confirmation. Test false readiness as well as missed opportunities.
4. Reserve a new unseen holdout with multiple labelers, short ambiguous identifiers, and varied enterprise schemas before adjusting rules or thresholds. Keep this dataset as a regression set after tuning.

## Reproduction

From the repository with the Phase 3 dependencies and local MiniLM model installed, regenerate the original demo via the existing offline pipeline if its files are absent. Use an empty evaluation directory because the fixture and inference writers refuse to overwrite an existing run.

~~~sh
python -m evaluation.fixtures data/generalization
python -m evaluation.infer data/generalization/predictions data/synthetic.sqlite data/generalization/databases/healthcare.sqlite data/generalization/databases/ecommerce.sqlite data/generalization/databases/education.sqlite data/generalization/databases/ecommerce_stress.sqlite data/generalization/databases/ecommerce_unlinked.sqlite
python -m evaluation.score data/generalization data/ground_truth.json
python -m evaluation.phase3_check data/generalization
~~~

The generated directory includes fixture databases, separately stored labels, a hash manifest, per-source predictions and Phase 3 reports, `metrics.json`, and `phase3_control.json`. The application code, model configuration, and existing thresholds were left frozen.

---

# Reliability improvement and final holdout

The original evaluation above remains the historical baseline. Healthcare, e-commerce, and education are now **development diagnostics** because their results informed the changes. Neither engine was changed after seeing the separate final holdout results.

## Technical changes

- Candidate scores use the strongest vote within each evidence family. Column text and MiniLM metadata similarity share a family. Presidio's regex counts are displayed as corroborating diagnostics with zero incremental weight. Format and checksum outcomes qualify structural evidence and influence review. The scorer accepts separately identified NER evidence, but this evaluation did not install or run an independent NER model.
- Identifier-shaped values can resolve to a generic Identifier with an uncertain subtype or to a business identifier. Personal identity calls depend on context, and invalid checksums or conflicting interpretations trigger review. Normalization handles Arabic marks and common letter variants, camel case, and reusable metadata abbreviations.
- Domain assignment combines field names, semantic anchors, neighborhood signals, table purpose, declared links, and existing MiniLM embeddings. New sector domains and unresolved domain review are supported. Personal-data decisions distinguish direct identity, entity linkage, and uncertainty.
- Confidence uses distinct evidence families, alternative margins, and conflicts. Unknowns, unresolved domains, uncertain personal classifications, and invalid identity checks can require review. Phase 3 keeps its existing prerequisite, quality, and privacy rules. [Classifier](backend/app/classification/engine.py) · [Metadata context](backend/app/classification/context.py) · [Fixed scoring mappings](evaluation/DOMAIN_SCORING.md)

## Original and development diagnostics

| Dataset | Exact semantic, original → improved | Exact domain, original → improved | Personal F1, original → improved | Automated coverage, original → improved |
| --- | ---: | ---: | ---: | ---: |
| Original demo | 94.8% → 94.8% | 100.0% → 82.8% | 98.5% → 84.8% | 81.0% → 81.0% |
| Healthcare development | 60.7% → 60.7% | 0.0% → 28.6% | 37.5% → 63.0% | 25.0% → 10.7% |
| E-commerce development | 60.7% → 64.3% | 23.2% → 32.1% | 45.7% → 29.6% | 35.7% → 16.1% |
| Education development | 50.0% → 53.6% | 23.2% → 71.4% | 39.1% → 50.0% | 39.3% → 25.0% |

## Final holdout

After implementation and development evaluation, hashes sealed both backend trees. The final generator then authored and sealed 156 labeled fields across 12 tables in logistics, insurance, and hospitality. It uses independent per-field random streams and different schema, value, and relationship generation from the previous fixtures. Both engines received the same read-only databases and model files. Labels were passed only to the scorer. The fixed domain parent mapping was hashed before inference. This is a single-author synthetic benchmark and has no independent human annotation agreement measurement.

| Metric on 156 fields | Original frozen engine | Improved frozen engine |
| --- | ---: | ---: |
| Exact semantic accuracy | 55.8% | 55.8% |
| Shared semantic-category accuracy | 67.9% | 69.9% |
| Exact domain accuracy | 7.7% | 27.6% |
| Predefined hierarchical domain agreement | 7.7% | 27.6% |
| Personal-data precision / recall / F1 | 63.0% / 20.2% / 30.6% | 96.7% / 34.5% / 50.9% |
| Personal-data false positives / negatives | 10 / 67 | 1 / 55 |
| Business identifiers incorrectly marked personal | 10/12 | 1/12 |
| Business identifiers given a Saudi identity subtype | 10/12 | 1/12 |
| Open-set unknown precision / recall / F1 | 15.5% / 100.0% / 26.9% | 16.7% / 100.0% / 28.6% |
| Strict semantic error at confidence ≥0.85 | 3/71 (4.2%) | 0/15 (0.0%) |
| Human review rate | 64.7% | 84.0% |
| Automated coverage | 35.3% (55/156) | 16.0% (25/156) |
| Exact semantics among unreviewed fields | 76.4% (42/55) | 100.0% (25/25) |
| Joint semantic, domain, and personal agreement among unreviewed fields | 9.1% (5/55) | 88.0% (22/25) |

Open-set unknown truth includes genuinely unresolved and unsupported semantic labels under a shared taxonomy. Only the six fields with uncertain personal truth were excluded from the binary privacy metrics. On known personal truth, the improved engine marked 41 of its 55 misses uncertain and 14 non-personal. Its residual business-identifier collision was `guestRegistry.facility_iqama`, predicted as a residency ID at 0.6486 and flagged for review.

| Final sector (52 fields each) | Exact semantic, original → improved | Exact domain, original → improved | Personal F1, original → improved |
| --- | ---: | ---: | ---: |
| Logistics | 48.1% → 48.1% | 0.0% → 3.8% | 25.0% → 30.0% |
| Insurance | 59.6% → 61.5% | 23.1% → 26.9% | 34.6% → 43.1% |
| Hospitality | 59.6% → 57.7% | 0.0% → 51.9% | 28.6% → 69.8% |

Quality and opportunity assessment ran offline on all six runs. The improved engine generated mixed domain groupings in 11 of 12 tables, versus none for the original. Each version marked 21 opportunities insufficient and three as requiring preparation or review. Neither marked any ready, so the final holdout validates conservative rejection but provides no positive end-to-end readiness coverage. Both detected the declared insurance integrity issue. Lower counts of format and checksum findings partly reflect more uncertain semantic outputs, and are not evidence that the data itself improved. Regression tests exercise the existing clean-to-poor readiness transition and missing-join blocking.

Total over three final databases, in one run on the same machine, was 3.39 s versus 3.18 s for classification, 1.82 s versus 2.40 s for discovery and profiling, and 0.05 s versus 0.04 s for Phase 3. Model initialization was 2.99 s versus 3.45 s, measured separately. These timings are descriptive rather than a performance benchmark.

**Verification.** All 36 tests passed, including four new regressions. The prior threshold test now runs on a known-domain fixture because unresolved domain independently requires review. A separate audit checked 1,653 distinct per-field synthetic personal values against both versions’ final exports and found no raw matches. Backend, fixture, model, and mapping hashes were verified after inference.

**Remaining limitations.** Exact semantic accuracy did not improve on the final holdout. The improvement in unreviewed accuracy came with a substantial reduction in automated coverage, and the 0/15 high-confidence error count is based on a much smaller set than the original’s 3/71. Personal recall remained 34.5%, exact logistics domain accuracy was 3.8%, and e-commerce development personal F1 regressed. The next iteration should test stronger evidence for mixed entities and ambiguous linkage, and measure coverage at matched risk on another unseen, independently labeled dataset.

## Reproduction artifacts

The final metrics are in `data/reliability/final_metrics.json`, and the original/development comparison is in `data/reliability/diagnostic_metrics.json`. The same directory stores both engine seals, the archived `dd58a8c` backend, the final hash manifest, separate labels and databases, per-version predictions, model hashes, and per-stage timings.

Use [the inference runner](evaluation/reliability_infer.py) with the archived backend or the improved repository root, a new output directory, the three final SQLite paths in logistics/insurance/hospitality order, and the corresponding `--seal` file. Use [the scorer](evaluation/reliability_score.py) with `--final` for the standard output directories. [The fixture generator](evaluation/final_holdout.py) requires an existing improved seal and refuses to overwrite an existing fixture directory.
