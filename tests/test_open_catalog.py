import json

import pytest

from backend.app.classification.open_catalog import accept, make_payload, validate_answer


def test_open_context_payload_omits_values_and_unbounded_metadata():
    column = {"name":"contact_email", "type":"TEXT"}
    table = {"name":"contact_book", "columns":[column], "foreign_keys":[]}
    profiles = {"contact_email":{
        "sample_count":10, "distinct_count":8, "non_null_count":10, "min_length":10, "max_length":80,
        "value_indicators":{"numeric":0,"binary":0,"currency":0,"code":0},
        "local_detection":{"email_address":{"structural":9,"format_valid":8,"checksum_valid":0}},
        "patterns":[{"pattern":"person@example.invalid"}],
    }}
    payload = make_payload(table, {"contact_email":{"semantic_type":"unknown"}}, profiles,
                           {"description":"personal@example.invalid"}, {"f0":column})
    text = json.dumps(payload)
    assert "example.invalid" not in text
    assert payload["description"] == ""
    assert payload["fields"]["f0"]["detectors"] == {"email_address":[9,8]}


def test_open_type_is_provisional_and_primary_key_is_protected():
    proposal = {"type":"equipment_calibration_interval","family":"duration","privacy":"none"}
    validate_answer({"entity":"object","columns":{"f0":proposal}}, {"f0":None})
    with pytest.raises(ValueError):
        validate_answer({"entity":"object","columns":{"f0":{**proposal,"type":"raw@example.org"}}}, {"f0":None})
    row = {"semantic_type":"unknown","semantic_verified":False,"review_dimensions":["semantic"]}
    accept(row, {"name":"calibration_cycle"}, {"sample_count":10,"value_indicators":{}}, proposal, "object")
    assert row["semantic_type"] == proposal["type"]
    assert row["semantic_category"] == "duration"
    assert not row["semantic_verified"] and "semantic" in row["review_dimensions"]
    protected = {"semantic_type":"record_id","semantic_verified":True}
    accept(protected, {"name":"id"}, {}, proposal, "object")
    assert protected["semantic_type"] == "record_id"
