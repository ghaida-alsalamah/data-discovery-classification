import json
import sqlite3

import pytest
from sqlalchemy import MetaData, Table, create_engine
from sqlalchemy.exc import DatabaseError, OperationalError

from backend.app.connectors.sqlite import InformationAsset, SQLiteConnector, SourceConnectionError
from backend.app.discovery.schema import discover
from backend.app.models.synthetic import generate_database
from backend.app.profiling.columns import profile_column
from scripts.run_pipeline import run


@pytest.fixture(scope="module")
def artifacts(tmp_path_factory):
    directory = tmp_path_factory.mktemp("pipeline")
    run(directory, phase_one_only=True)
    return directory


def read_json(directory, name):
    return json.loads((directory / f"{name}.json").read_text(encoding="utf-8"))


def test_generated_database_is_reproducible_and_linked(artifacts, tmp_path):
    database = tmp_path / "second.sqlite"
    truth = tmp_path / "ground_truth.json"
    generate_database(database, truth)
    with sqlite3.connect(artifacts / "synthetic.sqlite") as first, sqlite3.connect(database) as second:
        assert list(first.iterdump()) == list(second.iterdump())
        assert first.execute("PRAGMA foreign_key_check").fetchall() == []
        assert first.execute("SELECT count(*) FROM customers").fetchone() == (1000,)
    assert read_json(tmp_path, "ground_truth") == read_json(artifacts, "ground_truth")


def test_read_only_access_and_status(artifacts):
    asset = InformationAsset("Test", "Test database", "QA")
    connector = SQLiteConnector(artifacts / "synthetic.sqlite", asset)
    with connector.connect() as source:
        assert asset.connection_status == "connected"
        with pytest.raises(OperationalError, match="readonly"):
            source.exec_driver_sql("DELETE FROM customers")
        source.exec_driver_sql("PRAGMA query_only = OFF")
        with pytest.raises(OperationalError, match="readonly"):
            source.exec_driver_sql("CREATE TABLE forbidden (id INTEGER)")
        with pytest.raises(DatabaseError, match="not authorized"):
            source.exec_driver_sql("ATTACH DATABASE ? AS writable", (str(artifacts / "synthetic.sqlite"),))
        assert source.exec_driver_sql("SELECT count(*) FROM customers").scalar() == 1000
    assert asset.connection_status == "disconnected"


def test_connection_error_creates_no_source(tmp_path):
    missing = tmp_path / "missing.sqlite"
    asset = InformationAsset("Test", "", "QA")
    with pytest.raises(SourceConnectionError), SQLiteConnector(missing, asset).connect():
        pytest.fail("Missing source unexpectedly opened")
    assert asset.connection_status == "error"
    assert not missing.exists()


def test_discovers_schema_and_labels_every_column(artifacts):
    schema = read_json(artifacts, "schema")
    truth = read_json(artifacts, "ground_truth")
    tables = {item["name"]: item for item in schema["tables"]}
    assert set(tables) == {
        "customers", "employees", "services", "transactions", "payments",
        "support_tickets", "service_usage",
    }
    assert schema["asset"]["access_scope"] == "read_only"
    assert 50 <= sum(len(table["columns"]) for table in tables.values()) <= 80
    for name, table in tables.items():
        assert set(truth[name]) == {column["name"] for column in table["columns"]}
        assert table["primary_key"]["constrained_columns"] == ["id"]
        assert table["record_count"] > 0
    customers = tables["customers"]
    assert {"name": "f01", "type": "VARCHAR", "nullable": True} in customers["columns"]
    assert ["email"] in [key["column_names"] for key in customers["unique_constraints"]]


def test_extracts_declared_relationships(artifacts):
    graph = read_json(artifacts, "relationships")
    nodes = {node["id"] for node in graph["nodes"]}
    assert len(nodes) == 7
    assert len(graph["edges"]) == 8
    assert len({edge["id"] for edge in graph["edges"]}) == 8
    assert all(edge["data"]["kind"] == "declared" for edge in graph["edges"])
    assert all({edge["source"], edge["target"]} <= nodes for edge in graph["edges"])
    assert any(edge["source"] == "support_tickets" and edge["target"] == "employees"
               and edge["data"]["source_columns"] == ["employee_id"] for edge in graph["edges"])


def test_profiles_counts_sampling_and_numeric_statistics():
    engine = create_engine("sqlite://")
    with engine.begin() as connection:
        connection.exec_driver_sql("CREATE TABLE sample (id INTEGER PRIMARY KEY, value INTEGER)")
        connection.exec_driver_sql("INSERT INTO sample VALUES (1, 10), (2, 20), (3, 20), (4, NULL), (5, 'mixed')")
        table = Table("sample", MetaData(), autoload_with=connection)
        result = profile_column(connection, table, table.c.value, sample_size=3)
        mixed = profile_column(connection, table, table.c.value)
    assert result["total_count"] == 5
    assert result["non_null_count"] == 4
    assert result["null_percentage"] == 20
    assert result["distinct_count"] == 3
    assert result["duplicate_count"] == 1
    assert result["uniqueness_ratio"] == .75
    assert result["sample_count"] == 3
    assert result["numeric_statistics"]["mean"] == pytest.approx(15)
    assert result["min_length"] == 2
    assert result["max_length"] == 5
    assert result["average_length"] == 3
    assert result["sampling_method"] == "stratified_non_null_rank"
    assert mixed["text_indicators"]["english_values"] == 1
    assert mixed["numeric_statistics"]["count"] == 3


@pytest.mark.parametrize("insert_null", [False, True])
def test_empty_and_null_only_columns(insert_null):
    engine = create_engine("sqlite://")
    with engine.begin() as connection:
        connection.exec_driver_sql("CREATE TABLE sample (value TEXT)")
        if insert_null:
            connection.exec_driver_sql("INSERT INTO sample VALUES (NULL)")
        table = Table("sample", MetaData(), autoload_with=connection)
        result = profile_column(connection, table, table.c.value)
    assert result["total_count"] == int(insert_null)
    assert result["null_percentage"] == 100 * int(insert_null)
    assert result["non_null_count"] == result["sample_count"] == 0
    assert result["min_length"] is result["numeric_statistics"] is None
    assert result["patterns"] == []


def test_ambiguous_names_have_structural_evidence(artifacts):
    profiles = read_json(artifacts, "profiles")
    customers = profiles["customers"]
    assert customers["f01"]["null_percentage"] == 50
    assert customers["f01"]["patterns"][0]["pattern"] == "9999999999"
    assert customers["x2"]["patterns"][0]["pattern"] == "9999999999"
    assert customers["attr_03"]["sample_count"] == 500
    assert customers["full_name"]["duplicate_count"] > 0
    assert customers["full_name"]["text_indicators"]["arabic_values"] > 0
    assert customers["joined_on"]["date_formats"] == {"%Y-%m-%d": 500}
    assert profiles["payments"]["region_code"]["patterns"][0]["pattern"] == "XX" + "9" * 22


def test_exports_omit_raw_personal_data(artifacts):
    with sqlite3.connect(artifacts / "synthetic.sqlite") as connection:
        queries = [
            "SELECT full_name, f01, attr_03, email FROM customers WHERE id IN (2, 4)",
            "SELECT x2 FROM customers WHERE id = 1",
            "SELECT region_code FROM payments WHERE id = 3",
            "SELECT full_name, work_email FROM employees WHERE id = 1",
        ]
        raw_values = {value for query in queries for row in connection.execute(query) for value in row}
    for name in ("schema", "relationships", "profiles", "ground_truth"):
        export = (artifacts / f"{name}.json").read_text(encoding="utf-8")
        assert all(value not in export for value in raw_values)
