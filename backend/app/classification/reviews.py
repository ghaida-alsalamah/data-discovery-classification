"""Apply ordered specialist corrections to catalog output with a change history."""
from datetime import datetime

from .engine import IDENTIFIERS
from .taxonomy import DOMAINS, TYPES


def apply_reviews(predictions, reviews):
    if not isinstance(reviews, list):
        raise ValueError("The review file must be a list of correction records.")
    index = {(row["table_name"], row["column_name"]): row for row in predictions}
    allowed = {"semantic_type", "data_domain", "personal_data", "sensitivity"}
    domains = set(DOMAINS) | {row["data_domain"] for row in predictions} | {"unknown"}
    history = []
    for entry in reviews:
        if not isinstance(entry, dict) or set(entry) != {"table", "field", "reviewer", "reviewed_at", "reason", "changes"}:
            raise ValueError("Each correction requires table, field, reviewer, reviewed_at, reason and changes.")
        if any(not isinstance(entry[key], str) or not entry[key].strip() for key in entry.keys() - {"changes"}):
            raise ValueError("Review identity, timestamp and reason must be nonempty text.")
        if datetime.fromisoformat(entry["reviewed_at"]).utcoffset() is None:
            raise ValueError("Review timestamps must include a time zone.")
        changes = entry["changes"]
        key = (entry["table"], entry["field"])
        if key not in index or not isinstance(changes, dict) or not changes or not set(changes) <= allowed:
            raise ValueError("Review specifies an unknown field or unsupported correction.")
        valid = {"semantic_type": TYPES, "data_domain": domains, "personal_data": {"yes", "no", "uncertain"},
                 "sensitivity": {"internal", "confidential", "restricted", "undetermined"}}
        if any(not isinstance(value, str) or value not in valid[dimension] for dimension, value in changes.items()):
            raise ValueError("Review correction uses an unsupported taxonomy value.")
        row = index[key]
        history.append({**entry, "before": {dimension: row[dimension] for dimension in changes}})
        row.update(changes)
        if "semantic_type" in changes:
            kind = changes["semantic_type"]
            category = "identifier" if kind in IDENTIFIERS else TYPES[kind].category
            row.update(semantic_category=category,
                       semantic_path=list(dict.fromkeys(value for value in (category, kind) if value != "unknown")),
                       subtype_status="reviewed" if kind != "unknown" else "uncertain")
        if "data_domain" in changes:
            row["domain_resolution"] = "specialist_review"
        if "personal_data" in changes:
            row["personal_linkage"] = {"yes": "reviewed_personal", "no": "none", "uncertain": "uncertain"}[row["personal_data"]]
            row["personal_linkage_evidence"] = {"method": "specialist_review"}
            if "privacy_role" in row:
                row["privacy_role"] = {"yes": "reviewed_personal", "no": "non_personal",
                                       "uncertain": "uncertain"}[row["personal_data"]]
            if "sensitivity" not in changes:
                row["sensitivity"] = {"yes": "restricted" if row["sensitivity"] == "restricted" else "confidential",
                                      "no": "internal", "uncertain": "undetermined"}[row["personal_data"]]
        row.update(classification_resolution="specialist_review", review_status="corrected",
                   explanation="The specialist correction is recorded in review_history.",
                   review_required=any(row[key] == "unknown" for key in ("semantic_type", "data_domain"))
                   or row["personal_data"] == "uncertain" or row["sensitivity"] == "undetermined")
    return history
