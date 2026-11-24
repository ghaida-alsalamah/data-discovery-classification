from dataclasses import dataclass
from itertools import product

from .domains import restrictions

READY = "Ready for technical analysis"
PREPARE = "Requires preparation or review"
INSUFFICIENT = "Insufficient data"


@dataclass(frozen=True)
class Template:
    title: str
    objective: str
    benefit: str
    groups: dict
    joins: tuple = ()
    field_review: bool = False
    role_domains: tuple = ()


TEMPLATES = {
    "service_demand": Template(
        "Service demand analysis", "Compare transaction volume across catalog services.",
        "Prioritize investment in services with consistent demand.",
        {"activity": {"event": ("transaction_amount",)}, "catalog": {"label": ("service_name", "service_code")}},
        (("activity", "catalog"),)),
    "geography": Template(
        "Customer geographic distribution", "Summarize customer coverage by location.",
        "Identify coverage gaps and regional service needs.",
        {"customers": {"location": ("city", "location"), "customer": ("record_id",)}},
        role_domains=(("location", "customer"), ("customer", "customer"))),
    "transaction_trends": Template(
        "Transaction trend analysis", "Compare dated transaction amounts across time periods.",
        "Identify shifts in sales volume and monetary value.",
        {"transactions": {"event_date": ("date",), "amount": ("transaction_amount",)}}),
    "support_improvement": Template(
        "Customer support improvement", "Find frequent support topics and their priority mix.",
        "Prioritize recurring issues and improve triage.",
        {"tickets": {"topic": ("ticket_topic",), "priority": ("ticket_priority",)}}),
    "service_usage": Template(
        "Aggregated service usage", "Compare sessions and duration across catalog services.",
        "Understand adoption and resource demand by service.",
        {"usage": {"sessions": ("session_count",), "duration": ("duration_minutes",)},
         "catalog": {"label": ("service_name", "service_code")}}, (("usage", "catalog"),)),
    "operational_efficiency": Template(
        "Operational efficiency analysis", "Compare elapsed usage time per session.",
        "Identify where service operations may warrant investigation.",
        {"activity": {"sessions": ("session_count",), "duration": ("duration_minutes",)}}),
    "payment_trends": Template(
        "Payment trend analysis", "Summarize paid amounts and payment status over time.",
        "Track collection patterns and periods with delayed payments.",
        {"payments": {"payment_date": ("date",), "amount": ("payment_amount",),
                      "status": ("payment_status",)}}),
    "contact_quality": Template(
        "Contact data quality improvement", "Assess completeness and validity of contact fields.",
        "Reduce the cost of correcting failed or unreachable contact records.",
        {"contacts": {"contact": ("email_address", "phone_number")}}, field_review=True),
}


class OpportunityEngine:
    def __init__(self, schema, relationships, profiles, predictions, quality):
        self.predictions = {(row["table_name"], row["column_name"]): row for row in predictions}
        self.columns = {(table["name"], col["name"]): col
                        for table in schema["tables"] for col in table["columns"]}
        self.profiles = profiles
        self.issues = {issue["id"]: issue for issue in quality["issues"]}
        self.field_issues = {(field["table_name"], field["column_name"]): field["issue_ids"]
                             for field in quality["fields"]}
        self.checks = quality["relationships"]
        self.edges = {edge["id"]: edge for edge in relationships["edges"] if self.valid_edge(edge)}

    def valid_edge(self, edge):
        data = edge["data"]
        left, right = data["source_columns"], data["target_columns"]
        return (data["kind"] == "declared" and data.get("target_schema") in (None, "main")
                and bool(left) and len(left) == len(right)
                and all((edge["source"], name) in self.columns for name in left)
                and all((edge["target"], name) in self.columns for name in right))

    def has_values(self, key):
        return self.profiles[key[0]][key[1]]["non_null_count"] > 0

    def issue_rank(self, key):
        return sum({"high": 3, "medium": 2, "low": 1}[self.issues[issue]["severity"]]
                   for issue in self.field_issues.get(key, ()))

    def candidates(self, template):
        grouped = []
        role_domains = dict(template.role_domains)
        for roles in template.groups.values():
            choices = []
            for table in sorted(self.profiles):
                chosen = {}
                for role, types in roles.items():
                    matches = [key for key, row in self.predictions.items() if
                               key[0] == table and row["semantic_type"] in types]
                    if role in role_domains:
                        matches = [key for key in matches
                                   if self.predictions[key]["data_domain"] == role_domains[role]]
                    if matches:
                        chosen[role] = min(matches, key=lambda key: (
                            not self.has_values(key), self.issue_rank(key),
                            self.predictions[key]["review_required"],
                            -self.predictions[key].get("confidence", 0), key))
                if chosen:
                    choices.append(chosen)
            grouped.append(choices or [{}])
        for parts in product(*grouped):
            yield {role: field for part in parts for role, field in part.items()}

    def required_edges(self, template, bindings, proposed=None):
        links, missing = [], []
        for origin, target in template.joins:
            left = {bindings[role][0] for role in template.groups[origin] if role in bindings}
            right = {bindings[role][0] for role in template.groups[target] if role in bindings}
            choices = [key for key, edge in self.edges.items()
                       if edge["source"] in left and edge["target"] in right
                       and edge["source"] != edge["target"]
                       and (proposed is None or key in proposed)]
            if choices:
                links.append(min(choices, key=lambda key: (
                    self.checks.get(key, {}).get("status") != "passed", key)))
            else:
                missing.append(f"Declared relationship from {origin} to {target}.")
        return links, missing

    def evaluate(self, template_id, bindings, relationship_ids=None):
        template = TEMPLATES[template_id]
        allowed = {role: types for roles in template.groups.values() for role, types in roles.items()}
        role_domains = dict(template.role_domains)
        if any(role not in allowed or key not in self.columns or key not in self.predictions
               or self.predictions[key]["semantic_type"] not in allowed[role]
               or (role in role_domains and self.predictions[key]["data_domain"] != role_domains[role])
               for role, key in bindings.items()):
            raise ValueError("Invalid opportunity field reference or semantic role.")
        if any(len({bindings[role][0] for role in roles if role in bindings}) > 1
               for roles in template.groups.values()):
            raise ValueError("Fields in an opportunity group must be in the same table.")
        missing = [f"Populated {role} field ({', '.join(types)})."
                   for role, types in allowed.items() if role not in bindings or not self.has_values(bindings[role])]
        links, missing_links = self.required_edges(template, bindings, relationship_ids)
        missing.extend(missing_links)
        if relationship_ids is not None and (
                missing or sorted(relationship_ids) != sorted(links)):
            raise ValueError("Opportunity prerequisites or relationship references could not be verified.")

        required = set(bindings.values())
        for link in links:
            edge = self.edges[link]
            required.update((edge["source"], col) for col in edge["data"]["source_columns"])
            required.update((edge["target"], col) for col in edge["data"]["target_columns"])
        all_fields = [self.predictions[key] for key in sorted(required) if key in self.predictions]
        privacy = restrictions(all_fields)
        if len(all_fields) < len(required):
            privacy["personal_data_present_or_uncertain"] = True
            privacy["sensitive_or_unresolved_data"] = True
            privacy["constraints"] = ["Review the classification and access scope for the unclassified keys."]
        protect = privacy["personal_data_present_or_uncertain"] or privacy["sensitive_or_unresolved_data"]
        quality_ids = sorted({issue for key in required for issue in self.field_issues.get(key, ())})
        limitations = [{"issue_id": issue, "severity": self.issues[issue]["severity"],
                        "description": self.issues[issue]["description"]} for issue in quality_ids]
        key_review = any(self.checks.get(link, {}).get("status") != "passed" for link in links)
        if key_review:
            limitations.append({"description": "A required relationship failed or lacked eligible integrity checks."})
        data_review = any(self.issues[issue]["severity"] in {"medium", "high"} for issue in quality_ids)
        # Key-only review flags can reflect uncertain person linkage, handled by access constraints.
        classification_review = any(self.predictions[key]["review_required"] for key in bindings.values())
        status = INSUFFICIENT if missing else PREPARE if (
            key_review or data_review or classification_review or template.field_review
        ) else READY
        next_step = {
            INSUFFICIENT: "Obtain the missing fields or verified relationships before analysis.",
            PREPARE: "Resolve the listed limitations and review essential fields before analysis.",
            READY: "Prototype aggregate analysis with the stated access and privacy constraints.",
        }[status]
        return {
            "template_id": template_id, "title": template.title, "description": template.objective,
            "business_objective": template.objective, "expected_benefit": template.benefit,
            "relevant_domains": sorted({row["data_domain"] for row in all_fields}),
            "required_fields": [{"table_name": key[0], "column_name": key[1]}
                                for key in sorted(required)],
            "semantic_bindings": {role: {"table_name": key[0], "column_name": key[1]}
                                  for role, key in bindings.items()},
            "required_relationships": links,
            "feasibility_explanation": (
                "Discovered semantic fields and declared relationships satisfy the template's structural prerequisites."
                if not missing else "Discovered fields and relationships satisfy only part of the template."),
            "data_quality_limitations": limitations, "privacy_and_usage_constraints": privacy,
            "privacy_preserving_measures": [
                "Select only the fields needed and return aggregates.",
                "Pseudonymize join keys, suppress small groups and restrict individual-level access.",
            ] if protect else ["Select only the fields needed and prefer aggregates."],
            "missing_prerequisites": missing, "readiness_status": status,
            "recommended_next_steps": [next_step], "generation_method": "deterministic_rules",
        }

    def deterministic_results(self):
        results = []
        for template_id, template in TEMPLATES.items():
            candidates = (self.evaluate(template_id, bindings) for bindings in self.candidates(template))
            results.append(min(candidates, key=lambda row: (
                len(row["missing_prerequisites"]), row["readiness_status"] != READY,
                len(row["data_quality_limitations"]),
                -len(row["semantic_bindings"]))))
        return results
