import json
import sqlite3

from scripts.scan_data_asset import AssetScan


def test_evidence_catalog_checks_identity_roles_groups_and_abstention(tmp_path):
    path = tmp_path / "fixture.sqlite"
    with sqlite3.connect(path) as con:
        con.executescript("""
            CREATE TABLE directory(id INTEGER PRIMARY KEY, full_name TEXT, email TEXT);
            CREATE TABLE bayard_units(id INTEGER PRIMARY KEY, asset_code TEXT, location TEXT);
            CREATE TABLE bayard_events(id INTEGER PRIMARY KEY, unit_ref INTEGER REFERENCES bayard_units(id),
                                      subject_ref INTEGER REFERENCES directory(id), occurred TEXT, mystery TEXT);
            CREATE TABLE orphan_records(id INTEGER PRIMARY KEY, person_ref INTEGER REFERENCES directory(id));
        """)
        for i in range(1, 9):
            con.execute("INSERT INTO directory VALUES (?,?,?)", (i, "Sample Resident", f"person{i}@example.invalid"))
            con.execute("INSERT INTO bayard_units VALUES (?,?,?)", (i, f"051000000{i}", "Room Four"))
            con.execute("INSERT INTO bayard_events VALUES (?,?,?,?,?)", (i, i, i, f"2025-01-{i:02}", None))
        con.execute("INSERT INTO orphan_records VALUES (1,99)")
    result = AssetScan().scan(path)
    rows = {(r["table_name"], r["column_name"]): r for r in result["classifications"]}
    assert rows["directory", "email"]["privacy_role"] == "direct_identifier"
    assert rows["bayard_units", "asset_code"]["direct_pii_type"] is None
    assert rows["bayard_events", "subject_ref"]["privacy_role"] == "indirect_identifier"
    assert rows["bayard_events", "unit_ref"]["privacy_role"] == "object_reference"
    assert rows["bayard_events", "occurred"]["personal_linkage"] == "linked"
    assert rows["orphan_records", "person_ref"]["personal_linkage"] == "uncertain"
    assert rows["bayard_units", "location"]["data_domain"] == rows["bayard_events", "occurred"]["data_domain"]
    assert rows["bayard_events", "mystery"]["review_dimensions"]
    assert "example.invalid" not in json.dumps(result)
