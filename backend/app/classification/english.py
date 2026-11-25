"""English catalog refinements using local, aggregate content and relationship evidence."""
import re
from collections import Counter

from .context import BUSINESS, domain_mentions, has, words
from .engine import DIRECT, IDS, NUMERIC
from .taxonomy import DOMAINS, TYPES

SYNONYMS = {"mins": "minutes", "min": "minutes", "qty": "quantity", "amt": "amount",
            "ref": "reference", "no": "number", "memo": "note", "remarks": "notes",
            "municipality": "city", "town": "city", "venue": "location"}
TERMS = {
    "city": {"city", "municipality", "town"},
    "location": {"location", "venue", "storage area", "site", "facility location"},
    "duration_minutes": {"minutes", "duration", "elapsed time", "session length"},
    "status": {"status", "state", "progress", "workflow stage"},
    "payment_status": {"settlement state", "payment state", "billing status"},
    "payment_amount": {"payment amount", "settled amount", "amount paid", "payment total"},
    "tax_amount": {"tax amount", "tax total", "tax charge"},
    "price": {"replacement value", "unit cost", "list price", "unit price"},
    "count": {"quantity", "headcount", "count"},
    "category": {"class", "bucket", "category", "genre"},
    "customer_segment": {"segment", "membership tier"},
    "free_text": {"description", "note", "notes", "comment", "summary"},
}
PURPOSES = {
    "operations": {"inventory", "stock", "assets", "telemetry", "maintenance", "operations"},
    "support": {"support", "helpdesk", "help desk", "service desk", "incident"},
    "finance": {"invoice", "ledger", "finance", "billing", "receivables"},
    "customer": {"customer", "subscriber", "client"},
    "education": {"training", "attendance", "course", "student", "curriculum"},
}
FUNCTIONS = {"loans", "holdings", "catalog", "collections", "permits", "registrations",
             "events", "directory", "records", "cases", "activity"}
GENERIC = {"data", "sample", "test", "other", "misc", "unknown", "new", "table", "entity"}
CITIES = {"riyadh", "jeddah", "dammam", "mecca", "medina", "al khobar", "khobar", "taif",
          "abha", "tabuk", "yanbu", "hail", "jubail", "al ula", "arar", "qatif", "buraidah"}
STATUS = {"open", "closed", "pending", "complete", "completed", "cancelled", "canceled",
          "in progress", "active", "inactive", "approved", "rejected", "queued", "resolved"}
PAYMENT = {"paid", "unpaid", "overdue", "refunded", "settled", "failed", "partially paid"}
PLACE = {"warehouse", "depot", "building", "campus", "room", "office", "floor", "zone", "station"}
PERSON_FIELDS = {"city", "location", "customer_segment", "date", "status", "duration_minutes",
                 "payment_status", "payment_amount", "tax_amount", "academic_grade", "salary",
                 "clinical_measurement", "clinical_code", "transaction_amount"}
ORGANIZATIONAL = {"queue", "asset", "branch", "warehouse", "inventory", "office", "stock", "facility", "venue", "location"}


def normalize(value):
    return " ".join(SYNONYMS.get(word, word) for word in words(value).split())


class EnglishMetadata:
    """Expand the English inputs to the existing local embedding model."""
    def __init__(self, model):
        self.model = model

    def compare_fields(self, names, contexts, tables):
        def expand(items):
            return [normalize(item) for item in items]
        return self.model.compare_fields(expand(names), expand(contexts), expand(tables))


def mentions(text, vocabulary):
    return any(f" {term} " in f" {text} " for term in vocabulary)


def local_content(values):
    counts = Counter()
    for value in values:
        if not isinstance(value, str):
            continue
        text = normalize(value)
        if text in CITIES:
            counts["city"] += 1
        if set(text.split()) & PLACE:
            counts["location"] += 1
        if text in STATUS:
            counts["status"] += 1
        if text in PAYMENT:
            counts["payment_status"] += 1
        if len(text.split()) >= 5 and re.search(r"[.!?]$", value.strip()):
            counts["free_text"] += 1
        if re.match(r"^\s*(?:MULTI)?(?:POINT|POLYGON|LINESTRING)\s*\(", value, re.I):
            counts["unsupported_geometry"] += 1
    return counts


def purpose(table, description):
    words_ = normalize(table)
    combined = words_ + " " + normalize(description)
    declared = {kind for kind, terms in PURPOSES.items() if mentions(combined, terms)}
    if len(declared) == 1:
        return next(iter(declared)), "table_purpose"
    known = domain_mentions(combined)
    if len(known) == 1:
        return next(iter(known)), "table_purpose"
    tokens = words_.split()
    if (not declared and not known and len(tokens) >= 2 and tokens[-1] in FUNCTIONS
            and all(token.isalpha() and len(token) >= 3 and token not in GENERIC for token in tokens[:-1])):
        return "_".join(tokens[:-1]), "emerging_table_purpose"
    return None, None


def evidence(source, detail):
    return {"source": source, "family": "value_pattern" if source == "local_content" else "metadata",
            "weight": 0, "detail": detail}


def classify_field(row, profile, values, field_description, table_domain):
    name = normalize(row["column_name"])
    metadata = name + " " + normalize(field_description)
    kind = row["semantic_type"]
    if kind in {"record_id", "reference_id"}:
        return
    if kind in IDS and table_domain in {"operations", "catalog"} and has(name, {"code", "asset", "inventory", "stock"}):
        row.update(semantic_type="business_identifier", semantic_category="identifier", confidence=.64,
                   personal_data="uncertain", personal_linkage="uncertain", sensitivity="undetermined",
                   subtype_status="provisional", review_required=True,
                   explanation="Object context conflicts with a Saudi identifier-shaped value.")
        row["contradictory_evidence"] = [*row["contradictory_evidence"], {
            "source": "local_detector", "candidate": kind, "detail": "A business reference can resemble an identity number."}]
        return
    if kind in DIRECT:
        return
    sample = profile["sample_count"]
    detectors = profile["local_detection"]
    confirmed = {k for k in DIRECT - {"person_name"} if sample >= 5 and
                 detectors.get(k, {}).get("checksum_valid" if k.startswith("saudi_") else "format_valid", 0) >= .75*sample}
    identity = {"saudi_national_id": {"national", "citizen"},
                "saudi_residency_id": {"residency", "resident permit", "iqama", "permit number"}}
    candidates = [k for k in sorted(confirmed)
                  if k not in IDS or (table_domain in {"customer", "workforce", "healthcare", "education"}
                                      and mentions(metadata, identity[k]))]
    if len(candidates) == 1 and not has(name, BUSINESS):
        candidate = candidates[0]
        row.update(semantic_type=candidate, semantic_category="identifier" if candidate in IDS else TYPES[candidate].category,
                   personal_data="yes", personal_linkage="direct", confidence=.69,
                   sensitivity="restricted" if candidate.startswith("saudi_") else "confidential",
                   subtype_status="provisional", review_required=True,
                   explanation="Existing Saudi format or checksum validation supports a direct identifier.")
        row["supporting_evidence"] = [evidence("local_content", "Most sampled values passed the existing validator.")]
        return
    if confirmed & IDS and table_domain in {"operations", "catalog"} and has(name, {"code", "asset", "inventory", "stock"}):
        row.update(semantic_type="business_identifier", semantic_category="identifier", confidence=.64,
                   personal_data="no", personal_linkage="none", sensitivity="internal",
                   subtype_status="provisional", review_required=True,
                   explanation="Object context supports a business reference; identifier shape warrants review.")
        row["supporting_evidence"] = [evidence("english_metadata", "Object domain and reference terminology support this type.")]
        return
    counts = local_content(values)
    n = len(values)
    if n < 3:
        return
    if counts["unsupported_geometry"] >= .75*n:
        row.update(semantic_type="unknown", semantic_category="unknown", subtype_status="uncertain", review_required=True)
        row["supporting_evidence"] = [evidence("local_content", "Most sampled values are geometry. Geometry is outside the semantic taxonomy.")]
        return
    lexical = {k: max(len(term.split()) for term in terms if mentions(metadata, {term}))
               for k, terms in TERMS.items() if mentions(metadata, terms)}
    content = {k for k in ("city", "location", "status", "payment_status", "free_text")
               if counts[k] >= .70*n}
    numeric = profile["value_indicators"]["numeric"] >= .8 * profile["sample_count"]
    categorical = profile["distinct_count"] <= max(5, .30*profile["non_null_count"])
    options = {k: 1 + lexical.get(k, 0) for k in content}
    options.update({k: specificity + 1 for k, specificity in lexical.items()
                    if numeric and k in NUMERIC or categorical and k in {"category", "customer_segment"}})
    if "payment_status" in content and table_domain != "finance" and "payment_status" not in lexical:
        options.pop("payment_status", None)
    if "status" in content:
        options.pop("category", None)
    if not options:
        if kind == "unknown" and not row["supporting_evidence"]:
            row["supporting_evidence"] = [evidence(
                "local_content", "Available samples do not establish a supported content type.")]
        return
    rank = sorted(options, key=lambda k: (-options[k], k))
    first = rank[0]
    if len(rank) > 1 and options[first] == options[rank[1]]:
        return
    if first != kind:
        old = kind
        row.update(semantic_type=first, semantic_category=TYPES[first].category,
                   subtype_status="provisional", confidence=.68 if first in lexical else .57,
                   review_required=True, explanation="Local content and English context support the selected semantic type.")
        row["supporting_evidence"] = []
        if old != "unknown":
            row["alternative_candidates"] = [{"semantic_type": old, "evidence_score": 0},
                                             *row["alternative_candidates"]][:3]
    row["supporting_evidence"] = [*row["supporting_evidence"],
                                  evidence("local_content", "Local sample composition supports this interpretation.")]
    if first in lexical:
        row["supporting_evidence"].append(evidence("english_metadata", "An English term supports the selected type."))


def classify_content(rows, profiles, samples, metadata):
    tables = metadata.get("tables", {})
    for row in rows:
        table, field = row["table_name"], row["column_name"]
        info = tables.get(table, {})
        description = info.get("fields", {}).get(field, {}).get("description", "")
        context, _ = purpose(table, info.get("description", ""))
        classify_field(row, profiles[table][field], samples[table][field], description, context)


def refine(rows, profiles, metadata, relationships, checks, schema):
    tables = metadata.get("tables", {})
    purposes = {t: purpose(t, tables.get(t, {}).get("description", "")) for t in profiles}
    unique_keys = {t["name"]: {frozenset(t["primary_key"]["constrained_columns"])}
                   | {frozenset(key["column_names"]) for key in t["unique_constraints"]}
                   for t in schema["tables"]}
    verified = {}
    for edge in relationships["edges"]:
        if (checks.get(edge["id"], {}).get("status") == "passed"
                and frozenset(edge["data"]["target_columns"]) in unique_keys.get(edge["target"], set())):
            for field in edge["data"]["source_columns"]:
                verified.setdefault((edge["source"], field), set()).add(edge["target"])
    subject_tables = {row["table_name"] for row in rows
                      if row.get("personal_linkage_evidence", {}).get("method") == "subject_record"}
    for row in rows:
        table, field = row["table_name"], row["column_name"]
        context, source = purposes[table]
        kind = row["semantic_type"]
        targets = verified.get((table, field), set())
        reference_purposes = {purposes[t][0] for t in targets if t in purposes} - {None}
        linked = row["personal_linkage"]
        if context and row["domain_resolution"] not in {"field_description", "conflicting_domain_evidence"}:
            if kind == "reference_id" and linked != "linked" and len(reference_purposes) == 1 and not targets & subject_tables:
                row.update(data_domain=next(iter(reference_purposes)), domain_resolution="verified_reference")
            else:
                row.update(data_domain=context, domain_resolution=source)
                if source == "emerging_table_purpose":
                    row["review_required"] = True
        role = "direct_identifier" if kind in DIRECT else "uncertain"
        if kind not in DIRECT:
            organization = bool(set(normalize(field).split()) & ORGANIZATIONAL)
            if kind == "record_id":
                role = "indirect_identifier" if table in subject_tables and linked == "linked" else "record_identifier"
                if role == "record_identifier" and linked == "linked":
                    row.update(personal_data="no", personal_linkage="none", sensitivity="internal")
            elif kind in {"business_identifier", "tracking_code", "service_code"}:
                role = "object_identifier"
            elif kind == "reference_id" and linked == "linked":
                role = "indirect_identifier"
            elif kind == "reference_id" and targets and not targets & subject_tables and len(reference_purposes) == 1 and context:
                role = "object_identifier"
                row.update(personal_data="no", personal_linkage="none", sensitivity="internal")
            elif organization or kind in {"department", "category", "currency_code"}:
                role = "organizational_attribute"
                if linked == "linked":
                    row.update(personal_data="no", personal_linkage="none", sensitivity="internal")
            elif kind in PERSON_FIELDS and linked == "linked":
                role = "person_linked_attribute"
            elif linked == "linked":
                role = "uncertain"
                row.update(personal_data="uncertain", personal_linkage="uncertain", review_required=True,
                           sensitivity="restricted" if row["sensitivity"] == "restricted" else "undetermined")
            elif row["personal_data"] == "no":
                role = "non_personal"
        if linked == "linked" and row["personal_linkage"] != "linked":
            prior_path = row.pop("personal_linkage_evidence", None)
            if prior_path:
                row["subject_record_context"] = prior_path
        row["privacy_role"] = role
        row["semantic_path"] = list(dict.fromkeys(s for s in (row["semantic_category"], kind) if s != "unknown"))
        row["classification_resolution"] = row["subtype_status"] if row["semantic_path"] else "unresolved"
    return rows
