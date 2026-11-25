# Native platform adoption evaluation

Neither native workflow met the release target. Metacrafter and DataHub completed the same three synthetic databases locally. The benchmark artifacts contain native datatype or glossary-term identifiers, expected labels, and aggregate metrics. The project did not promote either workflow to the production classification path.

## Measured results

| Metric | Metacrafter 2.0.0 | DataHub 1.6.0.5 |
|---|---:|---:|
| Fields evaluated | 106 | 106 |
| Exact semantics across all fields | 47.2% (50/106) | 27.4% (29/106) |
| Fields with a mapped semantic result | 48.1% (51/106) | 28.3% (30/106) |
| Accuracy on mapped results | 98.0% (50/51) | 96.7% (29/30) |
| Expected semantic labels outside the crosswalk | 40 fields | 69 fields |
| Direct PII precision | 87.5% (7/8) | 80.0% (4/5) |
| Direct PII recall | 63.6% (7/11) | 36.4% (4/11) |
| Direct PII F1 | 73.7% | 50.0% |
| Overall personal-data F1 | 23.9% | 12.7% |
| Person-linked data F1 | 0.0% | 0.0% |
| Domain grouping F1 | Unavailable | Unavailable |
| Automated joint coverage | 0.0% | 0.0% |
| Native workflow time for all three databases | 11.0 s | 32.2 s |

Runtime covers the native commands, including process startup, on the same Windows host. It excludes setup and artifact scoring. The SQLite and PostgreSQL connectors received equivalent schemas and values. DataHub's report confirmed 15 classification attempts, no failed tables and no recognizer exceptions.

| Database | Fields | Metacrafter exact | DataHub exact | Metacrafter direct PII recall | DataHub direct PII recall |
|---|---:|---:|---:|---:|---:|
| Arts grants | 36 | 47.2% | 30.6% | 33.3% | 66.7% |
| Community care | 35 | 45.7% | 28.6% | 66.7% | 66.7% |
| Freight brokerage | 35 | 48.6% | 22.9% | 80.0% | 0.0% |

An oracle selecting the better existing output for every individual field would reach 52/106 exact matches (49.1%). A union of the direct PII outputs would catch 9/11 positives (81.8% recall) with one false positive. These are diagnostic bounds on the observed outputs. Both products discovered the 15 primary keys and 10 foreign keys. Neither inferred privacy linkage for the 47 person-linked fields. Both flagged a business reference string stored in a misleadingly named field. Metacrafter called it an email, and DataHub called it a phone number. Both missed the phone field labeled `signal_2`.

### Scoring protocol

The three project-authored databases contained 15 tables with 64 synthetic rows per table. The manifest hashes the SQLite copies, PostgreSQL load scripts, and separate ground truth. Inputs and platform settings were sealed before native inference, and both tools ran with the same settings across their three databases. All expected fields stay in the exact score. The classifiers receive database connections and upstream settings. Their runtime receives no evaluation labels.

Semantic types are projected from native labels when their meanings match a documented benchmark type. The native primary and foreign key flags count toward the corresponding semantic roles. A column with only a generic storage type receives no semantic credit. The personal-data score uses the reported privacy tags against both direct and person-linked truth. Direct PII counts only native direct identifier types. An unavailable domain assignment gives zero joint coverage and leaves domain F1 undefined.

The first Metacrafter crosswalk omitted the registry's surname, Saudi Iqama, United States city, and comment types. Its archived result was 43.4% exact accuracy and 45.5% typed direct PII recall. The corrected crosswalk maps those meanings explicitly. The native results, privacy flags, and frozen labels were verified identical across both passes. The aggregate count of native PII flags stays unchanged. [APICrafter datatype registry](https://registry.apicrafter.io/)

## Platform fit

**Metacrafter** ran the upstream SQL command against read-only SQLite, using its bundled offline rule pack and registry. It provides semantic tags, key evidence, rule IDs, and confidence. Most benchmark business semantics remained outside its mapped output. Its SQL workflow emitted no domain memberships or specialist approval history. [Native SQL workflow](https://apicrafter.github.io/metacrafter/commands/scan-sql)

**DataHub** ran the upstream PostgreSQL ingestion workflow with stock classification, local profiling, and a file sink. The last release that ships the stock classifier is 1.6.0.5. Current DataHub requires a separately registered classifier. The Windows build of SQLGlot's C accelerator failed, so the pilot used the same pinned SQLGlot release in pure Python. [PostgreSQL connector](https://docs.datahub.com/docs/generated/ingestion/sources/postgres) · [Classifier removal and legacy release](https://github.com/datahub-project/datahub/blob/master/metadata-ingestion/docs/dev_guides/classification.md)

**OpenMetadata** supports catalog ownership, governance tasks, domain descriptions, profiling, quality and lineage. Its native Auto-Classification workflow assigns PII sensitivity tags. The documented domain workflow assigns assets to configured domains. Both are relevant to Elm, but the native classification workflow could not be measured on this host. Docker Desktop returned HTTP 500 from its Linux engine, WSL was absent, and the two standalone release downloads timed out before completing. [Native Auto-Classification](https://docs.open-metadata.org/v2.1.x/how-to-guides/data-governance/classification/auto-classification) · [Catalog capabilities](https://docs.open-metadata.org/v1.12.x/how-to-guides/data-discovery/details) · [Domain workflow](https://docs.open-metadata.org/v1.12.x/how-to-guides/data-governance/domains-%26-data-products/domains) · [2.1.1 release](https://github.com/open-metadata/OpenMetadata/releases/tag/2.1.1-release)

Microsoft Purview and Google Sensitive Data Protection have documented database discovery or inspection workflows. They remain documentation-only comparisons because local testing had no approved tenant or deployment. Macie was screened out because its managed discovery targets S3 objects and would need a staging export. No vendor documentation was used as a comparative accuracy result. [Purview connectors](https://learn.microsoft.com/en-us/azure/purview/microsoft-purview-connector-overview) · [Google discovery and inspection](https://docs.cloud.google.com/sensitive-data-protection/docs/learn-about-your-data) · [Macie discovery scope](https://docs.aws.amazon.com/macie/latest/user/data-classification.html)

For Elm Challenge 1, the pilots verified source identification, read-only access, field inventory and declared relationships. Automatic grouping, field-to-domain reasoning, domain descriptions, practitioner review and quality-aware recommendations still require a validated platform workflow. OpenMetadata is a candidate for the governance layer. Its classification and those remaining capabilities require a runnable deployment before adoption.

## Reproduction on Windows

From a fresh project environment with Python 3.11, install the pinned native packages and materialize Metacrafter's bundled assets.

```powershell
python -m pip install --target .deps/metacrafter-experiment -r evaluation/requirements-metacrafter.txt
python -m evaluation.metacrafter_setup
python -m venv .deps/platform-datahub
.deps/platform-datahub/Scripts/python.exe -m pip install -r evaluation/requirements-platform-datahub.txt
python -m evaluation.platform_fixtures
python -m evaluation.platform_adoption freeze-metacrafter
python -m evaluation.platform_adoption freeze-datahub
python -m evaluation.platform_adoption metacrafter
.deps/platform-datahub/Scripts/python.exe -m evaluation.platform_postgres start
$env:NATIVE_CATALOG_POSTGRES_PASSWORD = [IO.File]::ReadAllText((Resolve-Path .deps/platform-adoption/fixture-reader.pw).Path)
python -m evaluation.platform_adoption datahub
Remove-Item Env:NATIVE_CATALOG_POSTGRES_PASSWORD
python -m evaluation.platform_postgres stop
```

The PostgreSQL loader verifies the published binary SHA-256, binds to loopback, and uses separate randomized owner and read-only ingestion credentials. The evaluation disables DataHub telemetry. Native JSON is filtered before persistent benchmark export. The DataHub file sink writes only to a temporary local directory for this synthetic evaluation. View pooled and per-database scores at `data/platform_adoption/<platform>/metrics.json`, field-level labels and output at `fields_with_truth.json`, and the first Metacrafter mapping at `data/platform_adoption/metacrafter_first_pass/metrics.json`. The installed distributions retain their upstream notices. [Metacrafter license](https://github.com/apicrafter/metacrafter/blob/main/LICENSE) · [DataHub license](https://github.com/datahub-project/datahub/blob/master/LICENSE) · [Zonky portable PostgreSQL binaries](https://github.com/zonkyio/embedded-postgres-binaries)
