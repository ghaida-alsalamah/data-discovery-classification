# Domain annotation guidelines

Elm Challenge 1 asks the catalog to group fields by a meaningful subject or purpose and explain the boundaries, relationships, and uses of each group. For future benchmark annotations, a **domain** is a group of fields that supports a coherent operational information purpose at a declared level of detail. A business purpose explains why the information is maintained. An entity identifies what a record represents. A data subject identifies the person or organization the information is about. A workflow describes how records progress through an activity. These are evidence for a domain decision and can cross domain boundaries.

## Annotation procedure

1. Define the benchmark level before inspecting scanner outputs. Use the leaf operational purpose as the primary membership level. Record optional parent groups as separate supplemental labels.
2. For each leaf, write a short purpose, an inclusion rule, an exclusion rule, and one example of a nearby but distinct purpose. Use stable IDs for scoring and readable names for presentation.
3. Label fields by the purpose they serve in their record. A table can contain multiple domains when fields serve genuinely distinct purposes. A foreign key links purposes and does not by itself merge them. A process header, history, and dependent charges can share a leaf when they describe the same lifecycle. Keep independent registries, inventory, and oversight separate when they are maintained for different purposes.
4. Record person reachability, subject role, and field attribution separately. An employee who performs a task can be identifiable in the employee reference without being the subject of the entire operational record.
5. Record alternative plausible groupings and uncertain fields for reviewer adjudication before sealing. Use independent reviewers when available and preserve disagreements. Freeze labels, evidence, annotation level, and scoring configuration before any final inference. Keep naming, descriptions, and membership as separate quality questions.

The existing sealed benchmarks retain their labels, thresholds, and metrics. The verifier holdout is reported separately under these guidelines. Its synthetic labels were authored with the fixture, without independent reviewer adjudication. Parent groups and descriptions are not scored by the original membership metric.

