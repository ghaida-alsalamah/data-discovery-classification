from collections import defaultdict
from dataclasses import dataclass

from .context import BUSINESS, CODE, ENTITY_TYPES, IDENTITY, PERSON, domain_mentions, has, infer_domain, words
from .taxonomy import DOMAINS, TYPES

IDS = {"saudi_national_id", "saudi_residency_id"}
DIRECT = IDS | {"phone_number", "email_address", "person_name", "saudi_iban"}
FORMATS = DIRECT - {"person_name"} | {"date"}
IDENTIFIERS = IDS | {"identifier", "business_identifier", "tracking_code", "policy_number",
                     "reservation_code", "record_id", "reference_id", "service_code"}
NUMERIC = {"financial_amount", "transaction_amount", "payment_amount", "tax_amount", "salary",
           "price", "count", "session_count", "duration_minutes", "clinical_measurement"}
FAMILIES = {
    "column_name": "metadata", "semantic_similarity": "metadata", "sql_type": "metadata",
    "local_detector": "value_pattern", "presidio": "value_pattern", "profiling": "value_pattern",
    "table_context": "table_context", "primary_key": "relationship", "foreign_key": "relationship",
    "format_validation": "validation", "named_entity": "named_entity",
}


@dataclass(frozen=True)
class ReviewThresholds:
    minimum_evidence: float = .46
    minimum_confidence: float = .70
    minimum_margin: float = .14
    minimum_sample: int = 5

    def __post_init__(self):
        if any(not 0 <= value <= 1 for value in
               (self.minimum_evidence, self.minimum_confidence, self.minimum_margin)):
            raise ValueError("Evidence, confidence and margin thresholds must be between 0 and 1.")
        if self.minimum_sample < 1:
            raise ValueError("Minimum sample size must be positive.")


def contains(text, phrase):
    return f" {phrase} " in f" {text} "


ALIASES = {kind: {words(alias) for alias in item.aliases} for kind, item in TYPES.items()}


def lexical_scores(name):
    text = words(name)
    return {kind: .83 if text in aliases else .59 for kind, aliases in ALIASES.items()
            if kind != "unknown" and any(contains(text, alias) for alias in aliases)}


def table_domain(name, semantic):
    mentions = domain_mentions(name)
    scores = {domain: (.58 if domain in mentions else 0) + max(0, semantic.get(domain, 0) - .46) * .8
              for domain in DOMAINS}
    first, second = sorted(scores, key=scores.get, reverse=True)[:2]
    return first if scores[first] >= .18 and scores[first] - scores[second] >= .04 else "unknown"


def name_only_baseline(schema):
    rows = []
    for table in schema["tables"]:
        for column in table["columns"]:
            name = column["name"]
            scores = lexical_scores(name)
            kind = max(scores, key=scores.get, default="unknown")
            domain = table_domain(name, {})
            personal = ("yes" if kind in DIRECT | {"salary"} else
                        "uncertain" if kind in {"unknown", "identifier", "location", "city", "date",
                                                "record_id", "reference_id", "free_text", "job_title",
                                                "financial_amount"} else "no")
            rows.append({"table_name": table["name"], "column_name": name, "semantic_type": kind,
                         "data_domain": domain, "personal_data": personal,
                         "review_required": kind == "unknown" or personal == "uncertain"})
    return rows


def personal_status(kind, entity, linked, target_person, target_catalog, identity_shape, business):
    if kind in DIRECT:
        return "yes", "direct"
    if kind == "reference_id":
        return ("yes", "linked") if target_person else (
            ("no", "none") if target_catalog else ("uncertain", "uncertain"))
    if kind == "record_id":
        return ("yes", "linked") if entity else (("uncertain", "uncertain") if linked else ("no", "none"))
    if kind in {"unknown", "identifier", "free_text"}:
        return "uncertain", "uncertain"
    if kind in {"business_identifier", "tracking_code", "policy_number", "reservation_code", "service_code"}:
        return ("uncertain", "uncertain") if identity_shape or linked else ("no", "none")
    if kind == "salary":
        return "yes", "linked"
    if kind in {"clinical_measurement", "clinical_code", "academic_grade"}:
        return ("yes", "linked") if linked else ("uncertain", "uncertain")
    if linked and kind not in {"currency_code", "service_name", "payment_method", "sales_channel", "department", "price"}:
        return ("uncertain", "uncertain") if business and not entity else ("yes", "linked")
    if kind in {"city", "location", "date", "job_title", "financial_amount"} and not business:
        return "uncertain", "uncertain"
    return "no", "none"


class HybridClassifier:
    def __init__(self, semantic=None, thresholds=None):
        self.semantic = semantic
        self.thresholds = thresholds or ReviewThresholds()

    def classify(self, schema, profiles):
        tables = schema["tables"]
        rows = [(table, col) for table in tables for col in table["columns"]]
        if not rows:
            return []
        names = [words(col["name"]) for _, col in rows]
        contexts = [f"{name}; {words(table['name'])}; " + ", ".join(
            words(other["name"]) for other in table["columns"][:12] if other is not column)
                    for (table, column), name in zip(rows, names)]
        descriptions = [words(table["name"]) + "; " + ", ".join(
            words(col["name"]) for col in table["columns"][:12]) for table in tables]
        if self.semantic and hasattr(self.semantic, "compare_fields"):
            sem, table_sem, field_sem = self.semantic.compare_fields(names, contexts, descriptions)
        else:
            sem, table_sem = (self.semantic.compare(names, contexts, descriptions)
                              if self.semantic else ([{}] * len(rows), [{}] * len(tables)))
            field_sem = [{}] * len(rows)
        domains = {table["name"]: table_domain(table["name"], scores)
                   for table, scores in zip(tables, table_sem)}
        people = {}
        for table in tables:
            name = table["name"]
            hints = set()
            for col in table["columns"]:
                profile = profiles[name][col["name"]]
                hints.update(kind for kind in lexical_scores(col["name"]).keys() & ENTITY_TYPES - IDS
                             if profile["local_detection"].get(kind, {}).get("structural", 0) >=
                             .65 * max(1, profile["sample_count"]))
            people[name] = (has(name, PERSON) or
                            (domains[name] in {"customer", "workforce"} and not has(name, BUSINESS))
                            or ("person_name" in hints and bool(hints - {"person_name"})))
        return [self._column(table, col, profiles[table["name"]][col["name"]], similarities,
                             field_domains, domains, people)
                for (table, col), similarities, field_domains in zip(rows, sem, field_sem)]

    def _column(self, table, column, profile, similarities, field_domains, domains, people):
        name, table_name = column["name"], table["name"]
        sample = profile["sample_count"]
        denom = max(1, sample)
        indicators = profile["value_indicators"]
        detectors = profile["local_detection"]
        ratios = {kind: hit["structural"] / denom for kind, hit in detectors.items()}
        lexical = lexical_scores(name)
        name_identity = has(name, IDENTITY) or bool(lexical.keys() & IDS)
        business = has(name, BUSINESS) or (has(table_name, BUSINESS) and not people[table_name]
                                          and not name_identity)
        key_like = has(name, CODE)
        primary = name in table["primary_key"]["constrained_columns"]
        targets = [fk["referred_table"] for fk in table["foreign_keys"]
                   if name in fk["constrained_columns"]]
        target_domains = {domains.get(target, "unknown") for target in targets}
        target_hint = next(iter(target_domains)) if len(target_domains) == 1 else None
        linked = people[table_name] or any(people.get(fk["referred_table"], False) for fk in table["foreign_keys"])
        strong_ids = {kind for kind in IDS if ratios.get(kind, 0) >= .45}
        numeric = indicators["numeric"] / denom
        evidence = defaultdict(list)

        def add(kind, source, weight, detail):
            evidence[kind].append({"source": source, "family": FAMILIES[source],
                                   "weight": round(weight, 4), "detail": detail})

        for kind, weight in lexical.items():
            add(kind, "column_name", weight, "Normalized column metadata matches a taxonomy alias.")
        for kind, similarity in similarities.items():
            if similarity >= .51:
                add(kind, "semantic_similarity", min(.47, (similarity - .46) * .87),
                    f"Multilingual metadata cosine similarity {similarity:.3f}.")
        for kind, ratio in ratios.items():
            if ratio < .15:
                continue
            hits = detectors[kind]
            weight = (.51 if kind == "person_name" else .83 if kind in IDS else .94) * ratio
            if kind in FORMATS and ratio < .55:
                weight *= .5
            if sample < self.thresholds.minimum_sample:
                weight *= .65
            add(kind, "local_detector", weight, f"Matching structure in {hits['structural']} of {sample} samples.")
            if kind in FORMATS:
                add(kind, "format_validation", 0, f"{hits['format_invalid']} format and "
                    f"{hits['checksum_invalid']} checksum failures qualify the same value evidence.")
        for kind, count in (profile.get("presidio_detection") or {}).items():
            if kind in TYPES and count / denom >= .15:
                add(kind, "presidio", 0, f"Presidio matched {count} samples using the same pattern family.")
        for kind, count in (profile.get("independent_ner_detection") or {}).items():
            if kind in TYPES and count / denom >= .5:
                add(kind, "named_entity", .70 * count / denom, "Independent entity-model evidence.")

        if primary:
            add("record_id", "primary_key", 1.28, "Column is part of the declared primary key.")
        if targets:
            add("reference_id", "foreign_key", 1.25, "Column participates in a declared foreign key.")
        sql_type = column["type"].upper()
        if sql_type.startswith(("DATE", "TIME")):
            add("date", "sql_type", .74, "Declared date or time storage.")
        if sql_type.startswith("BOOL"):
            add("boolean_flag", "sql_type", .74, "Declared boolean storage.")
        if sample >= 2 and indicators["binary"] == sample and profile["distinct_count"] <= 2:
            add("boolean_flag", "profiling", .76, "Sample is binary with at most two full-column values.")
        if indicators["currency"] / denom >= .7:
            add("currency_code", "profiling", .90, "Most sampled values match known currency codes.")
        if numeric >= .7:
            for kind in NUMERIC & lexical.keys():
                add(kind, "profiling", .25, "Sample uses numeric storage.")
            hint = domains[table_name]
            if "financial_amount" in lexical and hint in {"commerce", "finance"}:
                kind = "transaction_amount" if hint == "commerce" else "payment_amount"
                add(kind, "table_context", .62, "Numeric amount in a commercial or financial table.")
                add(kind, "column_name", .49, "Amount metadata supports a monetary interpretation.")
                add(kind, "profiling", .25, "Sample uses numeric storage.")
        if domains[table_name] == "catalog":
            if has(name, {"name", "title", "label"}):
                add("service_name", "table_context", .53, "Catalog context supports a service label.")
                add("service_name", "column_name", .46, "Field metadata describes a label.")
            if indicators["code"] / denom >= .75 and profile["uniqueness_ratio"] >= .85:
                add("service_code", "profiling", .60, "Unique code-shaped values in a catalog.")
                add("service_code", "table_context", .27, "Catalog context supports a service code.")
        if strong_ids and not (primary or targets):
            add("identifier", "profiling", .59, "Identifier shape does not identify the entity type.")
            if business and (key_like or not name_identity):
                add("business_identifier", "table_context", .62, "Business metadata supports an object reference.")
                add("business_identifier", "profiling", .25, "Values use an identifier-like structure.")

        conflict = []
        penalties = defaultdict(float)
        for kind in evidence:
            if kind in IDS and (business or not (name_identity or (people[table_name] and not key_like))):
                penalties[kind] += .82
            if kind in NUMERIC and sample >= 3 and numeric < .4:
                penalties[kind] += .32
            if kind in FORMATS and sample >= 5 and ratios.get(kind, 0) < .15:
                penalties[kind] += .37
            if kind not in IDENTIFIERS | FORMATS and any(ratios.get(k, 0) >= .65 for k in FORMATS):
                penalties[kind] += .26
        strength = {kind: {} for kind in evidence}
        for kind, items in evidence.items():
            for item in items:
                family = item["family"]
                strength[kind][family] = max(strength[kind].get(family, 0), item["weight"])
        scores = {kind: max(0., sum(families.values()) - penalties[kind])
                  for kind, families in strength.items()}
        ranked = sorted(scores, key=lambda kind: (-scores[kind], kind))
        leader = ranked[0] if ranked else "unknown"
        top = scores.get(leader, 0.)
        margin = top - (scores[ranked[1]] if len(ranked) > 1 else 0.)
        kind = leader if top >= self.thresholds.minimum_evidence else "unknown"
        if kind in FORMATS and 0 < ratios.get(kind, 0) < .55 and not (kind in IDS and name_identity):
            kind = "unknown"
        if kind not in {"unknown", "record_id", "reference_id"} and margin < .11 and len(ranked) > 1:
            rival = ranked[1]
            if kind in IDENTIFIERS and rival in IDENTIFIERS:
                kind = "identifier"
            elif TYPES[kind].category != TYPES[rival].category:
                kind = "unknown"
        if strong_ids and not (primary or targets) and (business or kind in {"identifier", "unknown"}):
            conflict.append({"source": "identity_context", "candidate": sorted(strong_ids)[0],
                             "detail": "Structure could identify a person or an object."})
        for candidate, weight in lexical.items():
            if candidate != kind and weight >= .59 and (
                (kind in FORMATS and ratios.get(kind, 0) >= .60 and TYPES[candidate].category != TYPES[kind].category)
                or ((primary or targets) and candidate in DIRECT)
            ):
                conflict.append({"source": "column_name", "candidate": candidate,
                                 "detail": "Field metadata conflicts with stronger evidence."})
        if kind in IDS and not (primary or targets) and (business or penalties[kind] >= .82):
            kind = "identifier"

        if penalties[kind] > 0 and kind != "unknown":
            conflict.append({"source": "validation", "candidate": kind,
                             "detail": "Sample evidence conflicts with the selected interpretation."})
        neighbors = [hint for other in table["columns"] if other is not column
                     for hint in sorted(domain_mentions(other["name"]))]
        domain, resolution = infer_domain(name, kind, table_name, domains[table_name],
                                          neighbors, field_domains, target_hint)
        personal, linkage = personal_status(
            kind, people[table_name], linked, any(people.get(t, False) for t in targets),
            target_hint == "catalog", bool(strong_ids), business or domain == "catalog")
        hits = detectors.get(kind, {})
        seen = hits or (detectors[max(strong_ids, key=lambda k: (ratios[k], k))] if strong_ids else {})
        warnings = []
        if profile["null_percentage"]:
            warnings.append(f"{profile['null_percentage']:.1f}% of full-column records are null.")
        for term in ("format", "checksum"):
            if seen.get(term + "_invalid"):
                warnings.append(f"{seen[term + '_invalid']} sample values failed {term} validation.")
        if kind in FORMATS and hits.get("structural", 0) < sample:
            warnings.append(f"{sample - hits.get('structural', 0)} samples did not match the selected format.")
        if kind in {"count", "session_count", "duration_minutes"} and indicators["negative"]:
            warnings.append(f"{indicators['negative']} sample values are negative.")

        independent = sum(weight >= .15 for weight in strength.get(kind, {}).values())
        confidence = min(.96, .24 + .45 * min(top, 1.40) + .20 * min(margin, .55))
        if independent < 2:
            confidence = min(confidence, .82 if primary or targets else .76)
        if kind in IDS and (not name_identity or hits.get("checksum_invalid", 0) > hits.get("checksum_valid", 0)):
            confidence = min(confidence, .79)
        if conflict:
            confidence = min(.74, confidence * .85)
        if kind in {"unknown", "identifier"}:
            confidence = min(confidence, .49)
        review = (kind in {"unknown", "identifier"} or domain == "unknown" or personal == "uncertain"
                  or confidence < self.thresholds.minimum_confidence or margin < self.thresholds.minimum_margin
                  or sample < self.thresholds.minimum_sample or bool(conflict)
                  or (kind in IDS and hits.get("checksum_invalid", 0) > hits.get("checksum_valid", 0)))
        return {
            "table_name": table_name, "column_name": name, "semantic_type": kind,
            "semantic_category": "identifier" if kind in IDENTIFIERS else TYPES[kind].category,
            "subtype_status": "uncertain" if kind in {"unknown", "identifier"} else "identified",
            "data_domain": domain, "domain_resolution": resolution, "personal_data": personal,
            "personal_linkage": linkage, "independent_evidence_families": independent,
            "sensitivity": ("restricted" if kind in IDS | {"saudi_iban", "salary"} else
                            {"yes": "confidential", "no": "internal", "uncertain": "undetermined"}[personal]),
            "confidence": round(confidence, 4), "review_required": review,
            "alternative_candidates": [{"semantic_type": candidate, "evidence_score": round(scores[candidate], 4)}
                                       for candidate in ranked if candidate != kind and scores[candidate] > .1][:3],
            "supporting_evidence": sorted(evidence.get(kind, []), key=lambda item: -item["weight"]),
            "contradictory_evidence": conflict, "data_quality_warnings": warnings,
            "explanation": ("Evidence does not support a specific semantic type." if kind in {"unknown", "identifier"}
                            else f"Selected {kind} with {independent} supporting evidence families."),
        }
