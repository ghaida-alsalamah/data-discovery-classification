"""Usable upstream-backed classifier composition with explicit review and fallback."""
from .context import BUSINESS, IDENTITY, has
from .engine import lexical_scores
from .pretrained import DIRECT_NATIVE, DODUO_MAP, EXACT_PII
from .taxonomy import TYPES
from ..profiling.columns import sample_values
from sqlalchemy import MetaData, Table

SAMPLE_LIMIT = 12


def collect(connection, table, profiles, sample_limit=SAMPLE_LIMIT):
    source = Table(table["name"], MetaData(), autoload_with=connection, resolve_fks=False)
    return {column["name"]: sample_values(connection, source, source.c[column["name"]],
                                          profiles[column["name"]]["non_null_count"], sample_limit)
            for column in table["columns"]}


def merge(baseline, profile, ner, doduo, table_name, column_name):
    result = dict(baseline)
    kind = result["semantic_type"]
    direct = DIRECT_NATIVE.get(kind) if result["personal_data"] == "yes" else None
    result["direct_pii_status"] = "yes" if direct else "uncertain"
    result["direct_pii_type"] = direct
    result["pretrained_evidence"] = {"pii_engineer": ner, "doduo_viznet": doduo}
    if ner:
        exact = set(ner["native_majority"]) & EXACT_PII
        if len(exact) == 1:
            candidate = next(iter(exact))
            matching_profile = profile["local_detection"].get(candidate, {}).get("structural", 0)
            if (candidate in lexical_scores(column_name) or matching_profile * 2 > profile["sample_count"]):
                if not has(column_name, BUSINESS):
                    result.update(direct_pii_status="yes", direct_pii_type=candidate, personal_data="yes",
                                  personal_linkage="direct",
                                  sensitivity="restricted" if result["sensitivity"] == "restricted" else "confidential")
                    if kind in {"unknown", "identifier"}:
                        result.update(semantic_type=candidate, semantic_category=TYPES[candidate].category,
                                      subtype_status="uncertain")
                    if not direct or direct != candidate:
                        result.update(review_required=True, confidence=min(result["confidence"], .69))
        if set(ner["native_majority"]) & {"government_id", "bank_account_number"} and not direct:
            result["review_required"] = True
            result["possible_identifier_collision"] = (
                has(column_name, BUSINESS) or not has(column_name, IDENTITY))
    if doduo and result["semantic_type"] == "unknown":
        mapped = DODUO_MAP.get(doduo[0]["type"])
        if mapped:
            # Native mapped predictions are hypotheses until reviewed.
            result["pretrained_semantic_suggestion"] = mapped
            result["review_required"] = True
    return result
