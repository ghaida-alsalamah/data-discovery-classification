"""Aggregate quality checks against the same read-only source used for discovery."""
from collections import Counter, defaultdict

from sqlalchemy import MetaData, Table, and_, func, select

from backend.app.classification.detectors import PATTERNS
from backend.app.classification.taxonomy import TYPES

DIMENSIONS = ("completeness", "validity", "uniqueness", "consistency", "referential_integrity")
CHECKSUM_TYPES = {"saudi_national_id", "saudi_residency_id", "saudi_iban"}


def verify_relationships(connection, schema, relationships):
    schema_tables = {table['name']: table for table in schema['tables']}
    fields = {(table['name'], column['name']) for table in schema['tables'] for column in table['columns']}
    metadata = MetaData()

    def source(name):
        return Table(name, metadata, autoload_with=connection, resolve_fks=False)

    relationship_checks = {}
    for edge in relationships["edges"]:
        data = edge["data"]
        origin, target = edge["source"], edge["target"]
        source_names, target_names = data["source_columns"], data["target_columns"]
        from_table, to_table = schema_tables.get(origin), schema_tables.get(target)
        if (data["kind"] != "declared" or data.get("target_schema") not in (None, "main")
                or not from_table or not to_table or not source_names
                or len(source_names) != len(target_names)
                or not all((origin, name) in fields for name in source_names)
                or not all((target, name) in fields for name in target_names)):
            relationship_checks[edge["id"]] = {"status": "not_evaluated"}
            continue
        child, parent = source(origin), source(target).alias()
        child_columns = [child.c[name] for name in source_names]
        eligible = and_(*(column.is_not(None) for column in child_columns))
        # Parent on the left preserves its affinity and collation in SQLite comparisons.
        joined = and_(*(parent.c[name] == column for name, column in zip(target_names, child_columns)))
        exists = select(1).select_from(parent).where(joined).correlate(child).exists()
        examined = connection.scalar(select(func.count()).select_from(child).where(eligible))
        missing = connection.scalar(select(func.count()).select_from(child).where(eligible, ~exists))
        relationship_checks[edge["id"]] = {
            "status": "issue" if missing else "passed" if examined else "not_evaluated",
            "examined_count": examined, "orphan_count": missing, "basis": "measured",
        }
    return relationship_checks


def assess_quality(connection, schema, relationships, profiles, predictions, *, relationship_checks=None):
    schema_tables = {table["name"]: table for table in schema["tables"]}
    fields = {}
    issues = []

    def check(field, dimension, code, count, examined, basis, description, impact, action,
              evidence=None, critical=False, affected_columns=None):
        measured = examined > 0
        fraction = count / examined if measured else None
        field["checks"][dimension].append({
            "code": code, "status": ("issue" if count else "passed") if measured else "not_evaluated",
            "basis": basis, "examined_count": examined,
        })
        if not count:
            return
        severity = "high" if critical or fraction >= .2 else "medium" if fraction >= .05 else "low"
        issue_id = len(issues) + 1
        issues.append({
            "id": issue_id, "table_name": field["table_name"], "column_name": field["column_name"],
            "columns": affected_columns or [field["column_name"]],
            "dimension": dimension, "code": code, "description": description,
            "affected_count": count, "examined_count": examined, "affected_fraction": fraction,
            "basis": basis, "severity": severity, "evidence": evidence or {},
            "potential_business_impact": impact, "suggested_corrective_action": action,
        })
        field["issue_ids"].append(issue_id)

    for table in schema["tables"]:
        table_name = table["name"]
        unique = {tuple(key["column_names"]) for key in table["unique_constraints"]}
        unique.add(tuple(table["primary_key"]["constrained_columns"]))
        for column in table["columns"]:
            name = column["name"]
            fields[table_name, name] = {
                "table_name": table_name, "column_name": name,
                "checks": {dim: [] for dim in DIMENSIONS}, "issue_ids": [],
            }
            field = fields[table_name, name]
            profile = profiles[table_name][name]
            non_null, total = profile["non_null_count"], profile["total_count"]
            check(field, "completeness", "missing_values", total - non_null, total, "measured",
                  "Records contain NULL in the field.",
                  "Analyses may exclude records or underrepresent some groups.",
                  "Confirm when the field is required and address unexpected omissions at entry.",
                  {"nullable": column["nullable"]}, critical=not column["nullable"])
            if (name,) in unique:
                check(field, "uniqueness", "duplicate_values", profile["duplicate_count"], non_null,
                      "measured", "Duplicate non-null occurrences beyond the first in each group.",
                      "Multiple records can be mistaken for distinct entities.",
                      "Investigate repeated values and enforce the intended uniqueness constraint.")

    reflected = {}
    metadata = MetaData()

    def source(name):
        if name not in reflected:
            reflected[name] = Table(name, metadata, autoload_with=connection, resolve_fks=False)
        return reflected[name]

    def check_group(names, dimension, *args, **kwargs):
        primary_field, *other_fields = [fields[name] for name in names]
        previous = len(primary_field["issue_ids"])
        check(primary_field, dimension, *args, **kwargs,
              affected_columns=[column for _, column in names])
        for other in other_fields:
            other["checks"][dimension].append(primary_field["checks"][dimension][-1])
            other["issue_ids"].extend(primary_field["issue_ids"][previous:])

    for table in schema["tables"]:
        constraints = {tuple(key["column_names"]) for key in table["unique_constraints"]}
        constraints.add(tuple(table["primary_key"]["constrained_columns"]))
        for names in sorted(names for names in constraints if len(names) > 1):
            columns = [source(table["name"]).c[name] for name in names]
            eligible = and_(*(column.is_not(None) for column in columns))
            grouped = select(*columns, func.count().label("quality_group_count")).where(
                eligible).group_by(*columns).subquery()
            occurrences, groups = connection.execute(select(
                func.coalesce(func.sum(list(grouped.c)[-1]), 0), func.count()
            )).one()
            check_group([(table["name"], name) for name in names], "uniqueness", "duplicate_key",
                        occurrences - groups, occurrences, "measured",
                        "Duplicate complete composite key occurrences beyond the first.",
                        "Records cannot be reliably distinguished by the declared key.",
                        "Resolve duplicate key groups before relying on the composite identifier.")

    for prediction in predictions:
        table, name = prediction["table_name"], prediction["column_name"]
        field = fields[table, name]
        profile = profiles[table][name]
        kind = prediction["semantic_type"]
        sample = profile["sample_count"]
        if kind in PATTERNS and "local_detection" in profile:
            hits = profile["local_detection"].get(kind, {})
            invalid_structure = sample - hits.get("structural", 0)
            invalid_format = hits.get("format_invalid", 0)
            check(field, "validity", "invalid_format", invalid_structure + invalid_format,
                  sample, "sample_based", f"Non-null sample values fail the {kind} format check.",
                  "Matching, grouping or downstream validation may fail.",
                  "Validate input formats and correct affected records at the source.",
                  {"unmatched_structure": invalid_structure, "matched_but_invalid": invalid_format})
            if kind in CHECKSUM_TYPES:
                eligible = hits.get("checksum_valid", 0) + hits.get("checksum_invalid", 0)
                check(field, "validity", "invalid_checksum", hits.get("checksum_invalid", 0),
                      eligible, "sample_based", "Structurally matched identifiers fail the checksum.",
                      "Identifier-based matching and verification are unreliable.",
                      "Verify identifiers at the source and separate invalid entries.")
        category = TYPES[kind].category if kind in TYPES else kind
        indicators = profile.get("value_indicators", {})
        if category in {"count", "duration", "boolean_flag", "currency"} and indicators:
            if category in {"count", "duration"}:
                bad = sample - indicators["numeric"] + indicators["negative"]
            else:
                bad = sample - indicators["binary" if category == "boolean_flag" else "currency"]
            check(field, "validity", "invalid_value", bad, sample, "sample_based",
                  f"Sample values fall outside the expected {category} representation.",
                  "Invalid values may distort summaries and comparisons.",
                  "Verify the field definition and validate values at entry.")
        if category in {"location", "category", "status"} and "normalization" in profile:
            variants = profile["normalization"]
            check(field, "consistency", "representation_variants", variants["affected_count"],
                  variants["text_count"], "sample_based",
                  "Sample contains spellings that differ only by case, spacing or Unicode normalization.",
                  "Equivalent labels may be split across groups in reports.",
                  "Map labels to a maintained canonical vocabulary and verify any translations.",
                  {"variant_groups": variants["variant_groups"]})

    if relationship_checks is None:
        relationship_checks = verify_relationships(connection, schema, relationships)
    for edge in relationships["edges"]:
        measured = relationship_checks[edge["id"]]
        if "examined_count" not in measured:
            continue
        check_group([(edge["source"], name) for name in edge["data"]["source_columns"]], "referential_integrity",
                    "missing_referenced_records", measured["orphan_count"], measured["examined_count"], "measured",
                    "Complete foreign key values have no matching parent record.",
                    "Joins may omit records and bias cross-domain reporting.",
                    "Restore missing parent records or correct the references.",
                    {"relationship_id": edge["id"]}, critical=True)

    for field in fields.values():
        field["dimensions"] = {}
        for dimension, checks in field["checks"].items():
            statuses = {item["status"] for item in checks}
            field["dimensions"][dimension] = ("issue" if "issue" in statuses else
                                               "passed" if "passed" in statuses else "not_evaluated")

    def summarize(keys):
        keys = list(keys)
        ids = sorted({issue for key in keys for issue in fields[key]["issue_ids"]})
        return {
            "field_count": len(keys), "issue_count": len(ids), "issue_ids": ids,
            "severity_counts": dict(Counter(issues[issue - 1]["severity"] for issue in ids)),
            "dimensions": {dimension: dict(Counter(fields[key]["dimensions"][dimension] for key in keys))
                           for dimension in DIMENSIONS},
        }

    domains = defaultdict(list)
    for prediction in predictions:
        domains[prediction["data_domain"]].append((prediction["table_name"], prediction["column_name"]))
    return {
        "methodology": {
            "measured": "Exact count from full-column profiles or database aggregate queries.",
            "sample_based": "Observed count and proportion within the stated sample denominator.",
            "not_evaluated": "No applicable check or no eligible observations.",
            "severity": "High for critical checks or at least 20% affected; medium from 5%; low otherwise.",
        },
        "issues": issues, "fields": list(fields.values()), "relationships": relationship_checks,
        "tables": {table: summarize(key for key in fields if key[0] == table) for table in schema_tables},
        "domains": {domain: summarize(keys) for domain, keys in domains.items()},
    }
