"""Locally grounded classification with separate semantic, domain and privacy decisions."""
from collections import Counter, defaultdict, deque
import re

from .context import BUSINESS, PERSON, domain_mentions, has
from .discovery_evidence import add_semantics, descriptions
from .engine import DIRECT, IDS, NUMERIC, lexical_scores
from .english import local_content, normalize
from .taxonomy import TYPES

FORMAT_TYPES = {"date", "email_address", "phone_number", "saudi_iban", *IDS}
SUBJECT_TERMS = PERSON | {"person", "contact", "individual", "worker", "employee"}
OBJECT_TERMS = BUSINESS | {"company", "organization", "organisation", "supplier", "equipment", "machine"}
STRUCTURE_WORDS = {"id", "identifier", "key", "code", "reference", "number", "name", "date", "type", "status",
                   "table", "record", "register", "directory", "history", "detail", "log", "list", "data"}
LINKABLE = {"location", "financial_amount", "duration", "date", "status", "salary", "measurement"}
BUSINESS_FIELDS = {"company", "organization", "supplier", "asset", "product", "inventory", "system", "branch",
                   "machine", "device", "office", "facility"}
IDENTITY_TERMS = {"identity", "citizen", "national", "iqama", "residency", "passport"}
ROLE_TERMS = {"first", "last", "given", "family", "surname", "full"}
MIN_SAMPLE = 5


def ratio(count, size):
    return count / max(1, size)


def assign(row, kind, source, detail, confirmed=False):
    original = row["semantic_type"]
    row.update(semantic_type=kind, semantic_category=TYPES[kind].category,
               subtype_status="identified" if confirmed else "uncertain" if kind == "unknown" else "provisional",
               semantic_verified=confirmed, explanation=detail)
    item = {"source": source, "family": "catalog_evidence", "weight": 0, "detail": detail}
    if original != kind:
        row["supporting_evidence"] = [item]
        row["confidence"] = .76 if confirmed else .49
        if original != "unknown":
            row["alternative_candidates"] = [{"semantic_type": original, "evidence_score": 0},
                                             *row["alternative_candidates"]][:3]
    else:
        row["supporting_evidence"] = [*row["supporting_evidence"], item]


def format_strength(profile, kind):
    hits = profile["local_detection"].get(kind, {})
    key = "checksum_valid" if kind in IDS | {"saudi_iban"} else "format_valid"
    return ratio(hits.get(key, 0), profile["sample_count"])


def key_columns(table, field):
    if any(field in fk["constrained_columns"] for fk in table["foreign_keys"]):
        return "reference_id", "Declared foreign key."
    if field in table["primary_key"]["constrained_columns"]:
        return "record_id", "Declared primary key."
    return None, None


def semantics(row, table, profile, values, text, subject_context):
    field = row["column_name"]
    size = profile["sample_count"]
    key, explanation = key_columns(table, field)
    if key:
        assign(row, key, "schema_constraint", explanation, True)
        return
    row["semantic_verified"] = False
    if size < MIN_SAMPLE:
        assign(row, "unknown", "sample_limit", "Too few non-null observations to verify a semantic type.")
        return
    label = normalize(field + " " + text)
    tokens = set(label.split())
    named = lexical_scores(label)
    content = local_content(values)
    indicators = profile["value_indicators"]
    mostly_numeric = ratio(indicators["numeric"], size) >= .80
    code_context = bool(tokens & {"code", "serial", "key", "identifier"}) or bool(tokens & OBJECT_TERMS)
    name_context = ("name" in tokens and bool(tokens & ROLE_TERMS | tokens & SUBJECT_TERMS)
                    and not bool(tokens & OBJECT_TERMS))
    # Names and number-shaped strings need context. Evidence for format is tracked separately.
    if name_context and (ratio(profile["local_detection"].get("person_name", {}).get("structural", 0), size) >= .70
                         or bool(tokens & ROLE_TERMS) and not mostly_numeric and
                         sum(isinstance(v, str) and v.strip().replace("-", "").replace("'", "").isalpha()
                             for v in values) >= .75 * len(values)):
        assign(row, "person_name", "name_context", "Name metadata and local text structure corroborate one another.", True)
        return
    confirmations = []
    for kind in FORMAT_TYPES:
        if format_strength(profile, kind) < .75:
            continue
        if kind in IDS and (not subject_context or not tokens & IDENTITY_TERMS or code_context):
            continue
        if kind == "phone_number" and (code_context or not (subject_context or "phone_number" in named)):
            continue
        if kind != "date" and code_context:
            continue
        confirmations.append(kind)
    if ("phone_number" in named and not code_context and "phone_number" not in confirmations and values
            and sum(isinstance(v, str) and bool(re.fullmatch(r"[+0-9][0-9 ().-]{6,23}", v.strip()))
                    and 10 <= sum(c.isdecimal() for c in v) <= 15 for v in values) >= .75 * len(values)):
        confirmations.append("phone_number")
    if len(confirmations) == 1:
        assign(row, confirmations[0], "validated_format", "At least three quarters of sampled values pass the local format or checksum test.", True)
        return
    baseline = row["semantic_type"]
    if baseline in DIRECT:
        if code_context and baseline in IDS | {"phone_number"}:
            assign(row, "business_identifier", "identifier_context", "Metadata describes a code or object identifier. Its format overlaps a personal identifier.")
            return
        assign(row, "unknown", "identity_conflict", "Potential personal-data format lacks corroborating evidence.")
        return
    if len(values) and content["unsupported_geometry"] >= .75 * len(values):
        assign(row, "unknown", "local_content", "Geometry is outside the supported semantic types.")
        return
    if (profile["distinct_count"] == 2 and ratio(indicators["binary"], size) == 1):
        assign(row, "boolean_flag", "value_profile", "Two observed values use a binary representation.", "boolean_flag" in named)
        return
    if ratio(indicators["currency"], size) >= .80:
        assign(row, "currency_code", "value_profile", "Sampled values are predominantly recognized currency codes.", True)
        return
    signals = sorted((kind for kind in ("city", "location", "status", "payment_status", "free_text")
                      if len(values) and ratio(content[kind],len(values)) >= .75),
                     key=lambda kind: (-content[kind], kind))
    if signals and (len(signals) == 1 or content[signals[0]] > content[signals[1]]):
        kind = signals[0]
        assign(row, kind, "local_content", "Most local observations support this content type.", kind in named)
        return
    if text:
        add_semantics(row, profile, text)
        baseline = row["semantic_type"]
    if baseline == "date" or baseline in NUMERIC and not mostly_numeric:
        assign(row, "unknown", "value_conflict", "Sampled values do not corroborate the proposed semantic type.")
    elif baseline != "unknown":
        row["semantic_verified"] = (mostly_numeric and baseline in NUMERIC and named.get(baseline, 0) >= .59)
    elif not row["supporting_evidence"]:
        row["supporting_evidence"] = [{"source":"value_profile", "family":"catalog_evidence", "weight":0,
                                       "detail":"No supported interpretation has sufficient independent evidence."}]


def verified_graph(schema_tables, relationships, checks):
    inbound = defaultdict(list)
    outgoing = defaultdict(list)
    for edge in relationships["edges"]:
        source, target, data = edge["source"], edge["target"], edge["data"]
        check = checks.get(edge["id"], {})
        if target not in schema_tables or source not in schema_tables or data["kind"] != "declared" or check.get("status") != "passed":
            continue
        keys = [schema_tables[target]["primary_key"]["constrained_columns"],
                *(key["column_names"] for key in schema_tables[target]["unique_constraints"])]
        if set(data["target_columns"]) not in [set(key) for key in keys if key]:
            continue
        outgoing[source].append(edge)
        if check["examined_count"] == schema_tables[source]["record_count"]:
            inbound[target].append(edge)
    return inbound, outgoing


def subject_paths(anchors, inbound):
    paths = {table: () for table in sorted(anchors)}
    queue = deque(paths)
    while queue:
        target = queue.popleft()
        for edge in inbound[target]:
            source = edge["source"]
            if source not in paths:
                paths[source] = (edge["id"], *paths[target])
                queue.append(source)
    return paths


def singular(token):
    return token.removesuffix("s") if not token.endswith(("ss", "us", "is")) else token


def domain_subject(value):
    return {singular(token) for token in normalize(value).split()
            if token.isascii() and token.isalpha() and len(token) > 2 and singular(token) not in STRUCTURE_WORDS}


def group_domains(grouped, tables, descriptions_by_table, outgoing):
    groups = {}
    subjects = {table: domain_subject(table) for table in grouped}
    frequency = Counter(token for tokens in subjects.values() for token in tokens)
    for table, rows in grouped.items():
        description = descriptions_by_table.get(table, {}).get("description", "")
        named = domain_mentions(table + " " + description)
        if len(named) == 1:
            groups[table] = (next(iter(named)), "table_subject")
        else:
            primary = set(tables[table]["primary_key"]["constrained_columns"])
            foreign = {c for edge in outgoing[table] for c in edge["data"]["source_columns"]}
            if (len(primary) >= 2 and primary <= foreign and
                    all(r["semantic_type"] in {"record_id", "reference_id", "date"} for r in rows.values())):
                groups[table] = (None, "junction")
            else:
                labels = [singular(token) for token in normalize(table).split() if singular(token) in subjects[table]]
                groups[table] = (max(labels, key=frequency.get, default=None), "discovered_table_subject")
    initial = dict(groups)
    for table, (group, method) in initial.items():
        targets = {initial[edge["target"]][0] for edge in outgoing[table]} - {None}
        if len(targets) == 1 and (method == "junction" or group in targets and method == "discovered_table_subject"):
            groups[table] = (next(iter(targets)), "verified_relationship_group")
    return groups


def privacy(row, table, anchors, paths, outgoing, inbound):
    kind, name = row["semantic_type"], row["column_name"]
    path = paths.get(table)
    subject_ref = [edge for edge in outgoing[table] if edge["target"] in anchors
                   and name in edge["data"]["source_columns"]
                   and edge in inbound[edge["target"]]]
    linked_subject = (path is not None and kind != "reference_id" and
                      not has(name, BUSINESS_FIELDS) and
                      (row["semantic_category"] in LINKABLE or
                       (table in anchors and kind in {"record_id", "category", "customer_segment", "boolean_flag"})))
    if kind in DIRECT and row["semantic_verified"]:
        return "yes", "direct", "direct_identifier", ()
    if kind == "record_id" and table in anchors or subject_ref:
        return "yes", "linked", "indirect_identifier", (subject_ref[0]["id"],) if subject_ref else ()
    if linked_subject:
        return "yes", "linked", "person_linked_attribute", path
    if kind == "reference_id":
        matches = [edge for edge in outgoing[table] if name in edge["data"]["source_columns"]]
        if matches and all(edge["target"] not in paths for edge in matches):
            return "no", "none", "object_reference", tuple(edge["id"] for edge in matches)
        return "uncertain", "uncertain", "unresolved_reference", ()
    if kind in {"unknown", "identifier", "free_text"} or kind in DIRECT or path is None and kind in {"salary", "clinical_measurement"}:
        return "uncertain", "uncertain", "unresolved", ()
    if has(name, BUSINESS_FIELDS) or kind in {"business_identifier", "service_code", "record_id", "category"}:
        return "no", "none", "organizational_or_object_data", ()
    if path is not None:
        return "uncertain", "uncertain", "unresolved_subject_scope", ()
    return "no", "none", "non_personal", ()


def classify(rows, schema, profiles, samples, relationships, checks, dictionary=None, asset_description=None):
    info = descriptions(dictionary)
    tables_info = info.get("tables", {})
    tables = {table["name"]: table for table in schema["tables"]}
    subject_contexts = {table: has(table + " " + tables_info.get(table, {}).get("description", ""), SUBJECT_TERMS)
                        or any(format_strength(p, "email_address") >= .75 and p["sample_count"] >= MIN_SAMPLE
                               for p in columns.values()) for table, columns in profiles.items()}
    grouped = defaultdict(dict)
    for row in rows:
        table, name = row["table_name"], row["column_name"]
        entry = tables_info.get(table, {})
        column_text = entry.get("fields", {}).get(name, {}).get("description", "")
        semantics(row, tables[table], profiles[table][name], samples[table][name], column_text,
                  subject_contexts[table])
        grouped[table][name] = row
    inbound, outgoing = verified_graph(tables, relationships, checks)
    anchors = set()
    for table, fields in grouped.items():
        verified_types = {r["semantic_type"] for r in fields.values() if r["semantic_verified"]}
        names = [set(normalize(name).split()) for name, row in fields.items()
                 if row["semantic_type"] == "person_name" and row["semantic_verified"]]
        separate_names = (any(words & {"first", "given"} for words in names)
                          and any(words & {"last", "family", "surname"} for words in names))
        if names and (len(verified_types & DIRECT) >= 2 or separate_names) and tables[table]["primary_key"]["constrained_columns"]:
            anchors.add(table)
    paths = subject_paths(anchors, inbound)
    groups = group_domains(grouped, tables, tables_info, outgoing)
    sibling_domains = {table: Counter(d for name in fields for d in domain_mentions(name))
                       for table, fields in grouped.items()}
    for row in rows:
        table, name = row["table_name"], row["column_name"]
        field_info = tables_info.get(table, {}).get("fields", {}).get(name, {})
        explicit = domain_mentions(field_info.get("description", ""))
        group, method = groups[table]
        if not group:
            fallback = domain_mentions(info.get("description") or asset_description or "")
            if len(fallback) == 1:
                group, method = next(iter(fallback)), "database_description"
        neighbors = {d for d in domain_mentions(name) if sibling_domains[table][d] >= 2}
        if not explicit and len(neighbors) == 1:
            group, method = next(iter(neighbors)), "field_context"
        if len(explicit) == 1:
            group, method = next(iter(explicit)), "field_description"
        elif len(explicit) > 1:
            group, method = None, "conflicting_domain_evidence"
        row.update(data_domain=group or "unknown", domain_resolution=method)
        personal, linkage, role, path = privacy(row, table, anchors, paths, outgoing, inbound)
        row.update(personal_data=personal, personal_linkage=linkage, privacy_role=role,
                   personal_linkage_evidence={"method": role, "relationship_ids":list(path)},
                   sensitivity=("restricted" if row["semantic_type"] in IDS | {"salary", "saudi_iban"} else
                                {"yes":"confidential","no":"internal","uncertain":"undetermined"}[personal]))
        kind = row["semantic_type"]
        row["semantic_path"] = list(dict.fromkeys(k for k in (row["semantic_category"],kind) if k != "unknown"))
        row["classification_resolution"] = row["subtype_status"] if row["semantic_path"] else "unresolved"
        row["review_dimensions"] = [dimension for dimension, needed in (
            ("semantic", not row["semantic_verified"]),
            ("privacy", personal == "uncertain" or role == "person_linked_attribute"),
            ("domain", not group or method in {"discovered_table_subject","database_description"})) if needed]
        row["review_required"] = bool(row["review_dimensions"])
    return rows
