"""Metadata and verified relationship evidence layered over the existing classifier."""
from collections import defaultdict, deque

from .context import BUSINESS, DOMAIN_ANCHORS, domain_mentions, has, words
from .engine import ALIASES, DIRECT, FORMATS, IDENTIFIERS, NUMERIC, contains, lexical_scores
from .taxonomy import TYPES

OBJECT_TYPES = {"business_identifier", "service_code", "tracking_code", "reservation_code",
                "policy_number", "service_name", "currency_code", "payment_method", "sales_channel"}


def descriptions(value):
    if value is None:
        return {}
    if not isinstance(value, dict):
        raise ValueError("The data dictionary must be a JSON object.")
    def parse(node, children=None):
        if isinstance(node, str):
            return {"description": node.strip()[:1000]}
        if not isinstance(node, dict) or set(node) - {"description", *([children] if children else [])}:
            raise ValueError("Dictionary entries accept descriptions and nested table or field entries.")
        text = node.get("description", "")
        if not isinstance(text, str):
            raise ValueError("A description must be text.")
        result = {"description": text.strip()[:1000]}
        if children:
            entries = node.get(children, {})
            if not isinstance(entries, dict):
                raise ValueError("Tables and fields must be keyed by their exact schema names.")
            key = "fields" if children == "tables" else None
            result[children] = {name: parse(entry, key) for name, entry in entries.items()}
        return result
    return parse(value, "tables")


def add_semantics(row, profile, field):
    kind = row["semantic_type"]
    if kind in DIRECT | {"record_id", "reference_id"} or not field or not profile["sample_count"]:
        return
    candidates = lexical_scores(field)
    if not candidates:
        return
    strongest = max(candidates.values())
    normalized = words(field)
    specificity = {kind: max(len(alias.split()) for alias in ALIASES[kind] if contains(normalized, alias))
                   for kind, score in candidates.items() if score == strongest}
    choices = sorted(kind for kind, size in specificity.items() if size == max(specificity.values()))
    supported = []
    for candidate in choices:
        if candidate in DIRECT or candidate in {"record_id", "reference_id"}:
            continue
        if candidate in NUMERIC and 2 * profile["value_indicators"]["numeric"] < profile["sample_count"]:
            continue
        if candidate in FORMATS and 2 * profile["local_detection"].get(candidate, {}).get("structural", 0) < profile["sample_count"]:
            continue
        supported.append(candidate)
    if not supported:
        return
    compatible = {TYPES[candidate].category for candidate in supported}
    if len(supported) != 1:
        row["review_required"] = True
        if kind == "unknown" and len(compatible) == 1:
            row["semantic_category"] = next(iter(compatible))
        return
    candidate = supported[0]
    if kind != candidate and kind not in {"unknown", "identifier", TYPES[candidate].category}:
        named = lexical_scores(row["column_name"])
        if kind in named or not row["review_required"]:
            row["review_required"] = True
            return
    if candidate != kind:
        row.update(semantic_type=candidate, semantic_category="identifier" if candidate in IDENTIFIERS
                   else TYPES[candidate].category, subtype_status="supported_by_description",
                   confidence=min(.69, max(.50, row["confidence"])), review_required=True,
                   explanation="The field description supports this type alongside available profile evidence.")
    row["supporting_evidence"] = [*row["supporting_evidence"], {
        "source": "field_description", "family": "metadata", "weight": strongest,
        "detail": "A field description matches a taxonomy alias.",
    }]


def enrich(predictions, profiles, relationships, checks, dictionary=None, *, schema, asset_description=None):
    metadata = descriptions(dictionary)
    database_hint = domain_mentions(metadata.get("description") or asset_description or "")
    tables = metadata.get("tables", {})
    grouped = defaultdict(dict)
    for original in predictions:
        row = dict(original)
        table, field = row["table_name"], row["column_name"]
        grouped[table][field] = row
        table_info = tables.get(table, {})
        text = table_info.get("fields", {}).get(field, {}).get("description", "")
        add_semantics(row, profiles[table][field], text)
        explicit = domain_mentions(text)
        table_hint = domain_mentions(table_info.get("description", ""))
        anchor = DOMAIN_ANCHORS.get(row["semantic_type"])
        if len(explicit) == 1 and (not anchor or anchor in explicit):
            row.update(data_domain=next(iter(explicit)), domain_resolution="field_description")
        elif len(explicit) > 1 or (explicit and anchor and anchor not in explicit):
            row.update(data_domain="unknown", domain_resolution="conflicting_domain_evidence", review_required=True)
        elif anchor and row["semantic_type"] != "department":
            row.update(data_domain=anchor, domain_resolution="semantic_type")
        elif row["data_domain"] == "unknown" and len(table_hint or database_hint) == 1:
            row.update(data_domain=next(iter(table_hint or database_hint)),
                       domain_resolution="table_description" if table_hint else "database_description")
    anchors = set()
    for table, rows in grouped.items():
        confirmed = {row["semantic_type"] for field, row in rows.items()
                     if row["semantic_type"] in DIRECT
                     and (hit := profiles[table][field]["local_detection"].get(row["semantic_type"], {}))
                     and hit.get("structural", 0) >= max(2, .6 * profiles[table][field]["sample_count"])
                     and (row["semantic_type"] == "person_name" or
                          hit.get("checksum_valid" if row["semantic_type"].startswith("saudi_") else "format_valid", 0)
                          >= max(2, .6 * profiles[table][field]["sample_count"]))}
        if "person_name" in confirmed and len(confirmed) > 1:
            anchors.add(table)

    unique_keys = {table["name"]: {frozenset(table["primary_key"]["constrained_columns"])}
                   | {frozenset(item["column_names"]) for item in table["unique_constraints"]}
                   for table in schema["tables"]}
    inbound = defaultdict(list)
    by_id = {edge["id"]: edge for edge in relationships["edges"]}
    outbound = defaultdict(list)
    record_counts = {table['name']: table['record_count'] for table in schema['tables']}
    verified_object_links = defaultdict(list)
    domain_sets = {table: {row["data_domain"] for row in rows.values()} - {"unknown"}
                   for table, rows in grouped.items()}
    reference_domains = defaultdict(set)
    for edge in relationships["edges"]:
        source, target = edge["source"], edge["target"]
        data = edge["data"]
        if source not in grouped or target not in grouped:
            continue
        check = checks.get(edge["id"], {})
        if (data["kind"] != "declared" or check.get("status") != "passed"
                or frozenset(data["target_columns"]) not in unique_keys[target]):
            continue
        for left, right in zip(data["source_columns"], data["target_columns"]):
            target_row = grouped[target][right]
            if target_row["data_domain"] != "unknown":
                reference_domains[source, left].add(target_row["data_domain"])
            else:
                reference_domains[source, left].update(domain_sets[target])
            if domain_sets[target] == {"catalog"}:
                verified_object_links[source, left].append(edge)
        if check["examined_count"] == record_counts[source]:
            inbound[target].append(edge)
            outbound[source].append(edge)

    for (table, field), candidates in reference_domains.items():
        row = grouped[table][field]
        resolution = row["domain_resolution"]
        if resolution in {"table_description", "database_description", "table_and_neighbors"} or (
                row["data_domain"] == "unknown" and resolution != "conflicting_domain_evidence"):
            if len(candidates) == 1:
                row.update(data_domain=next(iter(candidates)), domain_resolution="verified_reference")
            elif len(candidates) > 1:
                row.update(data_domain="unknown", domain_resolution="conflicting_domain_evidence", review_required=True)

    paths = {name: () for name in sorted(anchors)}
    queue = deque(paths)
    while queue:
        target = queue.popleft()
        for edge in inbound[target]:
            source = edge["source"]
            if source not in paths:
                paths[source] = (*paths[target], edge["id"])
                queue.append(source)

    for table, rows in grouped.items():
        path = paths.get(table)
        subject_keys = {}
        for edge in outbound[table]:
            target_path = paths.get(edge["target"])
            if target_path is None or edge["target"] == table or any(
                    by_id[edge_id]["source"] == table for edge_id in target_path):
                continue
            for field in edge["data"]["source_columns"]:
                candidate = (*target_path, edge["id"])
                if field not in subject_keys or len(candidate) < len(subject_keys[field]):
                    subject_keys[field] = candidate
        for field, row in rows.items():
            kind = row["semantic_type"]
            if kind not in DIRECT:
                eligible = (field in subject_keys or
                            (kind not in OBJECT_TYPES | {"unknown", "identifier", "reference_id"}
                             and not has(field, BUSINESS)))
                field_path = subject_keys.get(field, path)
                if field_path is not None and eligible:
                    row.update(personal_data="yes", personal_linkage="linked", review_required=True,
                               sensitivity="restricted" if row["sensitivity"] == "restricted" else "confidential",
                               personal_linkage_evidence={"method": "verified_relationship_path" if field_path else "subject_record",
                                                          "relationship_ids": list(reversed(field_path))})
                elif (kind == "reference_id" and len(verified_object_links[table, field]) == 1
                      and verified_object_links[table, field][0]["target"] not in paths
                      and row["data_domain"] == "catalog"):
                    row.update(personal_data="no", personal_linkage="none", sensitivity="internal",
                               personal_linkage_evidence={"method": "verified_object_reference",
                                                          "relationship_ids": [verified_object_links[table, field][0]["id"]]})
                elif row["personal_linkage"] == "linked":
                    row.update(personal_data="uncertain", personal_linkage="uncertain",
                               sensitivity="restricted" if row["sensitivity"] == "restricted" else "undetermined",
                               review_required=True, personal_linkage_evidence={"method": "insufficient_verified_evidence"})
            parent = row["semantic_category"]
            if (row["subtype_status"] == "identified" and row["review_required"] and
                    any(candidate["semantic_type"] in TYPES
                        and TYPES[candidate["semantic_type"]].category == parent
                        and candidate["evidence_score"] >= .45 for candidate in row["alternative_candidates"])):
                row["subtype_status"] = "provisional"
            row["semantic_path"] = list(dict.fromkeys(item for item in (parent, kind) if item != "unknown"))
            row["classification_resolution"] = ("unresolved" if not row["semantic_path"] else
                                                "category_only" if kind == "unknown" else row["subtype_status"])
    return [row for rows in grouped.values() for row in rows.values()]
