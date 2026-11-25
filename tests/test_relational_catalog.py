import json
import sqlite3

from scripts.scan_data_asset import AssetScan


def test_partial_and_multihop_relationship_paths_remain_reviewable(tmp_path):
    source = tmp_path / "catalog.sqlite"
    with sqlite3.connect(source) as db:
        db.executescript("""
            CREATE TABLE people (id INTEGER PRIMARY KEY, full_name TEXT, email TEXT);
            CREATE TABLE service_jobs (id INTEGER PRIMARY KEY, holder REFERENCES people(id));
            CREATE TABLE service_steps (id INTEGER PRIMARY KEY, job_ref REFERENCES service_jobs(id),
                                        occurred TEXT, shipping_address TEXT);
            CREATE TABLE unused_slots (id INTEGER PRIMARY KEY, reserved_by REFERENCES people(id));
        """)
        for n in range(1, 9):
            db.execute("INSERT INTO people VALUES (?, ?, ?)", (n, "Fixture Resident", f"x{n}@example.invalid"))
            db.execute("INSERT INTO service_jobs VALUES (?, ?)", (n, n if n < 8 else 999))
            db.execute("INSERT INTO service_steps VALUES (?, ?, ?, ?)", (n, n, f"2025-01-{n:02d}", "42 Fixture Road"))
            db.execute("INSERT INTO unused_slots VALUES (?, ?)", (n, None))
    report = AssetScan("relational").scan(source, owner="Fixture custodian")
    rows = {(r["table_name"], r["column_name"]): r for r in report["classifications"]}
    assert rows["people", "email"]["direct_pii_status"] == "yes"
    assert rows["service_jobs", "holder"]["personal_linkage"] == "linked"
    assert rows["service_steps", "job_ref"]["privacy_role"] == "indirect_identifier"
    assert rows["service_steps", "occurred"]["personal_linkage"] == "linked"
    evidence = rows["service_steps", "job_ref"]["personal_linkage_evidence"]
    assert len(evidence["relationship_ids"]) == 2
    assert (evidence["matched_source_rows"], evidence["source_rows"]) == (7, 8)
    assert "privacy" in rows["service_steps", "job_ref"]["review_dimensions"]
    assert rows["unused_slots", "reserved_by"]["personal_linkage"] == "uncertain"
    assert "@example.invalid" not in json.dumps(report)
    assert "42 Fixture Road" not in json.dumps(report)
    assert report["schema"]["asset"]["access_scope"] == "read_only"
    assert report["domains"]["domains"] and report["opportunities"]["opportunities"]
    assert any(check["orphan_count"] == 1 for check in report["quality"]["relationships"].values()
               if "orphan_count" in check)
