import re
from collections import defaultdict
from dataclasses import dataclass

from .taxonomy import DOMAINS, TYPES

DIRECT = {"person_name", "saudi_national_id", "saudi_residency_id",
          "phone_number", "email_address", "saudi_iban", "salary"}
RESTRICTED = {"saudi_national_id", "saudi_residency_id", "saudi_iban", "salary"}
FORMATS = DIRECT - {"person_name", "salary"} | {"date"}
NUMERIC_ONLY = {"financial_amount", "transaction_amount", "payment_amount", "tax_amount",
                "salary", "price", "count", "session_count", "duration_minutes"}
LINKED_DOMAINS = {"customer", "workforce", "commerce", "finance", "support", "operations"}


@dataclass(frozen=True)
class ReviewThresholds:
    minimum_evidence: float = 0.46
    minimum_confidence: float = 0.70
    minimum_margin: float = 0.14
    minimum_sample: int = 5

    def __post_init__(self):
        if any(not 0 <= value <= 1 for value in
               (self.minimum_evidence, self.minimum_confidence, self.minimum_margin)):
            raise ValueError("Evidence, confidence and margin thresholds must be between 0 and 1.")
        if self.minimum_sample < 1:
            raise ValueError("Minimum sample size must be positive.")


def words(name):
    name = re.sub(r"([a-z0-9])([A-Z])", r"\1 \2", name)
    return " ".join(re.findall(r"[^\W_]+", name.casefold()))


def contains(text, phrase):
    return f" {phrase} " in f" {text} "


def lexical_scores(name):
    label = words(name)
    return {kind: max(0.86 if alias == label else 0.62
                      for alias in item.aliases if contains(label, alias))
            for kind, item in TYPES.items() if kind != "unknown"
            and any(contains(label, alias) for alias in item.aliases)}


def domain_scores(text):
    raw_tokens = words(text).split()
    tokens = set(raw_tokens) | {token.removesuffix("s") for token in raw_tokens}
    return {kind: min(1.0, 0.8 + 0.1 * (len(matching) - 1))
            for kind, (_, _, aliases) in DOMAINS.items()
            if (matching := tokens.intersection(aliases))}


def predict_domain(name, semantic=None):
    semantic = semantic or {}
    lexical = domain_scores(name)
    scores = {kind: lexical.get(kind, 0) + max(0, semantic.get(kind, 0) - 0.46) * 0.7
              for kind in DOMAINS}
    ranked = sorted(scores, key=scores.get, reverse=True)
    first, second = ranked[:2]
    return first if scores[first] >= 0.16 and scores[first] - scores[second] >= 0.035 else "unknown"


def personal_status(kind, domain, target_domain=None, related_person=False):
    if kind in DIRECT:
        return "yes"
    if kind == "unknown":
        return "uncertain"
    if kind == "reference_id":
        if target_domain in LINKED_DOMAINS:
            return "yes"
        return "no" if target_domain == "catalog" else "uncertain"
    if kind == "record_id":
        return "uncertain" if domain != "catalog" else "no"
    if related_person and kind in {
        "city", "location", "service_region", "date", "customer_segment",
        "boolean_flag", "job_title", "financial_amount", "transaction_amount", "payment_amount",
        "tax_amount", "session_count", "duration_minutes", "device_category",
    }:
        return "yes"
    if kind in {"free_text", "city", "location", "date", "financial_amount", "job_title"}:
        return "uncertain" if domain != "catalog" else "no"
    return "no"


def sensitivity_for(kind, personal):
    if kind in RESTRICTED:
        return "restricted"
    if personal == "yes":
        return "confidential"
    if personal == "uncertain":
        return "undetermined"
    return "internal"


def name_only_baseline(schema):
    rows = []
    for table in schema["tables"]:
        for column in table["columns"]:
            name = column["name"]
            scores = lexical_scores(name)
            kind = max(scores, key=scores.get, default="unknown")
            domain = predict_domain(name)
            personal = personal_status(kind, domain)
            rows.append({"table_name": table["name"], "column_name": name,
                         "semantic_type": kind, "data_domain": domain, "personal_data": personal,
                         "review_required": kind == "unknown" or personal == "uncertain"})
    return rows


class HybridClassifier:
    def __init__(self, semantic=None, thresholds=None):
        self.semantic = semantic
        self.thresholds = thresholds or ReviewThresholds()

    def classify(self, schema, profiles):
        tables = schema["tables"]
        rows = [(table, column) for table in tables for column in table["columns"]]
        if not rows:
            return []
        names = [words(col["name"]) for _, col in rows]
        contexts = []
        for (table, column), name in zip(rows, names):
            adjacent = [words(other["name"]) for other in table["columns"] if other is not column]
            targets = [words(key["referred_table"]) for key in table["foreign_keys"]
                       if column["name"] in key["constrained_columns"]]
            contexts.append(f"{name}; {words(table['name'])}; {', '.join(adjacent[:12] + targets)}")
        descriptions = [words(table["name"]) + "; " + ", ".join(
            words(col["name"]) for col in table["columns"][:12]) for table in tables]
        semantic_columns, semantic_domains = (
            self.semantic.compare(names, contexts, descriptions) if self.semantic else
            ([{} for _ in rows], [{} for _ in tables])
        )
        domains = {table["name"]: predict_domain(table["name"], scores)
                   for table, scores in zip(tables, semantic_domains)}
        return [self._classify_column(table, column, profiles[table["name"]][column["name"]],
                                      domains, similarities)
                for (table, column), similarities in zip(rows, semantic_columns)]

    def _classify_column(self, table, column, profile, domains, similarities):
        name, table_name = column["name"], table["name"]
        domain = domains[table_name]
        sample = profile["sample_count"]
        denominator = max(sample, 1)
        indicators = profile["value_indicators"]
        detectors = profile["local_detection"]
        presidio = profile.get("presidio_detection") or {}
        evidence = defaultdict(list)

        def add(kind, source, weight, detail):
            evidence[kind].append({"source": source, "weight": round(weight, 4), "detail": detail})

        lexical = lexical_scores(name)
        for kind, weight in lexical.items():
            add(kind, "column_name", weight * 0.78, "Column name matches a taxonomy alias.")
        for kind, similarity in similarities.items():
            if similarity >= 0.48:
                add(kind, "semantic_similarity", min(0.40, (similarity - 0.44) * 0.72),
                    f"Multilingual metadata cosine similarity {similarity:.3f}.")
        for kind, hits in detectors.items():
            ratio = hits["structural"] / denominator
            if ratio >= 0.15:
                strength = 0.28 if kind == "person_name" else 1.1
                if sample < self.thresholds.minimum_sample:
                    strength *= 0.65
                add(kind, "local_detector", ratio * strength,
                    f"{hits['structural']} of {sample} sample values match the structure.")
        for kind, hits in presidio.items():
            if kind in TYPES and hits / denominator >= 0.15:
                add(kind, "presidio", 0.23 * hits / denominator,
                    f"Local Presidio recognizers matched {hits} of {sample} sample values.")

        primary = name in table["primary_key"]["constrained_columns"]
        targets = [key["referred_table"] for key in table["foreign_keys"]
                   if name in key["constrained_columns"]]
        target_domains = {domains.get(target, "unknown") for target in targets}
        target_domain = sorted(target_domains & LINKED_DOMAINS)[0] if (
            target_domains & LINKED_DOMAINS) else next(iter(sorted(target_domains)), None)
        person_link = domain in {"customer", "workforce"} or any(
            domains.get(key["referred_table"]) in LINKED_DOMAINS for key in table["foreign_keys"])
        if primary:
            add("record_id", "primary_key", 1.24, "Column is part of the declared primary key.")
        if targets:
            add("reference_id", "foreign_key", 1.22, "Column participates in a declared foreign key.")
        sql_type = column["type"].upper()
        numeric_ratio = indicators["numeric"] / denominator
        if sql_type.startswith(("DATE", "TIME")):
            add("date", "sql_type", 0.8, "SQL type declares a date or time.")
        if sql_type.startswith("BOOL"):
            add("boolean_flag", "sql_type", 0.8, "SQL type declares a Boolean.")
        if sample >= 2 and indicators["binary"] == sample and profile["distinct_count"] <= 2:
            add("boolean_flag", "profiling", 0.57, "Sample is binary with at most two full-column values.")
        if indicators["currency"] / denominator >= 0.7:
            add("currency_code", "profiling", 0.91, "Most sampled values match a known currency code.")
        if (domain == "catalog" and indicators["code"] / denominator >= 0.75
                and profile["uniqueness_ratio"] >= 0.85):
            add("service_code", "profiling", 0.72, "Unique code-shaped values in a catalog context.")
        if domain == "catalog" and contains(words(name), "name"):
            add("service_name", "table_context", 0.72, "A catalog name field describes a service.")
        if numeric_ratio >= 0.7:
            for kind in NUMERIC_ONLY.intersection(lexical):
                add(kind, "profiling", 0.21, "Most sampled values use numeric storage.")
            if contains(words(name), "amount") and domain in {"commerce", "finance"}:
                kind = "transaction_amount" if domain == "commerce" else "payment_amount"
                add(kind, "table_context", 0.86, "Numeric amount in its transaction or payment domain.")
        if contains(words(name), "status") and domain in {"commerce", "finance"}:
            kind = "transaction_status" if domain == "commerce" else "payment_status"
            add(kind, "table_context", 0.88, "Status field in its transaction or payment domain.")
        if profile["uniqueness_ratio"] <= 0.5 and sample >= 5:
            for kind in lexical:
                if TYPES[kind].category in {"category", "status", "location"}:
                    add(kind, "profiling", 0.10, "Repeated values support a categorical field.")

        penalties = defaultdict(list)
        strong_formats = {kind for kind in FORMATS
                          if detectors.get(kind, {}).get("structural", 0) / denominator >= 0.60}
        for kind in evidence:
            if strong_formats and kind not in strong_formats and kind not in {"record_id", "reference_id"}:
                penalties[kind].append(("value_conflict", 0.28, "A different type dominates sampled value structures."))
            if sample >= 3 and kind in NUMERIC_ONLY and numeric_ratio < 0.4:
                penalties[kind].append(("storage_conflict", 0.30, "Sample contains little numeric data."))
            if sample >= 5 and kind in FORMATS and kind not in detectors:
                penalties[kind].append(("format_conflict", 0.27, "Sample has no matches for the expected structure."))
        scores = {kind: max(0.0, sum(item["weight"] for item in items)
                            - sum(weight for _, weight, _ in penalties[kind]))
                  for kind, items in evidence.items()}
        ranked = sorted(scores, key=lambda kind: (-scores[kind], kind))
        leader = ranked[0] if ranked else "unknown"
        top = scores.get(leader, 0.0)
        second = scores[ranked[1]] if len(ranked) > 1 else 0.0
        margin = top - second
        kind = leader if top >= self.thresholds.minimum_evidence else "unknown"

        conflict = []
        for candidate, weight in lexical.items():
            if weight >= 0.62 and candidate != kind and (
                (kind in strong_formats and TYPES[candidate].category != TYPES[kind].category)
                or ((primary or targets) and candidate in DIRECT)
            ):
                conflict.append({"source": "column_name", "candidate": candidate,
                                 "detail": "Column name suggests a different type from stronger evidence."})
        for candidate in sorted(strong_formats - {kind}):
            conflict.append({"source": "local_detector", "candidate": candidate,
                             "detail": "A competing structure also covers much of the sample."})
        conflict.extend({"source": source, "candidate": leader, "detail": detail}
                        for source, _, detail in penalties[leader])

        personal = personal_status(kind, domain, target_domain, person_link)
        if personal == "no" and (strong_formats & DIRECT or any(candidate in DIRECT for candidate in lexical)):
            personal = "uncertain"
        warnings = []
        if profile["null_percentage"]:
            warnings.append(f"{profile['null_percentage']:.1f}% of full-column records are null.")
        hits = detectors.get(kind, {})
        if hits.get("format_invalid"):
            warnings.append(f"{hits['format_invalid']} sample values failed format validation.")
        if hits.get("checksum_invalid"):
            warnings.append(f"{hits['checksum_invalid']} sample values failed checksum validation.")
        if kind in FORMATS and hits.get("structural", 0) < sample:
            warnings.append(f"{sample - hits.get('structural', 0)} sample values did not match the expected structure.")
        if kind in {"count", "session_count", "duration_minutes"} and indicators["negative"]:
            warnings.append(f"{indicators['negative']} sample values are negative.")
        if kind in {"record_id", "saudi_national_id", "saudi_residency_id"} and profile["duplicate_count"]:
            warnings.append("Full-column counts include duplicate non-null values.")
        confidence = min(1.0, top * 0.78 + min(margin, 0.65) * 0.34)
        review = (kind == "unknown" or confidence < self.thresholds.minimum_confidence
                  or margin < self.thresholds.minimum_margin or sample < self.thresholds.minimum_sample
                  or personal == "uncertain" or bool(conflict))
        supporting = sorted(evidence.get(kind, []), key=lambda item: -item["weight"])
        explanation = ("Insufficient combined evidence to select a semantic type."
                       if kind == "unknown" else
                       f"Selected {kind} from {', '.join(item['source'] for item in supporting)} evidence.")
        if conflict:
            explanation += " Competing evidence requires review."
        return {
            "table_name": table_name, "column_name": name, "semantic_type": kind,
            "data_domain": domain, "personal_data": personal,
            "sensitivity": sensitivity_for(kind, personal),
            "confidence": round(confidence, 4),
            "alternative_candidates": [{"semantic_type": candidate, "evidence_score": round(scores[candidate], 4)}
                                       for candidate in ranked if candidate != kind and scores[candidate] > 0.1][:3],
            "supporting_evidence": supporting, "contradictory_evidence": conflict,
            "explanation": explanation, "data_quality_warnings": warnings, "review_required": review,
        }
