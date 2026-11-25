"""Second-pass decisions based on content compatibility and measured relationship paths."""
from collections import Counter, defaultdict, deque

from sqlalchemy import MetaData, Table, and_, func, select

from .context import BUSINESS, domain_mentions, has
from .discovery_evidence import descriptions
from .engine import DIRECT, NUMERIC, lexical_scores
from .evidence_catalog import assign, domain_subject, ratio, verified_graph
from .english import normalize
from .taxonomy import TYPES

NUMBER_WORDS = {
    "price": {"price", "cost", "rate", "fee", "charge"},
    "count": {"count", "quantity", "units", "number of", "capacity"},
    "duration_minutes": {"elapsed minutes", "minutes", "time in minutes"},
    "financial_amount": {"amount", "value", "balance", "total"},
}
TEXT_WORDS = {
    "location": {"address", "location", "street", "country", "province", "region", "state"},
    "city": {"city", "town", "municipality"},
    "category": {"type", "category", "class", "group", "kind"},
    "status": {"status", "state", "stage", "phase"},
    "free_text": {"notes", "note", "description", "comment", "remarks"},
    "business_identifier": {"asset code", "product code", "serial number", "batch code"},
}
PERSON_NAMES = {"first", "last", "given", "family", "surname", "full", "person"}
ORGANIZATIONAL = {"company", "organization", "organisation", "warehouse", "plant", "department", "region"}
LINKABLE_FAMILIES = {"financial_amount", "price", "count", "status", "duration", "date", "location",
                     "measurement", "salary", "category", "boolean_flag"}
KEY_TYPES = {"record_id", "reference_id"}
DOMAIN_STOP = {"reference", "value", "amount", "name", "category", "type", "active", "notes",
               "description", "created", "updated", "total", "flag", "code", "unit", "count"}


def contains_term(text, terms):
    return any(f" {word} " in f" {text} " for word in terms)


def reconcile_types(row, profile, values, text):
    proposed = row["semantic_type"]
    if proposed in KEY_TYPES | DIRECT or profile["sample_count"] < 5:
        return
    if row["semantic_verified"] and proposed in {"date", "boolean_flag", "currency_code"}:
        return
    label = normalize(row["column_name"] + " " + text)
    indicators = profile["value_indicators"]
    numeric = ratio(indicators["numeric"], profile["sample_count"]) >= .85
    vocabulary = NUMBER_WORDS if numeric else TEXT_WORDS
    candidates = {k for k, terms in vocabulary.items() if contains_term(label, terms)}
    if numeric:
        candidates |= {k for k in lexical_scores(label) if k in NUMERIC}
        if candidates & {"tax_amount", "payment_amount", "transaction_amount", "salary"}:
            candidates.discard("financial_amount")
    else:
        if "location" in candidates and "city" in candidates:
            candidates.discard("location")
        if "state" in label.split() and candidates == {"location", "status"}:
            # A compact opaque enumeration cannot distinguish administrative region from workflow state.
            return
        if candidates == {"category"} and profile["distinct_count"] > max(8, .4 * profile["non_null_count"]):
            return
        if not values or sum(isinstance(v, str) for v in values) < .85 * len(values):
            return
        if candidates == {"duration_minutes"}:
            return
    if len(candidates) != 1 or proposed not in candidates | {"unknown", "identifier"}:
        return
    selected = next(iter(candidates))
    if selected == "free_text" and profile["average_length"] is not None and profile["average_length"] < 15:
        return
    if selected in {"location", "city"} and sum(isinstance(v, str) and any(c.isalpha() for c in v)
                                                  for v in values) < .8 * len(values):
        return
    # Compatible storage is enough for a suggestion. Keep ambiguous text and numeric metadata provisional.
    confirmed = (numeric and selected in lexical_scores(label) and row["semantic_verified"]
                 or selected == "free_text" and (profile["average_length"] or 0) >= 30)
    assign(row, selected, "content_compatibility",
           "English metadata and sampled storage agree. A subtype requires corroboration.", confirmed)


def person_roots(grouped, tables):
    roots = set()
    for table, fields in grouped.items():
        if not tables[table]["primary_key"]["constrained_columns"]:
            continue
        direct = {row["semantic_type"] for row in fields.values() if row["semantic_type"] in DIRECT and row.get("semantic_verified", False)}
        name_fields = [normalize(name) for name, row in fields.items() if row["semantic_type"] == "person_name"
                       and row.get("semantic_verified", False)]
        parts = {role for name in name_fields for role in PERSON_NAMES if role in name.split()}
        if (name_fields and len(direct) >= 2
                or parts & {"first", "given"} and parts & {"last", "family", "surname"}):
            roots.add(table)
    return roots


def relationship_paths(roots, outgoing):
    """Keep one shortest declared path for each first edge, including partially populated links."""
    incoming = defaultdict(list)
    for edges in outgoing.values():
        for edge in edges:
            incoming[edge["target"]].append(edge)
    shortest = {table: () for table in sorted(roots)}
    queue = deque(shortest)
    while queue:
        target = queue.popleft()
        for edge in incoming[target]:
            child = edge["source"]
            if child not in shortest:
                shortest[child] = (edge, *shortest[target])
                queue.append(child)
    return shortest


def measured_path(connection, source, route, metadata):
    parent = source.alias()
    join = parent
    for i, edge in enumerate(route):
        target_name = edge["target"]
        target = Table(target_name, metadata, autoload_with=connection, resolve_fks=False).alias(f"path_{i}")
        columns = edge["data"]
        join = join.join(target, and_(*(target.c[right] == parent.c[left]
                         for left, right in zip(columns["source_columns"], columns["target_columns"]))))
        parent = target
    return connection.scalar(select(func.count()).select_from(join))


def apply_privacy(connection, rows, tables, grouped, relationships, checks, *, extra_roots=()):
    # Exact-key evidence is already calculated for every declared edge. Partial paths are
    # useful for review but are insufficient for an automatic negative or positive.
    _, outgoing = verified_graph(tables, relationships, checks)
    path_edges = defaultdict(list)
    for edge in relationships["edges"]:
        status = checks.get(edge["id"], {})
        if status.get("status") == "issue" and status.get("examined_count", 0) > status.get("orphan_count", 0):
            # This edge may be considered only if the target is independently unique.
            adjusted = {edge["id"]: {**status, "status": "passed"}}
            _, verified = verified_graph(tables, {"edges":[edge]}, adjusted)
            path_edges[edge["source"]].extend(verified[edge["source"]])
    for name, edges in outgoing.items():
        path_edges[name].extend(edges)
    roots = person_roots(grouped, tables) | set(extra_roots)
    shortest = relationship_paths(roots, path_edges)
    metadata = MetaData()
    coverage = {}
    def observe(table, route):
        key = table, tuple(edge["id"] for edge in route)
        if key not in coverage:
            source = Table(table, metadata, autoload_with=connection, resolve_fks=False)
            coverage[key] = {
                "relationship_ids": list(key[1]),
                "matched_source_rows": measured_path(connection, source, route, metadata),
                "source_rows": tables[table]["record_count"],
            }
        return coverage[key]

    for row in rows:
        table, field, kind = row["table_name"], row["column_name"], row["semantic_type"]
        if row.get("semantic_verified", False) and (kind in DIRECT or row["personal_linkage"] == "direct"):
            continue
        edges = [edge for edge in path_edges[table] if field in edge["data"]["source_columns"]]
        routes = [(edge, *shortest[edge["target"]]) for edge in edges if edge["target"] in shortest
                  and all(item["source"] != table for item in shortest[edge["target"]])]
        route = min(routes, key=len, default=None)
        if route is None and kind not in KEY_TYPES and (row["semantic_category"] in LINKABLE_FAMILIES
                or row.get("context_privacy_hypothesis") == "linked" and kind != "unknown"):
            if not has(field, ORGANIZATIONAL | BUSINESS):
                route = shortest.get(table)
        privacy_review = "privacy" in row["review_dimensions"]
        if table in extra_roots and kind == "record_id":
            route = ()
        if route is not None and len(route) < 64 and (route or table in extra_roots):
            found = observe(table, route)
            if found["matched_source_rows"] > 0:
                complete = found["matched_source_rows"] == found["source_rows"]
                role = "indirect_identifier" if kind in KEY_TYPES else "person_linked_attribute"
                row.update(personal_data="yes", personal_linkage="linked", privacy_role=role,
                           personal_linkage_evidence={"method":"measured_subject_path", **found},
                           sensitivity="restricted" if row["sensitivity"] == "restricted" else "confidential")
                privacy_review = not complete or role == "person_linked_attribute"
        elif kind == "reference_id" and row["privacy_role"] == "object_reference":
            # A verified match proves the referenced row exists. It does not prove that
            # an opaque target table lacks potentially identifying records.
            targets = [edge["target"] for edge in edges]
            if targets and not all(has(t, BUSINESS) for t in targets):
                row.update(personal_data="uncertain", personal_linkage="uncertain", privacy_role="unresolved_reference",
                           sensitivity="undetermined",
                           personal_linkage_evidence={"method":"target_purpose_unresolved","relationship_ids":[]})
                privacy_review = True
        dimensions = set(row["review_dimensions"])
        dimensions.discard("privacy")
        if privacy_review:
            dimensions.add("privacy")
        row["review_dimensions"] = sorted(dimensions)


def relate_groups(rows, grouped, tables, relationships, checks):
    """Use content-bearing schema terms to corroborate graph communities."""
    _, outgoing = verified_graph(tables, relationships, checks)
    table_group = {table: Counter(row["data_domain"] for row in fields.values()).most_common(1)[0][0]
                   for table, fields in grouped.items()}
    descriptors = {table: domain_subject(table) | {
        word for field, row in fields.items() if row["semantic_type"] not in KEY_TYPES
        for word in domain_subject(field) - DOMAIN_STOP}
        for table, fields in grouped.items()}
    for row in rows:
        table = row["table_name"]
        if row["domain_resolution"] not in {"discovered_table_subject", "junction"}:
            continue
        neighbors = {edge["target"] for edge in outgoing[table]}
        candidates = {table_group[t] for t in neighbors if table_group[t] != "unknown"
                      and (table_group[t] == table_group[table]
                           or len(descriptors[t] & descriptors[table]) >= 2)}
        if len(candidates) == 1:
            row.update(data_domain=next(iter(candidates)), domain_resolution="verified_relationship_group")
            row["review_dimensions"] = [d for d in row["review_dimensions"] if d != "domain"]


def refine(connection, rows, schema, profiles, samples, relationships, checks, dictionary, *, resolve_privacy=True):
    info = descriptions(dictionary).get("tables", {})
    tables = {table["name"]: table for table in schema["tables"]}
    grouped = defaultdict(dict)
    for row in rows:
        table, field = row["table_name"], row["column_name"]
        text = info.get(table, {}).get("fields", {}).get(field, {}).get("description", "")
        reconcile_types(row, profiles[table][field], samples[table][field], text)
        if row["semantic_verified"]:
            row["review_dimensions"] = [d for d in row["review_dimensions"] if d != "semantic"]
        grouped[table][field] = row
    relate_groups(rows, grouped, tables, relationships, checks)
    if resolve_privacy:
        apply_privacy(connection, rows, tables, grouped, relationships, checks)
    for row in rows:
        kind = row["semantic_type"]
        row["semantic_path"] = list(dict.fromkeys(v for v in (row["semantic_category"], kind) if v != "unknown"))
        row["classification_resolution"] = row["subtype_status"] if kind != "unknown" else "unresolved"
        row["review_required"] = bool(row["review_dimensions"])
    return rows
