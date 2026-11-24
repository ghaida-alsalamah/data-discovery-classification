import json
from copy import deepcopy

import pytest
from sqlalchemy import create_engine

from backend.app.classification.ai_evidence import DEFAULT_MODEL_PATH, PresidioEvidence, SemanticEvidence
from backend.app.classification.detectors import detect, detection_summary, id_checksum
from backend.app.classification.engine import HybridClassifier, ReviewThresholds, name_only_baseline
from backend.app.discovery.schema import discover
from backend.app.profiling.columns import profile_database
from scripts.evaluate import evaluate_predictions


def unusable_id(prefix, index):
    candidate = f"{prefix}{index:09d}"
    return candidate[:-1] + str((int(candidate[-1]) + 1) % 10) if id_checksum(candidate) else candidate


def test_structural_detection_keeps_invalid_saudi_values():
    national = unusable_id(1, 7390)
    resident = unusable_id(2, 7390)
    values = [national, resident, "+966 00 000 0142", "SA00" + "0" * 19 + "7"]
    summary = detection_summary(values)
    assert summary["saudi_national_id"]["checksum_invalid"] == 1
    assert summary["saudi_residency_id"]["checksum_invalid"] == 1
    assert summary["phone_number"]["format_invalid"] == 1
    assert summary["saudi_iban"]["format_invalid"] == 1
    assert summary["saudi_iban"]["checksum_invalid"] == 1
    assert all(value not in json.dumps(summary) for value in values)


def test_bilingual_names_email_and_calendar_validation():
    assert "person_name" in detect("Amal Example")
    assert "person_name" in detect("هدى مثال")
    assert "person_name" not in detect("not-a-name-123")
    assert detect("sample@example.test")["email_address"].format_valid
    assert not detect("bad..mail@example.test")["email_address"].format_valid
    assert not detect("2024-02-31")["date"].format_valid
    assert detect("٢٩/٠٢/٢٠٢٤")["date"].format_valid


@pytest.fixture(scope="module")
def independent_source():
    engine = create_engine("sqlite://")
    with engine.begin() as connection:
        connection.exec_driver_sql(
            "CREATE TABLE intake (id INTEGER PRIMARY KEY, opaque TEXT, postal_city TEXT,"
            " full_name TEXT, mystery_col TEXT, contact_email TEXT)"
        )
        rows = [(i, unusable_id(2, 7980 + i), f"SA00{i:020d}",
                 "ريم عينة" if i % 2 else "Nora Sample",
                 "---" if i % 2 else "n/a", f"fixture{i}@example.test")
                for i in range(1, 21)]
        connection.exec_driver_sql("INSERT INTO intake VALUES (?, ?, ?, ?, ?, ?)", rows)
        schema, _ = discover(connection)
        profiles = profile_database(connection, schema, sample_size=7)
    engine.dispose()
    return schema, profiles, rows


def test_hybrid_generalizes_to_unknown_and_misleading_names(independent_source):
    schema, profiles, _ = independent_source
    results = {row["column_name"]: row for row in HybridClassifier().classify(schema, profiles)}
    assert results["opaque"]["semantic_type"] == "saudi_residency_id"
    assert results["opaque"]["personal_data"] == "yes"
    assert results["opaque"]["sensitivity"] == "restricted"
    assert any("checksum" in warning for warning in results["opaque"]["data_quality_warnings"])
    assert results["postal_city"]["semantic_type"] == "saudi_iban"
    assert results["postal_city"]["contradictory_evidence"]
    assert results["postal_city"]["review_required"]
    assert results["full_name"]["semantic_type"] == "person_name"
    assert results["mystery_col"]["semantic_type"] == "unknown"
    assert results["mystery_col"]["personal_data"] == "uncertain"
    assert results["mystery_col"]["review_required"]
    assert results["id"]["semantic_type"] == "record_id"


def test_declared_reference_supplies_type_and_personal_context():
    engine = create_engine("sqlite://")
    with engine.begin() as connection:
        connection.exec_driver_sql("CREATE TABLE staff (entry INTEGER PRIMARY KEY)")
        connection.exec_driver_sql(
            "CREATE TABLE timesheets (entry INTEGER PRIMARY KEY, z INTEGER REFERENCES staff(entry))"
        )
        connection.exec_driver_sql("INSERT INTO staff VALUES (1)")
        connection.exec_driver_sql("INSERT INTO timesheets VALUES (1, 1)")
        schema, _ = discover(connection)
        profiles = profile_database(connection, schema)
    predictions = HybridClassifier().classify(schema, profiles)
    reference = next(row for row in predictions if row["column_name"] == "z")
    assert reference["semantic_type"] == "reference_id"
    assert reference["personal_data"] == "yes"
    assert reference["supporting_evidence"][0]["source"] == "foreign_key"


def test_review_thresholds_are_configurable(independent_source):
    schema, profiles, _ = independent_source
    def predict(threshold):
        classifier = HybridClassifier(thresholds=ReviewThresholds(minimum_confidence=threshold,
                                                                  minimum_margin=0))
        return next(row for row in classifier.classify(schema, profiles)
                    if row["column_name"] == "full_name")

    assert not predict(0.50)["review_required"]
    assert predict(1.0)["review_required"]


def test_sample_covers_late_records_reproducibly():
    engine = create_engine("sqlite://")
    with engine.begin() as connection:
        connection.exec_driver_sql("CREATE TABLE survey (id INTEGER PRIMARY KEY, opt TEXT)")
        connection.exec_driver_sql("INSERT INTO survey VALUES (?, ?)", [
            (i, "?" if i < 50 else "anon@example.test") for i in range(1, 101)
        ])
        schema, _ = discover(connection)
        first = profile_database(connection, schema, sample_size=8)
        second = profile_database(connection, schema, sample_size=8)
    result = first["survey"]["opt"]
    assert first == second
    assert result["total_count"] == 100
    assert result["sample_count"] == 8
    assert result["local_detection"]["email_address"]["structural"] == 4
    assert "distinct_count" in result["statistic_scope"]["full_column"]
    assert "local_detection" in result["statistic_scope"]["sample"]


def test_profiles_suppress_numeric_summary_for_identifier_columns():
    engine = create_engine("sqlite://")
    with engine.begin() as connection:
        connection.exec_driver_sql("CREATE TABLE example (ordinal INTEGER PRIMARY KEY, code INTEGER)")
        values = [(i, int(unusable_id(1, 4000 + i))) for i in range(1, 8)]
        connection.exec_driver_sql("INSERT INTO example VALUES (?, ?)", values)
        schema, _ = discover(connection)
        profiles = profile_database(connection, schema)
    profile = profiles["example"]["code"]
    assert profile["numeric_statistics"] is None
    assert profile["local_detection"]["saudi_national_id"]["checksum_invalid"] == 7


def test_local_presidio_adds_evidence_and_exports_are_private(independent_source):
    schema, profiles, rows = independent_source
    profiles = deepcopy(profiles)
    presidio = PresidioEvidence()
    for index, column in ((1, "opaque"), (2, "postal_city"), (5, "contact_email")):
        profiles["intake"][column]["presidio_detection"] = presidio.summarize(
            row[index] for row in rows[:7]
        )
    predictions = HybridClassifier().classify(schema, profiles)
    residency = next(row for row in predictions if row["column_name"] == "opaque")
    assert any(item["source"] == "presidio" for item in residency["supporting_evidence"])
    arabic_id = rows[0][1].translate(str.maketrans("0123456789", "٠١٢٣٤٥٦٧٨٩"))
    assert presidio.summarize([arabic_id]) == {"saudi_residency_id": 1}
    payload = json.dumps({"profiles": profiles, "predictions": predictions}, ensure_ascii=False)
    assert all(row[field] not in payload for row in rows for field in (1, 2, 3, 5))


@pytest.mark.skipif(not (DEFAULT_MODEL_PATH / "onnx/model.onnx").is_file(),
                    reason="Download the MiniLM model to exercise local embeddings.")
def test_minilm_recognizes_bilingual_metadata():
    semantic = SemanticEvidence()
    scores, domains = semantic.compare(
        ["email address", "عنوان البريد الإلكتروني"],
        ["customer contact email address", "بيانات اتصال العميل وعنوان البريد الإلكتروني"],
        ["employee staff and human resources"],
    )
    assert all(max(row, key=row.get) == "email_address" for row in scores)
    assert max(domains[0], key=domains[0].get) == "workforce"
    assert semantic.semantic_index[1].shape[1] == 384


def test_evaluation_counts_uncertain_as_a_personal_false_negative(independent_source):
    schema, _, _ = independent_source
    baseline = name_only_baseline(schema)
    truth = {"intake": {
        row["column_name"]: {"semantic_type": row["semantic_type"], "domain": row["data_domain"],
                             "personal_data": row["column_name"] == "opaque",
                             "column_name_quality": "ambiguous" if row["column_name"] == "opaque" else "clear"}
        for row in baseline
    }}
    report = evaluate_predictions(truth, baseline)
    assert report["semantic_accuracy"]["exact"] == 1
    assert report["difficult_names"]["ambiguous"]["columns"] == 1
    assert report["personal_data"]["recall"] == 0
    assert report["personal_data"]["false_negatives"] == [
        {"table_name": "intake", "column_name": "opaque", "predicted_status": "uncertain"}
    ]
