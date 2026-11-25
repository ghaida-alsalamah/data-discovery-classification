import json
import sqlite3

from evaluation.default_holdout import joint_by_membership
from scripts.scan_data_asset import AssetScan


def test_default_catalog_validates_identifiers_and_keeps_source_values_local(tmp_path):
    path = tmp_path / "synthetic.sqlite"
    with sqlite3.connect(path) as connection:
        connection.executescript("""
            CREATE TABLE Resident(SSN TEXT PRIMARY KEY, first_name TEXT, last_name TEXT, home_phone TEXT);
            CREATE TABLE Asset(id INTEGER PRIMARY KEY, asset_phone TEXT, confidential_number INTEGER);
            CREATE TABLE Registry(id INTEGER PRIMARY KEY, owner_ref TEXT REFERENCES Resident(SSN));
        """)
        for i in range(1, 5):
            ssn = f"219-09-981{i}"
            phone = f"+1 202 555 010{i}"
            connection.execute("INSERT INTO Resident VALUES (?,?,?,?)", (ssn, "Fixture", "Resident", phone))
            connection.execute("INSERT INTO Asset VALUES (?,?,?)", (i, phone, 83462210 + i))
            connection.execute("INSERT INTO Registry VALUES (?,?)", (i, ssn))

    report = AssetScan("default", offline=True).scan(path)
    rows = {(r["table_name"], r["column_name"]): r for r in report["classifications"]}
    assert report["mode"] == "default" and report["context_runtime"] == "offline"
    assert rows["Resident", "SSN"]["semantic_type"] == "ssn"
    assert rows["Resident", "SSN"]["direct_pii_type"] == "government_id"
    assert rows["Resident", "home_phone"]["direct_pii_type"] == "phone_number"
    assert rows["Resident", "home_phone"]["identifier_validation"]["valid"] == 4
    assert rows["Asset", "asset_phone"]["direct_pii_type"] is None
    assert rows["Registry", "owner_ref"]["personal_linkage"] == "linked"
    assert report["domains"]["domains"]
    assert report["quality"] and "opportunities" in report["opportunities"]
    exported = json.dumps(report)
    assert all(value not in exported for value in ("219-09-9811", "202 555 0101", "83462211"))


def test_joint_domain_metric_compares_full_group_membership():
    def field(expected, predicted, *, review=False):
        return {"sector": "example", "domain_true": expected, "domain_pred": predicted,
                "semantic_true": "date", "semantic_pred": "date", "personal_true": "no",
                "personal_pred": "no", "review_required": review}

    assert joint_by_membership([field("people", "directory"), field("people", "directory")])["accuracy"] == 1
    assert joint_by_membership([field("people", "directory"), field("people", "elsewhere", review=True)])["accuracy"] == 0
    assert joint_by_membership([field("people", "unknown")])["accuracy"] == 0
