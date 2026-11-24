"""Isolate Phase 3 using verified inputs. Never pass labels to the classifier."""
import argparse
import json
from pathlib import Path

from backend.app.connectors.sqlite import InformationAsset, SQLiteConnector
from backend.app.discovery.schema import discover
from backend.app.intelligence.service import analyze
from backend.app.profiling.columns import profile_database
from evaluation.fixtures import digest, write_json
from evaluation.score import read


def check(root):
    manifest = read(root / "fixture_manifest.json")
    label_path = root / "labels/ecommerce.json"
    if digest(label_path) != manifest["files"]["labels/ecommerce.json"]:
        raise ValueError("Sealed labels changed.")
    labels = read(label_path)
    # This control tests downstream behavior when correct classifications are available.
    # Only the Phase 3 API sees these rows. They are excluded from all benchmark scores.
    verified = [
        {"table_name": table, "column_name": col, "semantic_type": row["semantic_type"],
         "data_domain": row["domain"], "personal_data": row["personal_data"],
         "sensitivity": {"yes": "confidential", "no": "internal"}.get(row["personal_data"], "undetermined"),
         "review_required": False}
        for table, fields in labels.items() for col, row in fields.items()
    ]
    report = {"scope": "Phase 3 isolation with predeclared semantic inputs. No classification was run.", "variants": {}}
    for name in ("ecommerce", "ecommerce_stress", "ecommerce_unlinked"):
        path = root / "databases" / (name + ".sqlite")
        if digest(path) != manifest["files"]["databases/" + path.name]:
            raise ValueError("Sealed database changed.")
        with SQLiteConnector(path, InformationAsset(name, "Synthetic control", "Evaluation")).connect() as con:
            schema, links = discover(con)
            profiles = profile_database(con, schema, 500)
            domains, quality, opportunities = analyze(con, schema, links, profiles, verified, use_environment=False)
        report["variants"][name] = {
            "domains": domains, "quality": quality, "opportunities": opportunities,
        }
    statuses = {
        name: {row["template_id"]: row["readiness_status"]
               for row in result["opportunities"]["opportunities"]}
        for name, result in report["variants"].items()
    }
    report["checks"] = {
        "clean_service_demand_ready": statuses["ecommerce"]["service_demand"] == "Ready for technical analysis",
        "dirty_service_demand_requires_review": statuses["ecommerce_stress"]["service_demand"] ==
            "Requires preparation or review",
        "missing_link_blocks_service_demand": statuses["ecommerce_unlinked"]["service_demand"] == "Insufficient data",
        "clean_transaction_trends_ready": statuses["ecommerce"]["transaction_trends"] == "Ready for technical analysis",
        "dirty_transaction_trends_requires_review": statuses["ecommerce_stress"]["transaction_trends"] ==
            "Requires preparation or review",
    }
    write_json(root / "phase3_control.json", report)
    print(json.dumps(report["checks"], indent=2))


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("fixture_root", type=Path)
    check(parser.parse_args().fixture_root)
