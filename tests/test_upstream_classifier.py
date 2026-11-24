import json

from backend.app.classification.pretrained import DIRECT_NATIVE, PII_LABELS
from backend.app.classification.upstream import merge


def base(kind="unknown", status="uncertain"):
    return {"semantic_type": kind, "personal_data": status, "sensitivity": "undetermined",
            "review_required": False, "confidence": .55}


def test_direct_and_linked_truth_stay_separate():
    row = merge(base("date", "yes"), {"sample_count": 12, "local_detection": {}}, None,
                None, "roster", "start_day")
    assert row["personal_data"] == "yes"
    assert row["direct_pii_status"] == "uncertain"
    assert row["direct_pii_type"] is None


def test_generic_government_entity_does_not_relabel_business_code():
    native = {"samples": 12, "native_counts": {"government_id": 12},
              "native_majority": ["government_id"]}
    original = base("business_identifier", "no")
    result = merge(original, {"sample_count": 12, "local_detection": {}}, native, None,
                   "inventory", "vendor_national_id")
    assert result["semantic_type"] == "business_identifier"
    assert result["personal_data"] == "no"
    assert result["review_required"] and result["possible_identifier_collision"]


def test_promoted_exact_entity_has_aggregate_evidence_only():
    native = {"samples": 12, "native_counts": {"person_name": 9}, "native_majority": ["person_name"]}
    result = merge(base(), {"sample_count": 12, "local_detection": {"person_name": {"structural": 8}}},
                   native, None, "intake", "record_title")
    assert result["semantic_type"] == "person_name" and result["direct_pii_type"] == "person_name"
    assert result["review_required"] and result["personal_linkage"] == "direct"
    assert "synthetic raw value" not in json.dumps(result)
    assert set(DIRECT_NATIVE.values()) <= set(PII_LABELS)


def test_native_semantic_candidate_is_exposed_for_review_only():
    result = merge(base(), {"sample_count": 12, "local_detection": {}}, None,
                   [{"type": "city", "score": .97}], "directory", "z")
    assert result["semantic_type"] == "unknown"
    assert result["pretrained_semantic_suggestion"] == "city"
    assert result["review_required"]
