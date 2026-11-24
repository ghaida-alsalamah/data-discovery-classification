import json
from contextlib import contextmanager

import httpx
import pytest
from sqlalchemy import create_engine

from backend.app.discovery.schema import discover
from backend.app.intelligence.llm import OpenAICompatibleProvider
from backend.app.intelligence.opportunities import INSUFFICIENT, PREPARE, READY
from backend.app.intelligence.service import analyze
from backend.app.profiling.columns import profile_database


def prediction(table, column, kind, domain, personal=False):
    return {"table_name": table, "column_name": column, "semantic_type": kind,
            "data_domain": domain, "personal_data": "yes" if personal else "no",
            "sensitivity": "confidential" if personal else "internal",
            "confidence": .92, "review_required": False,
            "supporting_evidence": [{"source": "column_name", "detail": "ignored raw text"}]}


@contextmanager
def independent_source(*, poor_quality=False, declare_link=True):
    engine = create_engine("sqlite://")
    try:
        with engine.begin() as connection:
            connection.exec_driver_sql(
                'CREATE TABLE inventory (pk INTEGER PRIMARY KEY, "do not reveal label" TEXT)'
            )
            reference = "REFERENCES inventory(pk)" if declare_link else ""
            connection.exec_driver_sql(
                f"CREATE TABLE activity (key INTEGER PRIMARY KEY, item INTEGER {reference},"
                " units REAL, day_text TEXT, segment TEXT, hidden_contact TEXT UNIQUE)"
            )
            connection.exec_driver_sql(
                "INSERT INTO inventory VALUES (1, 'Synthetic Service'), (2, 'Sample Product')"
            )
            connection.exec_driver_sql("INSERT INTO activity VALUES (?, ?, ?, ?, ?, ?)", [
                (1, 1, 10, "2024-01-01", "Retail", "private@example.test"),
                (2, 1, None if poor_quality else 10, "broken date" if poor_quality else
                 "2024-02-01", "RETAIL", None),
                (3, 99 if poor_quality else 2, 20, "2024-03-01", "Retail", "bad@@mail"),
                (4, 2, 30, "2024-04-01", "Wholesale", "sample@example.test"),
            ])
            schema, links = discover(connection)
            profiles = profile_database(connection, schema)
            predictions = [
                prediction("inventory", "pk", "record_id", "catalog"),
                prediction("inventory", "do not reveal label", "service_name", "catalog"),
                prediction("activity", "key", "record_id", "commerce"),
                prediction("activity", "item", "reference_id", "commerce"),
                prediction("activity", "units", "transaction_amount", "commerce"),
                prediction("activity", "day_text", "date", "commerce"),
                prediction("activity", "segment", "category", "commerce"),
                prediction("activity", "hidden_contact", "email_address", "customer", True),
            ]
            yield connection, schema, links, profiles, predictions
    finally:
        engine.dispose()


def by_template(result, template):
    return next(row for row in result["opportunities"] if row["template_id"] == template)


def test_domain_contains_fields_from_mixed_tables_and_cross_domain_links(monkeypatch):
    monkeypatch.delenv("LLM_API_KEY", raising=False)
    with independent_source() as source:
        domains, quality, opportunities = analyze(*source)
    groups = {row["domain_name"]: row for row in domains["domains"]}
    assert set(groups) == {"catalog", "commerce", "customer"}
    customer_activity = groups["customer"]["included_tables"]
    assert customer_activity[0]["table_name"] == "activity"
    assert [row["column_name"] for row in customer_activity[0]["columns"]] == ["hidden_contact"]
    assert groups["commerce"]["relationships"] == [
        {"relationship_id": "activity:0", "other_domain": "catalog", "direction": "outgoing"}
    ]
    assert groups["customer"]["usage_restrictions"]["personal_data_present_or_uncertain"]
    assert quality["domains"]["customer"]["issue_count"] == 2
    assert opportunities["llm_status"] == "offline"
    assert all(row["generation_method"] == "deterministic_rules" for row in opportunities["opportunities"])


def test_quality_counts_and_only_checks_declared_uniqueness():
    with independent_source(poor_quality=True) as source:
        _, report, _ = analyze(*source, use_environment=False)
    checks = {(issue["column_name"], issue["code"]): issue for issue in report["issues"]}
    expected = {
        ("units", "missing_values"): (1, 4, "measured"),
        ("item", "missing_referenced_records"): (1, 4, "measured"),
        ("segment", "representation_variants"): (1, 4, "sample_based"),
        ("hidden_contact", "invalid_format"): (1, 3, "sample_based"),
        ("day_text", "invalid_format"): (1, 4, "sample_based"),
    }
    for key, (count, denominator, basis) in expected.items():
        issue = checks[key]
        assert (issue["affected_count"], issue["examined_count"], issue["basis"]) == (
            count, denominator, basis)
        assert issue["affected_fraction"] == pytest.approx(count / denominator)
    assert not any(issue["code"] == "duplicate_values" for issue in report["issues"])
    fields = {field["column_name"]: field for field in report["fields"]}
    assert fields["hidden_contact"]["dimensions"]["uniqueness"] == "passed"
    assert fields["units"]["dimensions"]["uniqueness"] == "not_evaluated"


def test_declared_composite_reference_checks_complete_keys_only():
    engine = create_engine("sqlite://")
    with engine.begin() as connection:
        connection.exec_driver_sql("CREATE TABLE parent (a INTEGER, b INTEGER, PRIMARY KEY (a,b))")
        connection.exec_driver_sql(
            "CREATE TABLE child (x INTEGER, y INTEGER, FOREIGN KEY (x,y) REFERENCES parent(a,b))")
        connection.exec_driver_sql("INSERT INTO parent VALUES (1, 2)")
        connection.exec_driver_sql("INSERT INTO child VALUES (1, 2), (1, 3), (NULL, 2)")
        schema, links = discover(connection)
        profiles = profile_database(connection, schema)
        _, quality, _ = analyze(connection, schema, links, profiles, [], use_environment=False)
    assert quality["relationships"]["child:0"]["examined_count"] == 2
    assert quality["relationships"]["child:0"]["orphan_count"] == 1
    issues = [issue for issue in quality["issues"] if issue["code"] == "missing_referenced_records"]
    assert len(issues) == 1
    assert issues[0]["columns"] == ["x", "y"]
    assert quality["tables"]["child"]["issue_count"] == 2


def test_opportunities_readiness_changes_for_quality_and_missing_prerequisites():
    with independent_source() as source:
        _, _, clean = analyze(*source, use_environment=False)
    with independent_source(poor_quality=True) as source:
        _, _, poor = analyze(*source, use_environment=False)
    with independent_source(declare_link=False) as source:
        _, _, no_join = analyze(*source, use_environment=False)
    for template in ("transaction_trends", "service_demand"):
        assert by_template(clean, template)["readiness_status"] == READY
        degraded = by_template(poor, template)
        assert degraded["readiness_status"] == PREPARE
        assert degraded["data_quality_limitations"]
    missing = by_template(no_join, "service_demand")
    assert missing["readiness_status"] == INSUFFICIENT
    assert missing["missing_prerequisites"] == ["Declared relationship from activity to catalog."]
    assert by_template(clean, "geography")["readiness_status"] == INSUFFICIENT
    contacts = by_template(clean, "contact_quality")
    assert contacts["readiness_status"] == PREPARE
    assert contacts["privacy_and_usage_constraints"]["personal_data_present_or_uncertain"]
    assert any("small groups" in measure for measure in contacts["privacy_preserving_measures"])


def mock_provider(reply, captured):
    def send(request):
        assert request.url.path == "/v1/chat/completions"
        assert request.headers["authorization"] == "Bearer test-key"
        envelope = json.loads(request.content)
        assert envelope["response_format"] == {"type": "json_object"}
        context = json.loads(envelope["messages"][1]["content"])
        captured.append(context)
        body = reply(context)
        return httpx.Response(200, json={"choices": [{"message": {"content": body}}]})

    return OpenAICompatibleProvider("https://example.test/v1", "test-key", "test-model",
                                    transport=httpx.MockTransport(send))


def opportunities_reply(context):
    fields = {row["semantic_type"]: row["id"] for row in context["fields"]}
    ref = context["declared_relationships"][0]["id"]
    return {
        "domain_focus": [{"domain": "catalog", "focus": "reporting",
                          "fields": [fields["service_name"]]}],
        "opportunities": [{"template": "service_demand", "relationships": [ref],
                           "fields": {"event": fields["transaction_amount"],
                                      "label": fields["service_name"]}}],
    }


def test_llm_http_contract_produces_locally_verified_results_and_safe_payload():
    captured = []
    provider = mock_provider(lambda context: json.dumps(opportunities_reply(context)), captured)
    with independent_source(poor_quality=True) as source:
        domains, quality, opportunities = analyze(*source, provider=provider)
    assert opportunities["llm_status"] == "accepted"
    result = by_template(opportunities, "service_demand")
    assert result["generation_method"] == "llm_assisted"
    assert result["readiness_status"] == PREPARE
    assert next(row for row in domains["domains"] if row["domain_name"] == "catalog")[
        "generation_method"] == "llm_assisted"
    private = ("private@example.test", "sample@example.test", "Synthetic Service",
               "ignored raw text", "bad@@mail")
    exported = json.dumps([domains, quality, opportunities])
    payload = json.dumps(captured)
    assert all(value not in exported and value not in payload for value in private)
    assert all(value not in payload for value in ("do not reveal label", "hidden_contact", "test-key"))


@pytest.mark.parametrize("invalid_reference", ["column", "table", "relationship", "role", "assertion", "json"])
def test_llm_rejects_unknown_references_and_unsupported_claims(invalid_reference):
    def reply(context):
        if invalid_reference == "json":
            return "not JSON"
        proposed = opportunities_reply(context)
        if invalid_reference == "column":
            proposed["opportunities"][0]["fields"]["event"] = "f999"
        if invalid_reference == "table":
            proposed["opportunities"][0]["fields"]["event"] = "imaginary_table.units"
        if invalid_reference == "relationship":
            proposed["opportunities"][0]["relationships"] = ["r999"]
        if invalid_reference == "role":
            proposed["opportunities"][0]["fields"]["event"] = proposed["opportunities"][0]["fields"]["label"]
        if invalid_reference == "assertion":
            proposed["opportunities"][0]["legal_approval"] = True
        return json.dumps(proposed)

    with independent_source() as source:
        domains, _, opportunities = analyze(*source, provider=mock_provider(reply, []))
    assert opportunities["llm_status"] == "rejected_response"
    assert all(row["generation_method"] == "deterministic_rules" for row in domains["domains"])
    assert all(row["generation_method"] == "deterministic_rules" for row in opportunities["opportunities"])


def test_provider_http_failure_falls_back_without_exposing_response():
    provider = OpenAICompatibleProvider(
        "https://example.test/v1", "secret", "test-model",
        transport=httpx.MockTransport(lambda request: httpx.Response(503, text="private provider detail")),
    )
    with independent_source() as source:
        domains, _, opportunities = analyze(*source, provider=provider)
    assert opportunities["llm_status"] == "provider_error"
    assert "private provider detail" not in json.dumps([domains, opportunities])
    assert by_template(opportunities, "service_demand")["generation_method"] == "deterministic_rules"
