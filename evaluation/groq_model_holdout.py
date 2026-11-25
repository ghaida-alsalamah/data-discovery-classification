"""Prepare, seal, and evaluate independent synthetic relational schemas."""
import argparse
import sqlite3
from pathlib import Path
from random import Random

from evaluation.groq_architecture_holdout import classification_confidence
from evaluation.default_holdout import joint_by_membership
from evaluation.score import rows_for
from evaluation.public_catalog import protocol_hashes
from evaluation.contextual_holdout import value
from evaluation.public_catalog import LINKAGE, PERSONAL
from evaluation.reliability_infer import digest, fingerprint
from evaluation.score import read
from scripts.scan_data_asset import write_report
from evaluation.groq_model_comparison import MODELS, run_model

# Field entries encode name, exact meaning, and privacy. References use table.field.
SOURCES = {
"home_telecommunications": """
subscribers subscriber_account skey:record_id:L label:person_name:D reach:email_address:D ring:phone_number:D opened:date:L
helpdesk_agents workforce employee_no:record_id:L display_name:person_name:D work_email:email_address:D callback:phone_number:D start_day:date:L
facilities network_registry node:record_id:N operator_title:organization_name:N switchboard:phone_number:N office_address:email_address:N municipality:city:N
subscriber_tickets support_lifecycle ticket:record_id:N holder:reference_id:L:subscribers.skey assigned_to:reference_id:L:helpdesk_agents.employee_no filed_on:date:L state:status:L narrative:free_text:L
ticket_updates support_lifecycle update_id:record_id:N ticket_number:reference_id:L:subscriber_tickets.ticket opened:date:L decision:status:L
network_inspections network_oversight inspection:record_id:N facility_ref:reference_id:N:facilities.node inspector:reference_id:L:helpdesk_agents.employee_no inspected:date:N finding:status:N notes:free_text:N
""",
"publishing_rights": """
contributors creator_registry code:record_id:L printable:person_name:D delivery_point:email_address:D feedback_line:phone_number:D entered:date:L
rights_partners partner_registry id:record_id:N trade_title:organization_name:N help_line:phone_number:N contact_mail:email_address:N city:city:N
catalog_inventory asset_catalog item_id:record_id:N title:product_name:N tracking:business_identifier:N note:free_text:N
licences licensing_lifecycle lk:record_id:N author_ref:reference_id:L:contributors.code material:reference_id:N:catalog_inventory.item_id licensee:reference_id:N:rights_partners.id effective:date:L state:status:L fee:price:L
royalty_statements licensing_lifecycle statement:record_id:N licence_reference:reference_id:L:licences.lk posted:date:L liability:financial_amount:L remarks:free_text:L
rights_checks independent_oversight check_no:record_id:N reviewed_licence:reference_id:N:licences.lk logged_on:date:N disposition:status:N
""",
"industrial_waste_collection": """
collectors workforce_registry badge:record_id:L display_txt:person_name:D inbox:email_address:D telephone:phone_number:D activated:date:L
contractors supplier_registry supplier_no:record_id:N firm_caption:organization_name:N support_mail:email_address:N switchboard:phone_number:N district:city:N
containers bins_inventory asset:record_id:N serial_number:business_identifier:N friendly_name:product_name:N supplier_ref:reference_id:N:contractors.supplier_no comments:free_text:N
pickups collection_lifecycle pickup:record_id:N bin:reference_id:N:containers.asset allocated_to:reference_id:L:collectors.badge scheduled:date:N state:status:N operational_notes:free_text:N
pickup_measurements collection_lifecycle sample_no:record_id:N pickup_ref:reference_id:N:pickups.pickup checked_at:date:N assessment:status:N
operator_training workforce_activity session_id:record_id:N attendee:reference_id:L:collectors.badge attended:date:L outcome:status:L
"""
}
ROOT = Path("data/groq_model_holdout")


def prepare():
    ROOT.mkdir(parents=True, exist_ok=False)
    files = {}
    for i, (sector, specification) in enumerate(SOURCES.items()):
        rng = Random(57991 + i * 773)
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
            "dictionary": None, "comparison": digest(Path("evaluation/groq_model_comparison.py")),
            "guidelines": digest(Path("evaluation/DOMAIN_ANNOTATION_GUIDELINES.md"))}



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





def participant_probe(mode):
    # Predeclared, independent of inference. These fields describe either a
    # person-owned activity or a separate operation with a reachable person.
    checks = {
        "home_telecommunications": {
            "subscriber_tickets": [("filed_on", True), ("state", True), ("narrative", True)],
            "ticket_updates": [("opened", True), ("decision", True)],
            "network_inspections": [("inspected", False), ("finding", False), ("notes", False)],
        },
        "publishing_rights": {
            "licences": [("effective", True), ("state", True), ("fee", True)],
            "royalty_statements": [("posted", True), ("liability", True), ("remarks", True)],
            "rights_checks": [("logged_on", False), ("disposition", False)],
        },
        "industrial_waste_collection": {
            "pickups": [("scheduled", False), ("state", False), ("operational_notes", False)],
            "pickup_measurements": [("checked_at", False), ("assessment", False)],
            "operator_training": [("attended", True), ("outcome", True)],
        },
    }
    result = []
    for name, tables in checks.items():
        rows = read(ROOT / mode / (name + ".json"))["classifications"]
        indexed = {(r["table_name"], r["column_name"]): r for r in rows}
        for table, fields in tables.items():
            for field, person in fields:
                prediction = indexed[table, field]
                result.append({"database": name, "table": table, "column": field,
                               "person_subject": person, "semantic_type": prediction["semantic_type"],
                               "privacy_prediction": prediction["personal_linkage"],
                               "correct": prediction["personal_linkage"] == ("linked" if person else "none")})
    write_report(ROOT / mode / "subject_participant_probe.json", result)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("prepare", "freeze", "run"))
    parser.add_argument("--candidate", choices=("oss20", "qwen27"))
    parser.add_argument("--model", choices=MODELS)
    args = parser.parse_args()
    seal = ROOT / "seal.json"
    if args.action == "prepare":
        prepare()
    elif args.action == "freeze":
        if not args.candidate or seal.exists():
            raise ValueError("Select one development finalist and a fresh seal.")
        write_report(seal, {"configuration": config(), "inputs": read(ROOT / "inputs.json"),
                            "candidate": args.candidate})
    else:
        frozen = read(seal)
        def check():
            if (frozen["configuration"] != config() or args.model not in {"oss120", frozen["candidate"]}
                    or any(digest(ROOT / name) != sha for name, sha in frozen["inputs"].items())):
                raise ValueError("Model or sealed holdout configuration changed.")
        sources = [(ROOT, name) for name in SOURCES]
        check()
        run_model(args.model, sources, ROOT / args.model)
        participant_probe(args.model)
        confidence_report(sources, (args.model,))
        check()
