from collections import Counter, defaultdict

from backend.app.classification.taxonomy import DOMAINS

PURPOSES = {
    "healthcare": "Organize clinical observations and care-delivery data.",
    "education": "Understand learning services and academic participation.",
    "logistics": "Track shipments and operational coordination.",
    "insurance": "Understand policy administration and claims activity.",
    "hospitality": "Understand reservations and guest services.",
    "customer": "Understand customer coverage and service needs.",
    "workforce": "Understand staffing and support capacity.",
    "catalog": "Compare the service portfolio and pricing.",
    "commerce": "Analyze transactions and demand trends.",
    "finance": "Understand payment and revenue patterns.",
    "support": "Identify recurring support needs and priorities.",
    "operations": "Monitor usage and service delivery.",
}


def restrictions(fields):
    personal = any(field["personal_data"] != "no" for field in fields)
    sensitive = any(field["sensitivity"] in {"confidential", "restricted", "undetermined"}
                    for field in fields)
    return {
        "personal_data_present_or_uncertain": personal,
        "sensitive_or_unresolved_data": sensitive,
        "constraints": (["Confirm permitted purpose and access with the data owner.",
                         "Restrict access to individual-level data and protect join keys."]
                        if personal or sensitive else ["Use data within the established access scope."]),
    }


def build_domains(predictions, relationships, quality):
    grouped = defaultdict(list)
    field_domains = {}
    for field in predictions:
        domain = field["data_domain"]
        grouped[domain].append(field)
        field_domains[field["table_name"], field["column_name"]] = domain

    links = defaultdict(list)
    for edge in relationships["edges"]:
        data = edge["data"]
        if data["kind"] != "declared":
            continue
        for origin, target in zip(data["source_columns"], data["target_columns"]):
            left = field_domains.get((edge["source"], origin))
            right = field_domains.get((edge["target"], target))
            if left is not None and right is not None and left != right:
                for domain, other, direction in ((left, right, "outgoing"), (right, left, "incoming")):
                    link = {"relationship_id": edge["id"], "other_domain": other, "direction": direction}
                    if link not in links[domain]:
                        links[domain].append(link)

    result = []
    for domain, fields in sorted(grouped.items()):
        tables = defaultdict(list)
        for field in fields:
            tables[field["table_name"]].append({
                "column_name": field["column_name"], "semantic_type": field["semantic_type"],
                "membership_reason": f"Classified into {domain} with semantic type {field['semantic_type']}.",
                "classification_evidence_sources": sorted(
                    {item["source"] for item in field.get("supporting_evidence", [])}),
            })
        result.append({
            "domain_name": domain,
            "description": (DOMAINS[domain][0].capitalize() + "." if domain in DOMAINS
                            else "Fields whose business domain needs confirmation."),
            "purpose_and_business_value": PURPOSES.get(domain, "Resolve classification before use."),
            "included_tables": [{"table_name": table, "columns": columns} for table, columns in tables.items()],
            "boundaries": "Membership applies to listed fields. Declared links connect domains without assigning membership.",
            "relationships": links[domain],
            "personal_data_counts": dict(Counter(field["personal_data"] for field in fields)),
            "sensitivity_counts": dict(Counter(field["sensitivity"] for field in fields)),
            "quality_limitations": quality["domains"].get(domain, {}),
            "usage_restrictions": restrictions(fields),
            "review_fields": [{"table_name": field["table_name"], "column_name": field["column_name"]}
                              for field in fields if field["review_required"] or domain == "unknown"],
            "generation_method": "deterministic_rules",
        })
    return {"domains": result}
