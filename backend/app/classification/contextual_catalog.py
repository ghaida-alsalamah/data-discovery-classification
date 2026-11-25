"""Reconcile model interpretations with independently observed types and verified person paths."""
from collections import defaultdict
from pathlib import Path

from .context import BUSINESS, has, words
from .context_provider import proposals
from .engine import DIRECT, IDS, lexical_scores
from .evidence_catalog import assign
from .local_llm import bucket, storage
from .open_catalog import EXTENSIONS as OPEN_TYPES
from .production_catalog import (
    EXTENDED, KEYS, PERSON_ROLES, ROLE_NAMES, SHARED_CONTACT, direct, name_shape,
    phone_shape, phone_valid, set_type,
)
from .relational_catalog import apply_privacy
from .taxonomy import TYPES

NER_ROOT = Path(".deps/upstream-om/en_core_web_md")
FAMILIES = {**OPEN_TYPES, **EXTENDED, "rank": "count", "language": "category"}
DIRECT_TYPES = DIRECT | {"ssn"}
SIMPLE = {
    "language": "language", "rank": "rank", "duration": "duration_minutes",
    "amount": "financial_amount", "count": "count", "quantity": "count",
    "weight": "mass", "mass": "mass", "cost": "price", "price": "price",
    "percent": "percentage", "percentage": "percentage", "ratio": "ratio",
    "age": "age", "year": "year", "status": "status", "category": "category",
    "description": "free_text", "notes": "free_text", "comment": "free_text",
}
EQUIVALENTS = {"full_name": "person_name", "given_name": "person_name", "first_name": "person_name",
               "surname": "person_name", "last_name": "person_name", "telephone": "phone_number",
               "email": "email_address", "timestamp": "date", "address": "location", "street_address": "location",
               "weight": "mass", "currency": "currency_code"}
NUMERIC_FAMILY = {"identifier", "measurement", "date", "count", "duration", "financial_amount",
                  "price", "salary", "record_id", "reference_id"}
OBJECT_TYPES = {"business_identifier", "service_code", "tracking_code", "organization_name", "currency_code"}
STORAGE_LABELS = {"string", "str", "varchar", "text", "int", "integer", "float", "numeric", "number", "column"}
ROLE_PRIVACY = {"d": "direct", "l": "linked", "n": "none", "u": "uncertain"}
RESPONSIBILITY = {"owner", "manager", "reviewer", "supervisor", "assignee", "approver"}


class EntityEvidence:
    def __init__(self, model=None):
        import spacy

        if model is None:
            installed = sorted(NER_ROOT.glob("en_core_web_md-*"))
            if installed:
                model = installed[0]
            elif spacy.util.is_package("en_core_web_md"):
                model = "en_core_web_md"
        self.pipeline = None if model is None else spacy.load(
            model, exclude=["tagger", "parser", "attribute_ruler", "lemmatizer"],
        )

    def shares(self, values):
        if self.pipeline is None or not values:
            return 0, 0
        text = [v.strip() for v in values if isinstance(v, str) and v.strip() and len(v) <= 96]
        people = places = 0
        for doc in self.pipeline.pipe(text, batch_size=32):
            labels = {e.label_ for e in doc.ents if e.start == 0 and e.end == len(doc)}
            people += "PERSON" in labels
            places += bool(labels & {"GPE", "LOC", "FAC"})
        return bucket(people, len(values)), bucket(places, len(values))


def observations(profiles, samples, entity):
    data = {}
    for table, columns in profiles.items():
        data[table] = {}
        for name, profile in columns.items():
            values = samples[table][name]
            size = profile["sample_count"]
            detectors = profile["local_detection"]
            indicators = profile["value_indicators"]
            person, place = entity.shares(values)
            data[table][name] = {
                "size": size,
                "person": person, "place": place,
                "name_shape": round(10 * name_shape(values)) if values else 0,
                "phone": bucket(sum(phone_shape(v) for v in values), len(values)),
                "valid_phone": bucket(sum(phone_valid(v) for v in values), len(values)),
                "email": bucket(detectors.get("email_address", {}).get("format_valid", 0), size),
                "date": bucket(detectors.get("date", {}).get("format_valid", 0), size),
                "saudi_national_id": bucket(detectors.get("saudi_national_id", {}).get("checksum_valid", 0), size),
                "saudi_residency_id": bucket(detectors.get("saudi_residency_id", {}).get("checksum_valid", 0), size),
                "saudi_iban": bucket(detectors.get("saudi_iban", {}).get("checksum_valid", 0), size),
                "currency": bucket(indicators["currency"], size),
                "number": bucket(indicators["numeric"], size),
                "bit": bucket(indicators.get("boolean_conventional", indicators["binary"]), size),
                "unique": bucket(profile["distinct_count"], profile["non_null_count"]),
                "empty": bucket(profile["total_count"] - profile["non_null_count"], profile["total_count"]),
            }
    return data


def family(kind):
    if kind in TYPES:
        return TYPES[kind].category
    return FAMILIES.get(kind, "other")


def apply_type(row, kind, source, detail, confirmed):
    if kind in EXTENDED and confirmed:
        set_type(row, kind, detail)
        return
    if kind in TYPES:
        assign(row, kind, source, detail, confirmed)
    else:
        row.update(semantic_type=kind, semantic_category=family(kind),
                   semantic_verified=confirmed, confidence=.76 if confirmed else .48,
                   subtype_status="identified" if confirmed else "provisional", explanation=detail)
        row["supporting_evidence"] = [{"source": source, "family": "catalog_evidence", "detail": detail, "weight": 0}]


def choose_type(row, column, evidence, role, suggestion):
    current = row["semantic_type"]
    proposed, privacy = suggestion
    proposed = EQUIVALENTS.get(proposed, proposed)
    sql_type = storage(column["type"])
    label = words(column["name"])
    tokens = set(label.split())
    obvious_nonperson = bool(tokens & SHARED_CONTACT or has(label, BUSINESS))
    name_metadata = "name" in tokens or bool(tokens & ROLE_NAMES)
    name_evidence = evidence["person"] >= 6 or evidence["name_shape"] >= 9 and name_metadata
    if current in KEYS or current in DIRECT_TYPES and row["personal_linkage"] == "direct" and row["semantic_verified"]:
        return current, True
    if evidence["size"] < 3:
        return ("date", True) if sql_type == "temporal" else (current, row["semantic_verified"])
    if evidence["email"] >= 8:
        return "email_address", True
    if sql_type == "temporal" or evidence["date"] >= 8:
        return "date", True
    if sql_type == "boolean" or evidence["bit"] >= 9 and proposed == "boolean_flag":
        return "boolean_flag", True
    if evidence["currency"] >= 8:
        return "currency_code", True
    if evidence["place"] >= 7 and tokens & {"city", "town", "hometown", "municipality"}:
        return "city", True
    if evidence["place"] >= 7 and tokens & {"state", "county", "country", "province", "district"}:
        return "location", True
    if name_evidence and not obvious_nonperson and (
            role == "p" and (name_metadata or proposed == "person_name")
            or proposed == "person_name" and evidence["person"] >= 7 and privacy == "d"):
        return "person_name", True
    if evidence["phone"] >= 6 and (
            proposed == "phone_number" or bool(tokens & {"phone", "telephone", "cell", "mobile"})
            or role == "p" and evidence["valid_phone"] >= 8):
        return "phone_number", evidence["valid_phone"] >= 7 or not obvious_nonperson and role == "p"
    for kind in IDS | {"saudi_iban"}:
        if proposed == kind and evidence.get(kind, 0) >= 7 and not obvious_nonperson and (role == "p" or privacy == "d"):
            return kind, True
    if row["semantic_verified"]:
        return current, True
    if proposed in DIRECT_TYPES | KEYS | STORAGE_LABELS | {"unknown"}:
        proposed = SIMPLE.get(label, current)
    elif proposed in {"city", "location"} and evidence["place"] < 5 and not tokens & {"city", "town", "hometown", "country", "street", "location", "address", "state", "region"}:
        return current, False
    if proposed == "unknown":
        return current, False
    if evidence["number"] >= 8:
        typed = family(proposed)
        if typed not in NUMERIC_FAMILY | {"category", "boolean_flag", "status", "identifier", "other"}:
            return current, False
    hints = lexical_scores(label)
    named = proposed in hints or SIMPLE.get(label) == proposed or proposed.replace("_", " ") == label
    compatible = (evidence["number"] >= 8 and family(proposed) in NUMERIC_FAMILY or
                  evidence["number"] <= 2 and sql_type == "text" and family(proposed) in {"category", "status", "free_text", "location"})
    if proposed != current and current not in {"unknown", "identifier"} and current in hints and not named:
        return current, False
    return proposed, bool(named and compatible)


def mark_direct(row, kind, evidence):
    if kind in {"phone_number", "email_address"} and evidence["phone" if kind == "phone_number" else "email"] < 8:
        return False
    direct(row, kind, "Context and independent local type evidence indicate an individual identifier.")
    return True


def classify(provider, entity, connection, rows, schema, profiles, samples, relationships, checks):
    evidence = observations(profiles, samples, entity)
    structural = {(row["table_name"], row["column_name"]) for row in rows
                  if row["semantic_type"] in KEYS and row["semantic_verified"]}
    candidate, roles, missing = proposals(provider, schema, evidence, structural)
    tables = {table["name"]: table for table in schema["tables"]}
    columns = {t: {c["name"]: c for c in table["columns"]} for t, table in tables.items()}
    grouped = defaultdict(dict)
    roots = set()
    observed_people = {
        table for table, fields in evidence.items()
        if not has(table, BUSINESS)
        and any(sig["person"] >= 7 and "name" in words(field).split() for field, sig in fields.items())
        and any(sig["email"] >= 8 or sig["valid_phone"] >= 8 for sig in fields.values())
    }
    metadata_roots = set()
    for row in rows:
        t, c = row["table_name"], row["column_name"]
        grouped[t][c] = row
        explicit_person = has(t, PERSON_ROLES) and not has(t, BUSINESS)
        role = "p" if t in observed_people else roles.get(t, "p" if explicit_person else "u")
        primary = tables[t]["primary_key"]["constrained_columns"]
        if primary and explicit_person and roles.get(t) == "p":
            metadata_roots.add(t)
        suggestion = candidate.get((t, c), ("unknown", "u"))
        sig = evidence[t][c]
        kind, confirmed = choose_type(row, columns[t][c], sig, role, suggestion)
        dimensions = set(row["review_dimensions"])
        if kind != row["semantic_type"] or confirmed and not row["semantic_verified"]:
            apply_type(row, kind, "catalog_context", "Schema context and local observations support this classification."
                       if confirmed else "Context suggests this type. Its meaning still needs confirmation.", confirmed)
        if confirmed:
            dimensions.discard("semantic")
        else:
            dimensions.add("semantic")
        row["review_dimensions"] = sorted(dimensions)
        row["context_status"] = ("completed" if (t, c) in candidate else "verified_locally" if (t, c) in structural
                                 else "fallback" if provider else "offline")
        if (t, c) in candidate:
            row["context_semantic_hypothesis"] = suggestion[0]
        row["context_privacy_hypothesis"] = ("none" if kind in OBJECT_TYPES else ROLE_PRIVACY[suggestion[1]])
        if kind in DIRECT_TYPES and confirmed and row["personal_linkage"] != "direct":
            shared = has(c, BUSINESS) or bool(set(words(c).split()) & SHARED_CONTACT)
            if not shared and (kind == "person_name" or role == "p" or suggestion[1] == "d"):
                if mark_direct(row, kind, sig):
                    row["review_dimensions"] = [d for d in row["review_dimensions"] if d != "privacy"]
            elif kind in {"email_address", "phone_number"} and (shared or role == "o"):
                row.update(personal_data="no", personal_linkage="none", sensitivity="internal",
                           privacy_role="organizational_contact")
        if kind == "person_name" and row["personal_linkage"] == "direct" and role == "p" and tables[t]["primary_key"]["constrained_columns"]:
            roots.add(t)
    inferred_roots = roots | metadata_roots
    barriers = {t for t, role in roles.items() if role == "o"} - inferred_roots
    for edge in relationships["edges"]:
        source, target = edge["source"], edge["target"]
        if source not in inferred_roots and target in inferred_roots and roles.get(source, "u") in {"o", "u"}:
            if any(set(words(column).split()) & RESPONSIBILITY for column in edge["data"]["source_columns"]):
                barriers.add(source)
    apply_privacy(connection, rows, tables, grouped, relationships, checks, extra_roots=inferred_roots,
                  resolve_verified_subject_attributes=True, subject_barriers=barriers)
    for t, fields in grouped.items():
        verified = sum(row["semantic_verified"] and row["semantic_type"] not in KEYS for row in fields.values())
        if verified >= 2 and tables[t]["primary_key"]["constrained_columns"]:
            for row in fields.values():
                if row["domain_resolution"] == "discovered_table_subject" and row["data_domain"] != "unknown":
                    row["domain_resolution"] = "corroborated_table_group"
                    row["review_dimensions"] = [d for d in row["review_dimensions"] if d != "domain"]
        for c, row in fields.items():
            kind = row["semantic_type"]
            if (row["personal_linkage"] == "linked" and row["semantic_verified"]
                    and row.get("context_privacy_hypothesis") == "linked"):
                measured = row["personal_linkage_evidence"]
                if measured.get("method") == "measured_subject_path" and measured["matched_source_rows"] == measured["source_rows"]:
                    row["review_dimensions"] = [d for d in row["review_dimensions"] if d != "privacy"]
            if (row["personal_data"] == "uncertain" or t in metadata_roots - roots
                    and row["personal_linkage"] == "linked") and "privacy" not in row["review_dimensions"]:
                row["review_dimensions"].append("privacy")
            row["semantic_path"] = list(dict.fromkeys(x for x in (row["semantic_category"], kind) if x != "unknown"))
            row["classification_resolution"] = row["subtype_status"] if kind != "unknown" else "unresolved"
            row["review_required"] = bool(row["review_dimensions"])
    return rows, {"missing_context_fields": missing, "entity_model_loaded": entity.pipeline is not None}
