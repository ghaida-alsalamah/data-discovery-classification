"""Reconcile model interpretations with independently observed types and verified person paths."""
from collections import Counter, defaultdict
import re

import httpx
from pathlib import Path

from .context import BUSINESS, has, words
from .context_provider import proposals, safe_hint
from .engine import DIRECT, IDS, lexical_scores
from .evidence_catalog import assign, verified_graph
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
            return 0, 0, 0
        text = [v.strip() for v in values if isinstance(v, str) and v.strip() and len(v) <= 96]
        people = places = organizations = 0
        for doc in self.pipeline.pipe(text, batch_size=32):
            labels = {e.label_ for e in doc.ents if e.start == 0 and e.end == len(doc)}
            people += "PERSON" in labels
            places += bool(labels & {"GPE", "LOC", "FAC"})
            organizations += "ORG" in labels
        return tuple(bucket(count, len(values)) for count in (people, places, organizations))


ROLE_MAILBOX = frozenset({
    "accounts", "admin", "billing", "bookings", "careers", "contact", "dispatch", "enquiries",
    "help", "hello", "info", "inquiries", "office", "orders", "reception", "sales", "service",
    "support", "team",
})


def contact_scope(values):
    """Recognize shared aliases locally without exporting mailbox text."""
    local_parts = [value.strip().lower().partition("@")[0] for value in values
                   if isinstance(value, str) and value.count("@") == 1]
    if len(local_parts) < 3:
        return 0
    shared = sum(bool(set(re.split(r"[.+_-]", part)) & ROLE_MAILBOX) and not any(char.isdigit() for char in part)
                 for part in local_parts)
    return bucket(shared, len(local_parts))



def observations(profiles, samples, entity):
    data = {}
    for table, columns in profiles.items():
        data[table] = {}
        for name, profile in columns.items():
            values = samples[table][name]
            size = profile["sample_count"]
            detectors = profile["local_detection"]
            indicators = profile["value_indicators"]
            person, place, organization = entity.shares(values)
            data[table][name] = {
                "size": size, "role_mailbox": contact_scope(values),
                "person": person, "place": place, "organization": organization,
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
    if kind in {"phone_number", "email_address"} and evidence["valid_phone" if kind == "phone_number" else "email"] < 8:
        return False
    direct(row, kind, "Context and independent local type evidence indicate an individual identifier.")
    return True


def contextual_domains(provider, grouped, tables, relationships, checks):
    if not hasattr(provider, "domain_groups") or not 2 <= len(tables) <= 30:
        return
    _, outgoing = verified_graph(tables, relationships, checks)
    names = list(tables)
    index = {name: i for i, name in enumerate(names)}
    targets = [{index[edge["target"]] for edge in outgoing[name]} for name in names]
    payload = [{"i": i, "hint": safe_hint(name, True),
                "types": dict(Counter(row["semantic_type"] for row in grouped[name].values()
                                      if row["semantic_type"] in TYPES)),
                "links": sorted(targets[i])}
               for i, name in enumerate(names)]
    try:
        clusters = provider.domain_groups(payload)
    except (httpx.HTTPError, ValueError, KeyError, TypeError, IndexError):
        return
    for i, root in enumerate(clusters):
        if i == root or root not in targets[i] and i not in targets[root]:
            continue
        source = list(grouped[names[i]].values())
        destination = list(grouped[names[root]].values())
        source_group = Counter(row["data_domain"] for row in source).most_common(1)[0][0]
        target_group = Counter(row["data_domain"] for row in destination).most_common(1)[0][0]
        if source_group == target_group or target_group == "unknown":
            continue
        for row in source:
            if row["data_domain"] == source_group:
                row.update(data_domain=target_group, domain_resolution="verified_relationship_group")


def relationship_domains(provider, grouped, tables, relationships, checks, person_entities):
    """Apply stable table-purpose clusters without using display names as group identities."""
    if not hasattr(provider, "purpose_groups") or not 2 <= len(tables) <= 30:
        return
    _, outgoing = verified_graph(tables, relationships, checks)
    names = list(tables)
    index = {name: i for i, name in enumerate(names)}
    scope = []
    payload = []
    majority = []
    for i, name in enumerate(names):
        rows = list(grouped[name].values())
        verified = Counter(row["semantic_type"] for row in rows if row["semantic_verified"])
        group = Counter(row["data_domain"] for row in rows).most_common(1)[0][0]
        majority.append(group)
        kind = ("person" if name in person_entities or verified["person_name"] and
                any(row["personal_linkage"] == "direct" for row in rows)
                else "activity" if outgoing[name] else "reference")
        scope.append(kind)
        payload.append({
            "i": i, "hint": safe_hint(name, True), "scope": kind,
            "fields": [[safe_hint(row["column_name"], True),
                        row["semantic_type"] if row["semantic_type"] in TYPES else "other"]
                       for row in rows[:16]],
            "links": [[index[edge["target"]], [safe_hint(c, True) for c in edge["data"]["source_columns"]]]
                      for edge in outgoing[name][:12]],
        })
    try:
        proposals = provider.purpose_groups(payload)
    except (httpx.HTTPError, ValueError, KeyError, TypeError, IndexError):
        proposals = list(range(len(names)))
    clusters = {}
    for i, representative in enumerate(proposals):
        # A person directory, an operational record, and a business entity
        # have distinct scopes even if a transaction connects them.
        clusters.setdefault((representative, scope[i]), []).append(i)
    assigned = set()
    reserved = {row["data_domain"] for i, name in enumerate(names) for row in grouped[name].values()
                if row["data_domain"] != majority[i]}
    for members in clusters.values():
        label = Counter(majority[i] for i in members).most_common(1)[0][0]
        if label == "unknown" or label in assigned or label in reserved:
            base = label if label != "unknown" else "domain"
            suffix = members[0] + 1
            label = f"{base}_{suffix}"
            while label in assigned or label in reserved:
                suffix += 1
                label = f"{base}_{suffix}"
        assigned.add(label)
        for i in members:
            for row in grouped[names[i]].values():
                if row["data_domain"] == majority[i] and row["data_domain"] != label:
                    row.update(data_domain=label, domain_resolution="verified_relationship_group"
                               if len(members) > 1 else "corroborated_table_group")


def corroborated_subjects(tables, evidence, candidates, roles, incoming, organizations):
    """Find additional person roots independently of final field labels."""
    roots = set()
    for table, fields in evidence.items():
        if (table in organizations or not tables[table]["primary_key"]["constrained_columns"]
                or not incoming.get(table)):
            continue
        person_role = roles.get(table) == "p"
        names, contacts = False, set()
        for field, facts in fields.items():
            kind, privacy = candidates.get((table, field), ("unknown", "u"))
            proposed_name = EQUIVALENTS.get(kind, kind) == "person_name" and privacy == "d"
            names |= (facts["size"] >= 10 and facts["name_shape"] >= 8
                      and facts["organization"] < 5
                      and (proposed_name or person_role and facts["person"] >= 4))
            if (facts["size"] >= 10 and facts["unique"] >= 6 and facts["role_mailbox"] < 5
                    and not set(words(field).split()) & SHARED_CONTACT
                    and (privacy == "d" or person_role)):
                if facts["email"] >= 8:
                    contacts.add("email")
                if facts["valid_phone"] >= 8:
                    contacts.add("phone")
                if any(facts.get(key, 0) >= 8 for key in IDS):
                    contacts.add("government_id")
        if names and len(contacts) >= 2:
            roots.add(table)
    return roots


def classify(provider, entity, connection, rows, schema, profiles, samples, relationships, checks):
    evidence = observations(profiles, samples, entity)
    structural = {(row["table_name"], row["column_name"]) for row in rows
                  if row["semantic_type"] in KEYS and row["semantic_verified"]}
    tables = {table["name"]: table for table in schema["tables"]}
    incoming, outgoing = verified_graph(tables, relationships, checks)
    candidate, roles, missing = proposals(provider, schema, evidence, structural,
                                          outgoing if getattr(provider, "remote", False) else None)
    columns = {t: {c["name"]: c for c in table["columns"]} for t, table in tables.items()}
    grouped = defaultdict(dict)
    roots = set()
    observed_people = {
        table for table, fields in evidence.items()
        if not has(table, BUSINESS)
        and any(sig["person"] >= 7 and "name" in words(field).split() for field, sig in fields.items())
        and any(sig["email"] >= 8 or sig["valid_phone"] >= 8 for sig in fields.values())
    }
    cloud_roles = {}
    known_organizations = {
        row["table_name"] for row in rows
        if row["semantic_type"] == "organization_name" and row["semantic_verified"]
    }
    if provider is not None and getattr(provider, "remote", False):
        for table, fields in evidence.items():
            person = any(sig["person"] >= 6 and sig["name_shape"] >= 8 and sig["organization"] < 5
                         for sig in fields.values())
            contact = any(sig["email"] >= 8 or sig["valid_phone"] >= 7 for sig in fields.values())
            organization = table in known_organizations or any(sig["organization"] >= 8 for sig in fields.values())
            model_role = roles.get(table, "u")
            if not person and (organization or model_role == "o" and has(table, BUSINESS)):
                cloud_roles[table] = "o"
            elif person and contact and not organization and model_role != "e":
                cloud_roles[table] = "p"
    metadata_roots = set()
    for row in rows:
        t, c = row["table_name"], row["column_name"]
        grouped[t][c] = row
        explicit_person = has(t, PERSON_ROLES) and not has(t, BUSINESS)
        role = cloud_roles.get(t, "p" if t in observed_people else roles.get(t, "p" if explicit_person else "u"))
        primary = tables[t]["primary_key"]["constrained_columns"]
        if primary and explicit_person and roles.get(t) == "p":
            metadata_roots.add(t)
        suggestion = candidate.get((t, c), ("unknown", "u"))
        sig = evidence[t][c]
        kind, confirmed = choose_type(row, columns[t][c], sig, role, suggestion)
        if (cloud_roles.get(t) == "o" and sig["organization"] >= 8
                and kind in {"unknown", "unknown_field", "free_text", "identifier"}):
            kind, confirmed = "organization_name", True
        if (cloud_roles.get(t) == "p" and sig["person"] >= 8 and sig["name_shape"] >= 9
                and kind in {"unknown", "unknown_field", "free_text", "identifier"}):
            kind, confirmed = "person_name", True
        if (t in roles and kind == "person_name" and cloud_roles.get(t) != "p"
                and role != "p" and not explicit_person):
            kind, confirmed = (row["semantic_type"], False) if row["semantic_type"] != "person_name" else ("unknown", False)
            if row["personal_linkage"] == "direct":
                row.update(personal_data="uncertain", personal_linkage="uncertain",
                           privacy_role="unresolved_subject_scope", sensitivity="undetermined",
                           personal_linkage_evidence={"method": "subject_scope_unverified", "relationship_ids": []})
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
        shared_contact = sig["role_mailbox"] >= 8 or (
            bool(set(words(c).split()) & SHARED_CONTACT) and role != "p"
        )
        if (kind in {"email_address", "phone_number"} and confirmed and t in roles
                and (shared_contact or cloud_roles.get(t) == "o"
                     or role == "o" and suggestion[1] == "n")):
            row.update(personal_data="no", personal_linkage="none", sensitivity="internal",
                       privacy_role="organizational_contact",
                       personal_linkage_evidence={"method": "shared_contact_scope", "relationship_ids": []})
            row["review_dimensions"] = [d for d in row["review_dimensions"] if d != "privacy"]
        elif kind in DIRECT_TYPES and confirmed and row["personal_linkage"] != "direct":
            shared = shared_contact or has(c, BUSINESS) and role != "p"
            if not shared and (kind == "person_name" or role == "p" or suggestion[1] == "d"):
                if mark_direct(row, kind, sig):
                    row["review_dimensions"] = [d for d in row["review_dimensions"] if d != "privacy"]
            elif kind in {"email_address", "phone_number"} and (shared or role == "o"):
                row.update(personal_data="no", personal_linkage="none", sensitivity="internal",
                           privacy_role="organizational_contact")
        if kind == "person_name" and row["personal_linkage"] == "direct" and role == "p" and tables[t]["primary_key"]["constrained_columns"]:
            roots.add(t)
    additionally_supported = corroborated_subjects(
        tables, evidence, candidate, roles, incoming,
        known_organizations | {t for t, role in cloud_roles.items() if role == "o"},
    ) if getattr(provider, "remote", False) else set()
    independent_roots = additionally_supported - roots - metadata_roots
    inferred_roots = roots | metadata_roots | additionally_supported
    barriers = ({t for t, role in roles.items() if role == "o" and cloud_roles.get(t) != "p"}
                | {t for t, role in cloud_roles.items() if role == "o"}) - inferred_roots
    for edge in relationships["edges"]:
        source, target = edge["source"], edge["target"]
        if source not in inferred_roots and target in inferred_roots and roles.get(source, "u") in {"o", "u"}:
            if any(set(words(column).split()) & RESPONSIBILITY for column in edge["data"]["source_columns"]):
                barriers.add(source)
    apply_privacy(connection, rows, tables, grouped, relationships, checks, extra_roots=inferred_roots,
                  resolve_verified_subject_attributes=True, subject_barriers=barriers,
                  check_context_scope=bool(cloud_roles), corroborated_roots=independent_roots)
    if getattr(provider, "experimental_purpose_domains", False):
        relationship_domains(provider, grouped, tables, relationships, checks, inferred_roots)
    else:
        contextual_domains(provider, grouped, tables, relationships, checks)
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
                if (measured.get("method") == "measured_subject_path"
                        and measured.get("subject_evidence") != "corroborated_entity"
                        and measured["matched_source_rows"] == measured["source_rows"]):
                    row["review_dimensions"] = [d for d in row["review_dimensions"] if d != "privacy"]
            if (row["personal_data"] == "uncertain" or t in metadata_roots - roots
                    and row["personal_linkage"] == "linked") and "privacy" not in row["review_dimensions"]:
                row["review_dimensions"].append("privacy")
            row["semantic_path"] = list(dict.fromkeys(x for x in (row["semantic_category"], kind) if x != "unknown"))
            row["classification_resolution"] = row["subtype_status"] if kind != "unknown" else "unresolved"
            row["review_required"] = bool(row["review_dimensions"])
    return rows, {"missing_context_fields": missing, "entity_model_loaded": entity.pipeline is not None,
                  "additional_person_anchors": len(independent_roots)}
