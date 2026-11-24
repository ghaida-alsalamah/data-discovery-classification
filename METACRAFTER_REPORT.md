# Metacrafter comparison

**Recommendation** Keep the current engine as the default. Metacrafter is useful as a local candidate and rule-pack service for reviewer evidence. The tested hybrid did not improve decisions, and standalone Metacrafter had lower coverage and personal-data recall on these databases.

## Setup and evaluation

Installed Metacrafter **2.0.0** on Python 3.11 in an isolated project dependency directory. The experiment used registry snapshot **1.3.0** and bundled rules **v0.0.8** from the wheel, verified offline. Direct imports preserve upstream notices. [Attribution](evaluation/METACRAFTER_ATTRIBUTION.md) · [Python SDK](https://apicrafter.github.io/metacrafter/integrations/sdk) · [Registry](https://registry.apicrafter.io/)

The six previously evaluated sectors were treated as development data (324 fields). The final holdout used 90 fresh fields in utilities, procurement, and community services. The adapter, scoring code, and backend were sealed before fixture generation. Fixtures and labels were hashed before inference, and only the separate scorer loaded labels. All variants used the same read-only databases. Metacrafter ran locally on independently sampled values using the existing 500-value cap. The crosswalk was fixed before holdout generation and only maps compatible labels. A Metacrafter match outside the crosswalk scores as unknown. Shared category scoring follows the existing [fixed mapping](evaluation/DOMAIN_SCORING.md).

## Fresh holdout results

| Metric, 90 fields | Current | Metacrafter | Hybrid |
| --- | ---: | ---: | ---: |
| Exact semantic accuracy | 71.1% | 23.3% | 71.1% |
| Broader category accuracy | 84.4% | 26.7% | 84.4% |
| Exact field-domain accuracy | 24.4% | unavailable (0.0% exact) | 24.4% |
| Personal-data precision / recall / F1 | 100% / 40.0% / 57.1% | 100% / 20.0% / 33.3% | 100% / 40.0% / 57.1% |
| Personal-data false negatives | 21 | 28 | 21 |
| Business identifiers given Saudi identity subtypes | 0/8 | 0/8 | 0/8 |
| Open-set unknown F1 | 50.0% | 17.5% | 50.0% |
| Semantic errors at score ≥0.85 | 0/9 | 0/16 | 0/9 |

Standalone Metacrafter returned no candidate for 72 fields and one top candidate outside the crosswalk. Its per-field PII flags are upstream results. Its domain output is unavailable in the tested SDK path, so comparisons use an unknown domain for those fields. The packages use different heuristic confidence scales, and the high-score denominators are small. The hybrid included seven additional upstream registry candidates and twelve custom Saudi structural matches on the fresh run without changing a semantic prediction. Phase 3 ran on all three outputs. Each marked 21 opportunities insufficient and three for preparation or review. None was ready, so this run offers no positive readiness coverage.

On development data, current / Metacrafter / hybrid exact accuracy was **57.7% / 18.5% / 57.7%**. Personal-data recall was **34.7% / 10.2% / 34.7%**, and personal-data F1 was **51.0% / 18.6% / 51.0%**. Standalone avoided the single Saudi-subtype business-ID error made by both current and hybrid, while missing 158 known personal fields versus 115. The two local Metacrafter scans and registry ranking took about 21.0 seconds across the fresh databases. Current classification took 2.3 seconds after shared profiling.

## Reuse and integration limits

- The experiment reused the bundled registry canonical identifiers, `CrafterCmd.scan_data`, native rule scoring, `registry.identify` ranking, and version-3 structured `FieldReport` output. The custom YAML function rules successfully exposed the existing Saudi structural detectors. Their matches remain hypotheses and contribute no extra correlated votes to the current engine. [Custom rule API](https://apicrafter.github.io/metacrafter/integrations/rules)
- The optional Metacrafter verifier uses the existing `LLM_BASE_URL`, `LLM_API_KEY`, and `LLM_MODEL` configuration. It receives synthetic column handles, allowlisted semantic and domain hints, aggregate distinct counts, and registered candidate descriptions. Raw values, database names, column names, and free-form database metadata are omitted. The response is validated against the candidate-list schema and a failure keeps offline results. **No live provider was configured.** The verifier prompt contract was tested offline, and no model performance is reported. [Upstream verifier](https://apicrafter.github.io/metacrafter/integrations/llm)
- Preserve the current field-domain and privacy models, Saudi validators, Presidio, discovery, profiling, quality, and opportunities. Use upstream registry/rules selectively for explainable alternatives. Collect labeled reviewer decisions before experimenting with promotion of candidates. Compare a live verifier separately on another unseen data set before enabling it by default.

**Verification.** 39 tests passed (36 existing plus three integration tests). The upstream Python rule pack emitted deprecation warnings. An audit checked 2,357 distinct per-column synthetic personal values against fresh exports and found no raw matches. Results are synthetic and do not estimate production recall.

## Artifacts

- `data/metacrafter/development_metrics.json` and `data/metacrafter/fresh_metrics.json` contain sector results, confusion matrices, personal-data miss lists, timings, and provenance.
- `data/metacrafter/fresh/` contains separate SQLite fixtures and labels with a manifest. `data/metacrafter/experiment_seal.json` identifies the evaluated configuration.
- Install via `python -m pip install --target .deps/metacrafter-experiment -r evaluation/requirements-metacrafter.txt`. Use [the runner](evaluation/run_metacrafter.py) with an empty output directory and SQLite input paths. Its `--verify` switch uses the configured provider if present. [The scorer](evaluation/score_metacrafter.py) defines the standard development and fresh output directories, and [the fixture generator](evaluation/metacrafter_holdout.py) requires a seal before it writes data.
