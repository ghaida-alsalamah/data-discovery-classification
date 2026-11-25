"""Prepare, seal, and evaluate independent synthetic relational schemas."""
import argparse
import json
import sqlite3
from pathlib import Path
from collections import Counter
from random import Random

from evaluation.contextual_eval import run
from backend.app.classification import contextual_catalog
from evaluation.database_first_domains import infer, apply_partition
from evaluation.groq_architecture_holdout import classification_confidence
from backend.app.discovery.schema import discover
from backend.app.intelligence.quality import verify_relationships
from sqlalchemy import create_engine
import httpx
from evaluation.default_holdout import joint_by_membership
from evaluation.score import rows_for
from evaluation.public_catalog import protocol_hashes
from evaluation.contextual_holdout import value
from evaluation.public_catalog import LINKAGE, PERSONAL
from evaluation.reliability_infer import digest, fingerprint
from evaluation.score import read
from scripts.scan_data_asset import write_report
from evaluation import contextual_eval

# Field entries encode name, exact meaning, and privacy. References use table.field.
SOURCES = {
"translation_services": """
clients client_accounts ident:record_id:L caption:person_name:D response_mail:email_address:D voice_contact:phone_number:D registered:date:L
freelancers workforce vendor_key:record_id:L display_name:person_name:D invoice_mail:email_address:D reply_number:phone_number:D joined:date:L
language_tools assets tool_key:record_id:N product_label:product_name:N stock_identifier:business_identifier:N category:category:N
work_requests fulfilment request:record_id:N requested_by:reference_id:L:clients.ident assignee:reference_id:L:freelancers.vendor_key requested:date:L quote:price:L state:status:L
deliveries fulfilment delivery:record_id:N request_link:reference_id:L:work_requests.request released:date:L note:free_text:L milestone:status:L
audits oversight review:record_id:N reference_key:reference_id:N:work_requests.request decided:date:N evidence_note:free_text:N
""",
"building_access": """
occupants occupants id_no:record_id:L display:person_name:D delivery_point:email_address:D return_line:phone_number:D start_day:date:L
operators service_providers code:record_id:N operator_group:organization_name:N switchboard:phone_number:N address:email_address:N town:city:N
premises inventory property_id:record_id:N building_name:product_name:N registry:business_identifier:N managing_operator:reference_id:N:operators.code
assignments access_activity permit:record_id:N person_ref:reference_id:L:occupants.id_no location_ref:reference_id:N:premises.property_id granted:date:L situation:status:L
renewals access_activity renewal:record_id:N authorization:reference_id:L:assignments.permit date_effective:date:L change_summary:free_text:L
inspections compliance inspection_id:record_id:N site:reference_id:N:premises.property_id inspected:date:N status:status:N notes:free_text:N
""",
"medical_equipment_dispatch": """
providers organizations id:record_id:N operating_title:organization_name:N contact_mail:email_address:N main_number:phone_number:N municipality:city:N
receivers client_accounts ref:record_id:L label:person_name:D contact_point:email_address:D alternate:phone_number:D enrolled:date:L
dispatch_inventory stock equipment:record_id:N title:product_name:N tracking:business_identifier:N ownership:reference_id:N:providers.id cargo_notes:free_text:N
requests fulfilment case_id:record_id:N person_ref:reference_id:L:receivers.ref requested_item:reference_id:N:dispatch_inventory.equipment logged:date:L disposition:status:L amount:price:L
handoffs fulfilment handoff:record_id:N parent_case:reference_id:L:requests.case_id issued:date:L notes:free_text:L
stock_checks inventory_control check_no:record_id:N item:reference_id:N:dispatch_inventory.equipment observed:date:N condition:status:N
"""
}
ROOT = Path("data/groq_hierarchy_holdout")


def prepare():
    ROOT.mkdir(parents=True, exist_ok=False)
    files = {}
    for i, (sector, specification) in enumerate(SOURCES.items()):
        rng = Random(71831 + i * 613)
        labels = {}
        path = ROOT / (sector + ".sqlite")
        with sqlite3.connect(path) as db:
            for line in specification.strip().splitlines():
                table, domain, *fields = line.split()
                declarations, definitions = [], []
                labels[table] = {}
                for entry in fields:
                    name, kind, privacy, *relation = entry.split(":")
                    labels[table][name] = {"semantic_type": kind, "domain": domain,
                                           "personal_data": PERSONAL[privacy], "personal_linkage": LINKAGE[privacy]}
                    sql_type = {"record_id": "INTEGER PRIMARY KEY", "reference_id": "INTEGER",
                                "price": "NUMERIC", "date": "DATE", "time_of_day": "TIME"}.get(kind, "TEXT")
                    if relation:
                        target, target_field = relation[0].split(".")
                        sql_type += f" REFERENCES {target}({target_field})"
                    declarations.append(f"{name} {sql_type}")
                    definitions.append((name, kind))
                db.execute(f"CREATE TABLE {table} ({', '.join(declarations)})")
                rows = []
                for idx in range(42):
                    rows.append([7000 + (idx if kind == "record_id" else (idx * 5 + 3) % 42)
                                 if kind in {"record_id", "reference_id"}
                                 else value(kind, name, idx, rng) for name, kind in definitions])
                marks = ",".join(["?"] * len(definitions))
                db.executemany(f"INSERT INTO {table} VALUES ({marks})", rows)
        label_path = ROOT / (sector + "_labels.json")
        write_report(label_path, labels)
        for item in (path, label_path):
            files[item.name] = digest(item)
    write_report(ROOT / "inputs.json", files)
    print("Fixture field count:", sum(len(line.split()) - 2 for spec in SOURCES.values()
                                      for line in spec.strip().splitlines()), flush=True)


def config():
    return {"source": digest(Path(__file__)), "backend": fingerprint(Path(".")),
            "runner": digest(Path("evaluation/contextual_eval.py")), "protocol": protocol_hashes(),
            "value_generator": digest(Path("evaluation/contextual_holdout.py")),
            "scan": digest(Path("scripts/scan_data_asset.py")), "model": "openai/gpt-oss-120b",
            "dictionary": None, "domain_experiment": digest(Path("evaluation/database_first_domains.py"))}



def confidence_report(sources, modes):
    for mode in modes:
        rows, scores = [], {}
        for root, name in sources:
            truth = read(root / (name + "_labels.json"))
            predictions = read(ROOT / mode / (name + ".json"))["classifications"]
            rows.extend(rows_for(name, truth, predictions))
            for row in predictions:
                scores[name, row["table_name"], row["column_name"]] = classification_confidence(row, include_joint=False)
        def key(row):
            return row["sector"], row["table"], row["column"]
        errors = {key(row): row["wrong_dimensions"] for row in
                  joint_by_membership([dict(row, review_required=False) for row in rows])["errors"]}
        report = {}
        for score, outcome in (("semantic", "semantic"), ("domain", "group"), ("privacy", "privacy"),
                               ("semantic", "joint")):
            for subset, selected in (("all", rows), ("automatic", [r for r in rows if not r["review_required"]])):
                samples = [(scores[key(r)][score], (key(r) not in errors if outcome == "joint"
                            else outcome not in errors.get(key(r), ()))) for r in selected]
                pos = [v for v, ok in samples if ok]
                neg = [v for v, ok in samples if not ok]
                bins = {}
                for low, high in ((0, .4), (.4, .65), (.65, .8), (.8, .9), (.9, 1.01)):
                    group = [ok for v, ok in samples if low <= v < high]
                    if group:
                        bins[f"{low}-{high}"] = [sum(group), len(group)]
                report[f"{subset}.{score}.{outcome}"] = {
                    "auc": sum((a > b)+.5*(a == b) for a in pos for b in neg)/(len(pos)*len(neg))
                    if pos and neg else None, "correct_by_score_bin": bins,
                }
        write_report(ROOT / mode / "component_confidence.json", report)



def schema_evidence(path):
    engine = create_engine("sqlite:///" + path.resolve().as_uri() + "?mode=ro&uri=true")
    try:
        with engine.connect() as connection:
            schema, relations = discover(connection)
            checks = verify_relationships(connection, schema, relations)
    finally:
        engine.dispose()
    return {t["name"]: t for t in schema["tables"]}, relations, checks


def development():
    output = Path("data/groq_hierarchy_development")
    saved = Path("data/groq_ownership_development/groq")
    with httpx.Client(timeout=35, trust_env=False, follow_redirects=False) as client:
        provider = contextual_eval.FreeCatalogProvider(client, "groq")
        for root, name in contextual_eval.DEV:
            rows = read(saved / (name + ".json"))["classifications"]
            truth = read(root / (name + "_labels.json"))
            from evaluation.public_catalog import grouping
            before = grouping(rows_for(name, truth, rows))
            grouped = {}
            for row in rows:
                grouped.setdefault(row["table_name"], {})[row["column_name"]] = row
            partition = infer(provider, *schema_evidence(root / (name + ".sqlite")))
            apply_partition(grouped, partition)
            after = grouping(rows_for(name, truth, rows))
            write_report(output / (name + ".json"), {"baseline": before, "hierarchy_leaf": after,
                         "partition_returned": partition is not None})
        write_report(output / "runtime.json", provider.counters)


def paired_run(sources):
    original = contextual_eval.FreeCatalogProvider
    scanner = contextual_eval.AssetScan
    original_groups = contextual_catalog.contextual_domains
    calls = {}

    class SharedGroq(original):
        replay = False

        def request(self, payload, count, system, schema):
            key = json.dumps([payload, count, system, schema], sort_keys=True)
            if self.replay and "parent" not in schema["properties"]:
                assert key in calls, "Field or fallback-domain requests differ."
                result, error = calls[key]
                if error:
                    raise error
                return result
            try:
                result = super().request(payload, count, system, schema)
            except Exception as error:
                calls[key] = (None, error)
                raise
            calls[key] = (result, None)
            return result

    class DatabaseFirst(scanner):
        def scan(self, path, **kwargs):
            self.provider.database_partition = infer(self.provider, *schema_evidence(path))
            return super().scan(path, **kwargs)

    def hierarchy_groups(provider, grouped, tables, relationships, checks):
        if provider.database_partition is None:
            original_groups(provider, grouped, tables, relationships, checks)
        else:
            apply_partition(grouped, provider.database_partition)

    contextual_eval.FreeCatalogProvider = SharedGroq
    try:
        run("groq", sources, ROOT / "baseline", None, None)
        SharedGroq.replay = True
        contextual_eval.AssetScan = DatabaseFirst
        contextual_catalog.contextual_domains = hierarchy_groups
        run("groq", sources, ROOT / "hierarchy", None, None)
    finally:
        contextual_eval.FreeCatalogProvider = original
        contextual_eval.AssetScan = scanner
        contextual_catalog.contextual_domains = original_groups
    confidence_report(sources, ("baseline", "hierarchy"))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("prepare", "freeze", "run", "development"))
    action = parser.parse_args().action
    seal = ROOT / "seal.json"
    if action == "development":
        development()
    elif action == "prepare":
        prepare()
    elif action == "freeze":
        if seal.exists():
            raise FileExistsError(seal)
        write_report(seal, {"config": config(), "fixtures": read(ROOT / "inputs.json")})
    else:
        frozen = read(seal)
        def verify():
            if config() != frozen["config"] or any(
                    digest(ROOT / name) != sha for name, sha in frozen["fixtures"].items()):
                raise ValueError("Frozen evaluation configuration or fixtures changed.")

        verify()
        paired_run([(ROOT, name) for name in SOURCES])
        verify()

