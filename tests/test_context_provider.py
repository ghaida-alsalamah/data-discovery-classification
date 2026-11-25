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
    report = AssetScan().scan(source)
    assert report["mode"] == "contextual" and report["context_runtime"] == "offline"
    fields = {(r["table_name"], r["column_name"]): r for r in report["classifications"]}
    assert fields["Equipment", "owner_id"]["personal_linkage"] == "linked"
    assert fields["Equipment", "acquired_on"]["personal_linkage"] != "linked"
    assert fields["Inspections", "equipment_id"]["personal_linkage"] != "linked"
    assert "contact.1@example.org" not in json.dumps(report)

def test_free_groq_uses_fixed_model_and_stops_at_quota(tmp_path):
    from backend.app.classification.context_provider import FreeCatalogProvider

    env = tmp_path / ".env"
    env.write_text("GROQ_API_KEY=test-key\n")
    calls = []

    def handler(request):
        calls.append(request)
        assert request.url.host == "api.groq.com"
        body = json.loads(request.content)
        assert body["model"] == "openai/gpt-oss-120b"
        assert body["response_format"]["json_schema"]["strict"] is True
        assert "test-key" not in request.content.decode()
        return httpx.Response(429)

    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        provider = FreeCatalogProvider(client, "groq", env)
        with pytest.raises(httpx.HTTPStatusError):
            provider.classify([{"table": "t0", "fields": [["email", "t", "", "E10"]]}], 1)
        with pytest.raises(ValueError, match="paused"):
            provider.classify([], 0)
    assert len(calls) == 1
    assert provider.counters["http_429"] == 1


def test_free_provider_domains_validate_cluster_representatives(tmp_path):
    from backend.app.classification.context_provider import FreeCatalogProvider

    env = tmp_path / ".env"
    env.write_text("GROQ_API_KEY=test-key\n")

    def handler(request):
        body = json.loads(request.content)
        assert body["response_format"]["json_schema"]["schema"]["required"] == ["groups"]
        assert body["model"] == "openai/gpt-oss-120b"
        return httpx.Response(200, json={
            "usage": {"prompt_tokens": 20, "completion_tokens": 10},
            "choices": [{"finish_reason": "stop", "message": {"content": '{"groups":[1,0]}'}}],
        })

    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        provider = FreeCatalogProvider(client, "groq", env)
        with pytest.raises(ValueError, match="representative"):
            provider.domain_groups([{"i": 0, "links": [1]}, {"i": 1, "links": []}])

def test_role_mailboxes_are_distinct_from_named_contacts_and_require_samples():
    from backend.app.classification.contextual_catalog import contact_scope

    assert contact_scope(["support@example.org", "sales.uk@example.org", "help+booking@example.org"]) == 10
    assert contact_scope(["jane.smith@example.org", "matt@example.org", "alex@example.org"]) == 0
    assert contact_scope(["support@example.org"]) == 0

def test_verified_target_context_uses_opaque_ids_and_bounded_flags():
    table = {"name": "OpaqueOrchid", "primary_key": {"constrained_columns": []},
             "foreign_keys": [], "columns": [{"name": "AmberCanary", "type": "TEXT"}]}
    target = {"name": "SecretMagnolia", "primary_key": {"constrained_columns": []},
              "foreign_keys": [], "columns": []}
    stats = {"OpaqueOrchid": {"AmberCanary": {}}, "SecretMagnolia": {
        "hidden": {"size": 10, "person": 9, "email": 0, "valid_phone": 0,
                   "raw": "sensitive.person@example.org"},
    }}
    outgoing = {"OpaqueOrchid": [{"target": "SecretMagnolia",
                                  "data": {"source_columns": ["AmberCanary"]}}]}
    payload, _ = next(batches({"tables": [table, target]}, stats, True, outgoing=outgoing))
    assert payload[0]["targets"] == [["t1", [""], True, False]]
    assert "Magnolia" not in json.dumps(payload) and "sensitive.person" not in json.dumps(payload)

def test_corroborated_anchor_does_not_require_a_verified_name_classification():
    from backend.app.classification.contextual_catalog import corroborated_subjects

    blank = dict(size=24, organization=0, name_shape=0, person=0,
                 email=0, valid_phone=0, unique=10, role_mailbox=0)
    evidence = {"registrants": {
        "caption": dict(blank, name_shape=10),
        "mail": dict(blank, email=10),
        "contact": dict(blank, valid_phone=10),
    }}
    tables = {"registrants": {"primary_key": {"constrained_columns": ["k"]}}}
    candidates = {("registrants", field): (kind, "d") for field, kind in
                  (("caption", "person_name"), ("mail", "email_address"), ("contact", "phone_number"))}
    incoming = {"registrants": [{"id": "member_reference"}]}
    assert corroborated_subjects(tables, evidence, candidates, {}, incoming, set()) == {"registrants"}
    assert corroborated_subjects(tables, evidence, candidates, {}, {}, set()) == set()
    assert corroborated_subjects(tables, evidence, candidates, {}, incoming, {"registrants"}) == set()
    evidence["registrants"]["mail"]["role_mailbox"] = 10
    assert corroborated_subjects(tables, evidence, candidates, {}, incoming, set()) == set()

def test_unverified_name_keeps_verified_subject_branch_reachable(tmp_path):
    class Provider:
        remote = True

        def classify(self, payload, field_count):
            answers = []
            for table in payload:
                for _, storage, _, signals in table["fields"]:
                    if "E10" in signals:
                        answers.append(("email_address", "d"))
                    elif "V10" in signals:
                        answers.append(("phone_number", "d"))
                    elif storage == "d":
                        answers.append(("date", "l"))
                    else:
                        answers.append(("person_name", "d"))
            assert len(answers) == field_count
            return ["u"] * len(payload), answers

    path = tmp_path / "chain.sqlite"
    with sqlite3.connect(path) as db:
        db.executescript("""
            CREATE TABLE roster_units(k INTEGER PRIMARY KEY, caption TEXT, relay TEXT, voice TEXT);
            CREATE TABLE entry_log(k INTEGER PRIMARY KEY, u INTEGER REFERENCES roster_units(k), opened DATE);
            CREATE TABLE detail_log(k INTEGER PRIMARY KEY, e INTEGER REFERENCES entry_log(k), noted DATE);
        """)
        for i in range(12):
            db.execute("INSERT INTO roster_units VALUES (?,?,?,?)",
                       (i, "Avery Wren", f"relay.{i}@example.org", f"+1 202 555 {100+i:04d}"))
            db.execute("INSERT INTO entry_log VALUES (?,?,?)", (i, i, "2025-01-01"))
            db.execute("INSERT INTO detail_log VALUES (?,?,?)", (i, i, "2025-01-02"))
    scanner = AssetScan(provider=Provider())
    scanner.entity.pipeline = None
    report = scanner.scan(path)
    rows = {(r["table_name"], r["column_name"]): r for r in report["classifications"]}
    assert rows["roster_units", "caption"]["semantic_type"] != "person_name"
    assert report["context_summary"]["additional_person_anchors"] == 1
    assert rows["entry_log", "u"]["personal_linkage"] == "linked"
    assert rows["detail_log", "e"]["personal_linkage"] == "linked"
    assert rows["detail_log", "noted"]["personal_linkage"] == "linked"
    assert "privacy" in rows["detail_log", "noted"]["review_dimensions"]

def test_purpose_partitions_do_not_merge_distinct_scopes_or_colliding_labels():
    from backend.app.classification.contextual_catalog import relationship_domains

    class Provider:
        def purpose_groups(self, payload):
            assert [entry["scope"] for entry in payload] == ["person", "activity", "reference"]
            return [0, 0, 2]

    names = ("roster", "submissions", "inventory")
    tables = {name: {"primary_key": {"constrained_columns": ["id"]},
                     "unique_constraints": [], "record_count": 12} for name in names}
    grouped = {name: {"id": {"column_name": "id", "semantic_type": "record_id",
                           "data_domain": "accounts", "personal_linkage": "none",
                           "semantic_verified": True}} for name in names}
    edge = {"id": "fk", "source": "submissions", "target": "roster",
            "data": {"kind": "declared", "source_columns": ["owner"], "target_columns": ["id"]}}
    relationship_domains(Provider(), grouped, tables, {"edges": [edge]},
                         {"fk": {"status": "passed", "examined_count": 12}}, {"roster"})
    assert len({fields["id"]["data_domain"] for fields in grouped.values()}) == 3
    assert grouped["roster"]["id"]["data_domain"] == "accounts"

def test_groq_timeout_recovers_only_failed_batch_in_two_halves(tmp_path, monkeypatch):
    from backend.app.classification import context_provider as context

    monkeypatch.setattr(context, "sleep", lambda _: None)
    env = tmp_path / ".env"
    env.write_text("GROQ_API_KEY=test-key\n")
    sizes = []

    def handler(request):
        body = json.loads(request.content)
        fields = json.loads(body["messages"][1]["content"])[0]["fields"]
        sizes.append(len(fields))
        if len(fields) == 4:
            raise httpx.ReadTimeout("fixture timeout", request=request)
        answer = {"roles": ["p"], "types": ["date"] * 2, "privacy": ["l"] * 2}
        return httpx.Response(200, json={"choices": [{"finish_reason": "stop",
                              "message": {"content": json.dumps(answer)}}],
                              "usage": {"prompt_tokens": 20, "completion_tokens": 20}})

    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        provider = context.FreeCatalogProvider(client, "groq", env)
        fragments = list(context.classify_fragments(
            provider, [{"table": "t0", "fields": [["", "d", "", "D10"]] * 4}], list(range(4)),
        ))
        assert sizes == [4, 2, 2]
        assert [f[1] for f in fragments] == [[0, 1], [2, 3]]
        assert provider.counters["failure_timeout"] == 1
        assert provider.counters["recovered_fields"] == 4

def test_process_domain_requires_shared_purpose_and_verified_parent():
    from evaluation.groq_architecture_holdout import corroborate_process_links

    names = ("accounts", "orders", "order_lines", "external_audits")
    tables = {name: {"primary_key": {"constrained_columns": ["id"]},
                     "unique_constraints": [], "record_count": 12} for name in names}
    grouped = {name: {"id": {"data_domain": name, "personal_linkage": "none"}} for name in names}
    edges = [{"id": str(i), "source": child, "target": parent, "data": {
                  "kind": "declared", "source_columns": [field], "target_columns": ["id"]}}
             for i, (child, parent, field) in enumerate((
                 ("orders", "accounts", "account_ref"),
                 ("order_lines", "orders", "order_ref"),
                 ("external_audits", "orders", "audited_ref"),
             ))]
    checks = {edge["id"]: {"status": "passed", "examined_count": 12} for edge in edges}
    corroborate_process_links(grouped, tables, {"edges": edges}, checks, {"accounts"})
    assert grouped["order_lines"]["id"]["data_domain"] == "orders"
    assert grouped["external_audits"]["id"]["data_domain"] == "external_audits"
    assert grouped["accounts"]["id"]["data_domain"] == "accounts"
