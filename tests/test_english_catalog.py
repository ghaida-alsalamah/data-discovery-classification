import json

from backend.app.classification.english import normalize, purpose
from evaluation.english_fixture import generate
from scripts.scan_data_asset import AssetScan


def test_english_catalog_acceptance(tmp_path):
    root = tmp_path / "english"
    generate(root)
    report = AssetScan("english").scan(root / "english_business.sqlite", owner="Demo steward")
    fields = {(r["table_name"], r["column_name"]): r for r in report["classifications"]}
    assert len(fields) == 48
    assert report["schema"]["asset"]["access_scope"] == "read_only"
    assert fields["support_cases", "elapsedMins"]["semantic_type"] == "duration_minutes"
    assert fields["customer_directory", "home_municipality"]["semantic_type"] == "city"
    assert fields["support_cases", "subject_ref"]["privacy_role"] == "indirect_identifier"
    assert fields["support_cases", "case_id"]["privacy_role"] == "record_identifier"
    assert fields["support_cases", "asset_ref"]["privacy_role"] == "object_identifier"
    assert fields["asset_inventory", "shape_payload"]["review_required"]
    assert fields["library_loans", "borrower_ref"]["personal_linkage"] == "uncertain"
    assert any(d["domain_name"] == "library" and "table purpose" in d["description"]
               for d in report["domains"]["domains"])
    assert any(c["status"] == "issue" for c in report["quality"]["relationships"].values())
    assert report["opportunities"]["opportunities"]
    export = json.dumps(report)
    assert "@sample.invalid" not in export
    assert "The requester asked for a different collection time." not in export


def test_english_normalization_and_open_domain():
    assert normalize("dispatchMins") == "dispatch minutes"
    assert normalize("stock_qty") == "stock quantity"
    assert purpose("museum_collections", "") == ("museum", "emerging_table_purpose")
    assert purpose("random_data", "") == (None, None)
