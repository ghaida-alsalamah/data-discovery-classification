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
        emerging = any(field.get("domain_resolution") in {"emerging_table_purpose", "discovered_table_subject", "verified_relationship_group",
                                                                "corroborated_table_group"} for field in fields)
        subject = domain.replace("_", " ")
        tables = defaultdict(list)
        for field in fields:
            resolution = field.get("domain_resolution", "uncertain")
            membership = {
                "table_subject": "The table subject identifies this business group.",
                "discovered_table_subject": "The group reflects the table subject and shared schema terms.",
                "corroborated_table_group": "Multiple content-verified fields and a declared key support the table group.",
                "verified_relationship_group": "Verified references support a shared group for this relationship table.",
                "field_context": "Several fields in the table corroborate this business context.",
                "table_purpose": "The table purpose and surrounding fields support this business domain.",
                "emerging_table_purpose": "The subject and function in the table metadata suggest an emerging domain.",
                "field_description": "The field description names this domain.",
                "table_description": "The table description provides a single domain candidate.",
                "database_description": "The database description provides a single domain candidate.",
                "semantic_type": "The detected semantic type is associated with this domain.",
                "verified_reference": "The field references a verified key assigned to this domain.",
                "specialist_review": "A specialist assigned this field to the domain.",
                "conflicting_domain_evidence": "Domain evidence conflicts and requires review.",
                "field_semantics_or_metadata": "Field semantics or schema metadata support this domain.",
                "table_and_neighbors": "The table and neighboring fields support this domain.",
            }
            tables[field["table_name"]].append({
                "column_name": field["column_name"], "semantic_type": field["semantic_type"],
                "membership_reason": (membership.get(resolution, "Available evidence leaves the domain unresolved.")
                                      if "classification_resolution" in field
                                      else f"Classified into {domain} with semantic type {field['semantic_type']}."),
                "classification_evidence_sources": sorted(
                    {item["source"] for item in field.get("supporting_evidence", [])}),
            })
        result.append({
            "domain_name": domain,
            "description": (DOMAINS[domain][0].capitalize() + "." if domain in DOMAINS
                            else f"Data about {subject} inferred from source table purpose." if emerging
                            else "Fields whose business domain needs confirmation."),
            "purpose_and_business_value": PURPOSES.get(domain, f"Understand {subject} activity and related records." if emerging
                                                                else "Resolve classification before use."),
            "included_tables": [{"table_name": table, "columns": columns} for table, columns in tables.items()],
            "boundaries": ("Membership applies to the listed fields. A verified reference can support its own field's domain."
                           if any("classification_resolution" in field for field in fields)
                           else "Membership applies to listed fields. Declared links connect domains without assigning membership."),
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
