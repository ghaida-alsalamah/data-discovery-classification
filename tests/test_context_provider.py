import json
import sqlite3

import httpx
import pytest

from backend.app.classification.context_provider import CatalogProvider, batches, parse
from scripts.scan_data_asset import AssetScan


def test_remote_model_only_receives_controlled_metadata_and_aggregate_facts():
    schema = {"tables": [{
        "name": "SecretPersonOrchid", "primary_key": {"constrained_columns": []}, "foreign_keys": [],
        "columns": [{"name": "SecretPersonOrchidEmail", "type": "TEXT"}],
    }]}
    stats = {"SecretPersonOrchid": {"SecretPersonOrchidEmail": {
        "email": 10, "unique": 8, "size": 83, "unapproved": "do-not-send@example.org",
    }}}
    payload, keys = next(batches(schema, stats, True))
    assert keys == [("SecretPersonOrchid", "SecretPersonOrchidEmail")]

    def handler(request):
        body = json.loads(request.content)
        combined = request.content.decode()
        assert "SecretPersonOrchid" not in combined and "orchid" not in combined.lower()
        assert "do-not-send@example.org" not in combined and "unapproved" not in combined
        sent = json.loads(body["messages"][1]["content"])
        assert sent[0]["fields"] == [["person email", "t", "", "E10 U8"]]
        return httpx.Response(200, json={"choices": [{"message": {"content": json.dumps(
            {"roles": ["p"], "types": ["email_address"], "privacy": ["d"]},
        )}}]})

    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        provider = CatalogProvider(client, "https://inference.example/v1", "catalog",
                                   remote=True, api_key="test-key")
        assert provider.classify(payload, 1) == (["p"], [("email_address", "d")])
        with pytest.raises(ValueError):
            CatalogProvider(client, "http://inference.example/v1", "catalog", remote=True, api_key="test-key")


def test_structured_output_rejects_missing_fields_and_unbounded_text():
    with pytest.raises(ValueError):
        parse({"roles": ["p"], "types": ["email_address"], "privacy": []}, 1, 1)
    with pytest.raises(ValueError):
        parse({"roles": ["p"], "types": ["raw.email@example.org"], "privacy": ["d"]}, 1, 1)


def test_custody_link_preserves_person_reference_without_labeling_object_attributes(tmp_path):
    source = tmp_path / "custody.sqlite"
    with sqlite3.connect(source) as db:
        db.executescript("""
            CREATE TABLE Resident(id INTEGER PRIMARY KEY, first_name TEXT, last_name TEXT, email TEXT);
            CREATE TABLE Equipment(id INTEGER PRIMARY KEY, owner_id INTEGER REFERENCES Resident(id), acquired_on TEXT);
            CREATE TABLE Inspections(id INTEGER PRIMARY KEY, equipment_id INTEGER REFERENCES Equipment(id), occurred_on TEXT);
        """)
        for i in range(1, 6):
            db.execute("INSERT INTO Resident VALUES (?,?,?,?)", (i, "Noah", "Fenwright", f"contact.{i}@example.org"))
            db.execute("INSERT INTO Equipment VALUES (?,?,?)", (i, i, "2025-06-22"))
            db.execute("INSERT INTO Inspections VALUES (?,?,?)", (i, i, "2025-09-01"))
    report = AssetScan("contextual", offline=True).scan(source)
    fields = {(r["table_name"], r["column_name"]): r for r in report["classifications"]}
    assert fields["Equipment", "owner_id"]["personal_linkage"] == "linked"
    assert fields["Equipment", "acquired_on"]["personal_linkage"] != "linked"
    assert fields["Inspections", "equipment_id"]["personal_linkage"] != "linked"
    assert "contact.1@example.org" not in json.dumps(report)
