import json

from sqlalchemy import create_engine

from backend.app.classification.context import words
from backend.app.classification.engine import HybridClassifier
from backend.app.discovery.schema import discover
from backend.app.intelligence.service import analyze
from backend.app.profiling.columns import profile_database


def test_correlated_format_evidence_does_not_override_business_context():
    engine = create_engine("sqlite://")
    values = [str(2620000200 + i) for i in range(12)]
    with engine.begin() as source:
        source.exec_driver_sql("CREATE TABLE asset_lots (batch_code TEXT, memo TEXT)")
        source.exec_driver_sql("INSERT INTO asset_lots VALUES (?, ?)",
                               [(value, "none") for value in values])
        schema, _ = discover(source)
        profiles = profile_database(source, schema)
    classifier = HybridClassifier()
    first = classifier.classify(schema, profiles)[0]
    profiles["asset_lots"]["batch_code"]["presidio_detection"] = {"saudi_residency_id": 12}
    second = classifier.classify(schema, profiles)[0]
    assert first["semantic_type"] == second["semantic_type"] == "business_identifier"
    assert first["confidence"] == second["confidence"] < .85
    assert second["personal_data"] == "uncertain" and second["review_required"]
    assert not any(value in json.dumps(second) for value in values)


def test_field_domains_and_personal_context_are_separate():
    engine = create_engine("sqlite://")
    with engine.begin() as source:
        source.exec_driver_sql("CREATE TABLE patient_register (pk INTEGER PRIMARY KEY, "
                               "full_name TEXT, base_salary REAL, invoice_currency TEXT, "
                               "national_id TEXT, unknown_payload BLOB)")
        rows = [(i, "Samira Fixture", 2500 + i, "SAR", str(1620000200 + i), b"\x00\xfa")
                for i in range(1, 13)]
        source.exec_driver_sql("INSERT INTO patient_register VALUES (?, ?, ?, ?, ?, ?)", rows)
        schema, links = discover(source)
        profiles = profile_database(source, schema)
        predictions = HybridClassifier().classify(schema, profiles)
        domains, _, opportunities = analyze(source, schema, links, profiles, predictions,
                                            use_environment=False)
    by_name = {row["column_name"]: row for row in predictions}
    assert by_name["invoice_currency"]["data_domain"] == "finance"
    assert by_name["full_name"]["data_domain"] == "healthcare"
    assert by_name["pk"]["personal_linkage"] == "linked"
    assert by_name["national_id"]["personal_data"] == "yes"
    assert by_name["national_id"]["confidence"] < .85
    assert by_name["national_id"]["review_required"]
    assert by_name["unknown_payload"]["semantic_type"] == "unknown"
    assert len(domains["domains"]) >= 3
    assert not any(row["missing_prerequisites"] for row in opportunities["opportunities"]
                   if row["readiness_status"] == "Ready for technical analysis")


def test_metadata_normalization_handles_arabic_marks_and_english_abbreviations():
    assert words("تَارِيخ_الإقَامَة") == "تاريخ الاقامة"
    assert words("DOBAddr") == "birth date address"


def test_ambiguous_identity_shaped_values_abstain_at_identifier_level():
    engine = create_engine("sqlite://")
    with engine.begin() as source:
        source.exec_driver_sql("CREATE TABLE bundles (opaque_key TEXT)")
        source.exec_driver_sql("INSERT INTO bundles VALUES (?)",
                               [(str(2620000200 + i),) for i in range(15)])
        schema, _ = discover(source)
        profiles = profile_database(source, schema)
    result, = HybridClassifier().classify(schema, profiles)
    assert result["semantic_type"] == result["semantic_category"] == "identifier"
    assert result["subtype_status"] == "uncertain"
    assert result["review_required"] and result["personal_data"] == "uncertain"
