"""Prepare, seal, and evaluate independent synthetic relational schemas."""
import argparse
import json
import sqlite3
from pathlib import Path
from random import Random

from evaluation.contextual_eval import run
from evaluation.public_catalog import protocol_hashes
from evaluation.contextual_holdout import value
from evaluation.public_catalog import LINKAGE, PERSONAL
from evaluation.reliability_infer import digest, fingerprint
from evaluation.score import read
from scripts.scan_data_asset import write_report
from evaluation import contextual_eval

# Field entries encode name, exact meaning, and privacy. References use table.field.
SOURCES = {
"property_restoration": """
policy_clients accounts client:record_id:L heading:person_name:D email_out:email_address:D callback:phone_number:D commenced:date:L
builders suppliers code:record_id:N trading_name:organization_name:N switchboard:phone_number:N help_email:email_address:N region:location:N
work_orders restoration work:record_id:N account_ref:reference_id:L:policy_clients.client provider_ref:reference_id:N:builders.code requested_on:date:L phase:status:L estimate:price:L
site_visits restoration visit:record_id:N work_ref:reference_id:L:work_orders.work visited_on:date:L status:status:L observations:free_text:L
building_stock stock k:record_id:N item_name:product_name:N serial:business_identifier:N purchasing_price:price:N
""",
"municipal_lending": """
cardholders membership ref:record_id:L printable:person_name:D feedback_to:email_address:D reachable_at:phone_number:D joined:date:L
borrowers membership borrower:record_id:L title_line:person_name:D delivery_inbox:email_address:D mobile:phone_number:D address_city:city:L
reading_material holdings id:record_id:N title:product_name:N barcode:business_identifier:N edition:category:N
checkouts borrowing checkout:record_id:N recipient:reference_id:L:borrowers.borrower holding:reference_id:N:reading_material.id accepted:date:L standing:status:L
extensions borrowing extension:record_id:N loan:reference_id:L:checkouts.checkout renewed_on:date:L extension_note:free_text:L result:status:L
library_sites buildings location_key:record_id:N organization_name:organization_name:N office_email:email_address:N utility_phone:phone_number:N municipality:city:N
""",
"equipment_calibration": """
operators staffing operator:record_id:L name_on_card:person_name:D desk_dial:phone_number:D desk_inbox:email_address:D certified_on:date:L
labs test_facilities lab:record_id:N legal_operator:organization_name:N switchboard:phone_number:N mailstop:email_address:N area:city:N
instruments inventory instrument:record_id:N tracking:business_identifier:N model_title:product_name:N lab_location:reference_id:N:labs.lab notes:free_text:N
submissions calibration case_id:record_id:N item_ref:reference_id:N:instruments.instrument handler:reference_id:L:operators.operator delivered:date:N progress:status:N
certificates calibration certificate:record_id:N parent:reference_id:N:submissions.case_id produced_on:date:N commentary:free_text:N disposition:status:N
training staffing key_id:record_id:N employee:reference_id:L:operators.operator enrolled_on:date:L course_status:status:L
""",
"volunteer_transport": """
participants riders id_num:record_id:L caption:person_name:D inbox:email_address:D voice:phone_number:D home_town:city:L
drivers staffing badge:record_id:L name_line:person_name:D contact_number:phone_number:D reply:email_address:D active_since:date:L
depots facilities node:record_id:N regional_operator:organization_name:N contact:email_address:N ext:phone_number:N city:city:N
trip_requests trips job:record_id:N passenger:reference_id:L:participants.id_num assigned_to:reference_id:L:drivers.badge depot:reference_id:N:depots.node requested:date:L progress:status:L notes:free_text:L
trip_legs trips leg:record_id:N booking:reference_id:L:trip_requests.job routed_on:date:L status:status:L fare:price:L
fleet fleet asset:record_id:N plate_code:business_identifier:N description:free_text:N station:reference_id:N:depots.node
"""
}
ROOT = Path("data/groq_joint_holdout")


def prepare():
    ROOT.mkdir(parents=True, exist_ok=False)
    files = {}
    for i, (sector, specification) in enumerate(SOURCES.items()):
        rng = Random(46663 + i * 571)
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
            "dictionary": None}


def paired_run(sources):
    """Share live field inference and evaluate both native domain passes."""
    original = contextual_eval.FreeCatalogProvider
    calls = {}

    class SharedGroq(original):
        replay = False
        experimental_purpose_domains = True

        def request(self, payload, count, system, schema):
            key = json.dumps([payload, count, system, schema], sort_keys=True)
            if self.replay and key not in calls:
                assert "groups" in schema["properties"], "Baseline and candidate submitted different field requests."
                return super().request(payload, count, system, schema)
            if self.replay:
                ok, result = calls[key]
                if not ok:
                    raise ValueError("This request failed in the live run.")
                return result
            try:
                result = super().request(payload, count, system, schema)
            except Exception:
                calls[key] = (False, None)
                raise
            calls[key] = (True, result)
            return result

    run("offline", sources, ROOT / "offline", None, None)
    contextual_eval.FreeCatalogProvider = SharedGroq
    try:
        run("groq", sources, ROOT / "groq", None, None)
        SharedGroq.replay = True
        SharedGroq.experimental_purpose_domains = False
        run("groq", sources, ROOT / "prior_decision_logic", None, None)
    finally:
        contextual_eval.FreeCatalogProvider = original


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("prepare", "freeze", "run"))
    action = parser.parse_args().action
    seal = ROOT / "seal.json"
    if action == "prepare":
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

