# Relational scanner validation

Run the candidate with `python -m scripts.scan_data_asset source.sqlite catalog.json --engine relational`. The default remains the evidence scanner while the candidate's deployment tradeoffs are assessed. Both modes use the same local MiniLM artifacts and validators, with an offline fallback for the catalog. The candidate adds local compatibility checks and measured multi-hop privacy paths. A matched row count documents partial links without exposing matching keys or source values. The catalog keeps separate review reasons for semantic, domain and privacy decisions.

## Frozen comparison

Use the SQLite Northwind port and three Spider databases from the referenced public sources. Place them in `data/relational_validation` as `northwind.sqlite`, `car_1.sqlite`, `concert_singer.sqlite` and `employee_hire_evaluation.sqlite`. Spider supplies source schemas and values. The semantic, domain and privacy labels are independently authored for this project and do not come from the text-to-SQL benchmark. All discovered table fields are included. [Northwind SQLite port](https://github.com/jpwhite3/northwind-SQLite3) · [Spider benchmark](https://yale-lily.github.io/spider) · [SQLite mirror](https://huggingface.co/datasets/target-benchmark/spider-corpus)

```powershell
python -m evaluation.relational_holdout freeze
python -m evaluation.relational_holdout evaluate
```

Freeze checks label coverage and hashes the inputs, candidate source, evaluator and MiniLM files. Evaluate compares both modes without a dictionary, verifies the seal again, and writes per-database and pooled metrics. Strict exact metrics preserve unsupported labels. The output separately includes supported-type accuracy and unsupported abstentions. Domain grouping uses B-cubed membership F1, with unresolved fields treated as singletons. Automated coverage is the proportion of fields without a review flag. Joint accuracy on those fields follows the existing open-set scoring policy.

The existing read-only catalog workflow still covers asset and ownership, inventory, domains and membership reasoning, domain descriptions and relationships, and quality-aware value and opportunities. The regression suite covers uncertainty, specialist corrections, and privacy restrictions. The repository ships source and annotations. Public database files remain in the ignored local data directory.
