"""Fixed synthetic acceptance cases derived from the supplied Elm Challenge 1 brief."""
import json
import sqlite3

import pytest

from scripts.scan_data_asset import AssetScan

DICTIONARY = {
    "description": "Customer service requests and finance records",
    "tables": {
        "entries": {"description": "Customer requests", "fields": {
            "q7": "Payment amount recorded for each completed request.",
            "u9": "City or location when available.",
        }},
        "entry_events": {"description": "Operations events"}
    },
}
DDL = """
CREATE TABLE resident_directory (
 id INTEGER PRIMARY KEY, full_name TEXT, email TEXT, phone TEXT, national_id TEXT, iban TEXT
);
CREATE TABLE assets (id INTEGER PRIMARY KEY, service_name TEXT, price REAL);
CREATE TABLE entries (
 id INTEGER PRIMARY KEY, x4 INTEGER REFERENCES resident_directory(id),
 item_ref INTEGER REFERENCES assets(id), q7 REAL, opened_on TEXT, u9 TEXT
);
CREATE TABLE entry_events (id INTEGER PRIMARY KEY, x5 INTEGER REFERENCES entries(id), event_date TEXT);
CREATE TABLE broken_entries (id INTEGER PRIMARY KEY, x6 INTEGER REFERENCES resident_directory(id), event_date TEXT);
CREATE TABLE empty_entries (id INTEGER PRIMARY KEY, x7 INTEGER REFERENCES resident_directory(id), event_date TEXT);
"""


def fixed_database(path):
    with sqlite3.connect(path) as con:
        con.executescript(DDL)
        for i in range(1, 9):
            base = f"1{92345000+i:08}"
            weighted = [int(digit) * (2 - index % 2) for index, digit in enumerate(base)]
            national = base + str(-sum(value if value < 10 else value - 9 for value in weighted) % 10)
            account = f"88{987654300+i:018}"
            iban = f"SA{98 - int(account + '281000') % 97:02}{account}"
            phone = f"+9665{12345000+i:08}"
            if i == 8:
                national = national[:-1] + str((int(national[-1]) + 1) % 10)
                iban = "SA00" + account
                phone = "+96600" + "0000000"
            con.execute("INSERT INTO resident_directory VALUES (?, ?, ?, ?, ?, ?)",
                        (i, "Sample Resident", f"resident-{i}@catalog.invalid", phone, national, iban))
            con.execute("INSERT INTO assets VALUES (?, ?, ?)", (i, "Fixture service", i * 110.5))
            con.execute("INSERT INTO entries VALUES (?, ?, ?, ?, ?, ?)",
                        (i, i, i, i * 35.15, f"2024-11-{i:02}", None))
            con.execute("INSERT INTO entry_events VALUES (?, ?, ?)", (i, i, f"2024-11-{i:02}"))
        con.execute("INSERT INTO broken_entries VALUES (?, ?, ?)", (1, 999, "2024-11-01"))
        con.execute("INSERT INTO empty_entries VALUES (?, ?, ?)", (1, None, "2024-11-01"))


def index(report):
    return {(r["table_name"], r["column_name"]): r for r in report["classifications"]}


@pytest.fixture(scope="module")
def acceptance(tmp_path_factory):
    db = tmp_path_factory.mktemp("elm_acceptance") / "representative.sqlite"
    fixed_database(db)
    old = AssetScan("current")
    scanner = AssetScan("enhanced")
    return db, old.scan(db), scanner.scan(db), scanner.scan(db, dictionary=DICTIONARY, owner="Demo data steward")


def test_six_challenge_requirements_and_fixed_scenario_accuracy(acceptance):
    _, old, bare, new = acceptance
    asset = new["schema"]["asset"]
    assert (asset["name"], asset["owner"], asset["access_scope"]) == (
        "representative", "Demo data steward", "read_only")
    assert len(new["schema"]["tables"]) == 6 and len(new["relationships"]["edges"]) == 5
    fields = index(new)
    assert len(fields) == 24
    assert new["profiles"]["resident_directory"]["national_id"]["local_detection"]["saudi_national_id"]["checksum_valid"] == 7
    assert new["profiles"]["resident_directory"]["phone"]["local_detection"]["phone_number"]["format_valid"] == 7
    assert new["profiles"]["resident_directory"]["iban"]["local_detection"]["saudi_iban"]["checksum_valid"] == 7
    assert fields["entries", "q7"]["data_domain"] == "finance"
    assert fields["entries", "q7"]["field_meaning"]
    domains = {row["domain_name"]: row for row in new["domains"]["domains"]}
    assert domains["finance"]["description"] and domains["finance"]["boundaries"]
    assert any(("semantic type" in row["membership_reason"] or "description" in row["membership_reason"])
               for table in domains["finance"]["included_tables"] for row in table["columns"]
               if row["column_name"] == "q7")
    assert fields["entries", "u9"]["review_required"]
    assert any(row["status"] == "issue" for row in new["quality"]["relationships"].values())
    assert any(row["missing_prerequisites"] or row["data_quality_limitations"]
               for row in new["opportunities"]["opportunities"])
    assert domains["finance"]["usage_restrictions"]["personal_data_present_or_uncertain"]
    contact = next(row for row in new["opportunities"]["opportunities"] if row["template_id"] == "contact_quality")
    assert contact["readiness_status"] == "Requires preparation or review"
    assert contact["privacy_and_usage_constraints"]["personal_data_present_or_uncertain"]

    # These outcomes are evaluation assertions only. Neither scanner collects them as inputs.
    probes = [
        (("entries", "q7"), "semantic_type", "payment_amount"),
        (("entries", "q7"), "data_domain", "finance"),
        (("entries", "x4"), "personal_linkage", "linked"),
        (("entry_events", "x5"), "personal_linkage", "linked"),
        (("entry_events", "event_date"), "personal_linkage", "linked"),
        (("broken_entries", "x6"), "personal_linkage", "uncertain"),
        (("empty_entries", "x7"), "personal_linkage", "uncertain"),
        (("entries", "item_ref"), "personal_linkage", "none"),
    ]
    def score(report):
        by_field = index(report)
        return sum(by_field[key][metric] == answer for key, metric, answer in probes)
    print(f"Fixed Elm acceptance probes: current={score(old)}/8 enhanced={score(bare)}/8 descriptions={score(new)}/8")
    assert score(new) == len(probes) and score(new) > score(old)
    assert index(bare)["entry_events", "x5"]["personal_linkage_evidence"]["method"] == "verified_relationship_path"
    direct = lambda report: {key: row["direct_pii_type"] for key, row in index(report).items()}
    assert direct(old) == direct(bare) == direct(new)
    assert "@catalog.invalid" not in json.dumps(new)


def test_specialist_review_exports_before_after(acceptance):
    db, _, _, _ = acceptance
    correction = {"table": "entries", "field": "u9", "reviewer": "Demo steward",
                  "reviewed_at": "2026-01-01T12:00:00+00:00", "reason": "Confirmed from the source contract.",
                  "changes": {"semantic_type": "location", "data_domain": "customer", "personal_data": "yes"}}
    result = AssetScan("enhanced").scan(db, dictionary=DICTIONARY, reviews=[correction])
    row = index(result)["entries", "u9"]
    assert row["review_status"] == "corrected"
    assert row["semantic_path"] == ["location"]
    assert not row["review_required"]
    assert result["review_history"][0]["before"]["semantic_type"] == "unknown"
    assert result["review_history"][0]["changes"] == correction["changes"]
    with pytest.raises(ValueError):
        AssetScan("enhanced").scan(db, dictionary={"tables": {"entries": {"fields": {"u9": {"label": "location"}}}}})
