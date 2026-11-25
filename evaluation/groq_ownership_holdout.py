"""Prepare, seal, and evaluate independent synthetic relational schemas."""
import argparse
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

# Field entries encode name, exact meaning, and privacy. References use table.field.
SOURCES = {
"renewable_grid": """
subscribers subscribers eid:record_id:L label:person_name:D notices:email_address:D connect:phone_number:D begun:date:L
dispatch_centers grid_ops node:record_id:N operating_body:organization_name:N ext:phone_number:N inbox:email_address:N municipality:city:N
devices asset_catalog thing:record_id:N serial:business_identifier:N product:product_name:N control_site:reference_id:N:dispatch_centers.node notes:free_text:N
subscriptions subscriptions sid:record_id:N sub:reference_id:L:subscribers.eid meter:reference_id:N:devices.thing effective:date:L tariff:price:L condition:status:L
adjustments subscriptions adj:record_id:N ledger_ref:reference_id:L:subscriptions.sid period:date:L correction:financial_amount:L grounds:free_text:L
outages outage_tracking oid:record_id:N device:reference_id:N:devices.thing coordinator:reference_id:N:dispatch_centers.node beginning:date:N status:status:N
""",
"petroleum_testing": """
operators workforce emp:record_id:L formal_name:person_name:D w_addr:email_address:D desk_dial:phone_number:D induction:date:L
testing_partners laboratory_network partner:record_id:N trading_name:organization_name:N booking_tel:phone_number:N service_inbox:email_address:N location:city:N
sample_batches specimens ref:record_id:N batch_serial:business_identifier:N collected:date:N label:category:N assay_notes:free_text:N
assays chemistry qa:record_id:N specimen:reference_id:N:sample_batches.ref lab:reference_id:N:testing_partners.partner technician:reference_id:L:operators.emp started:date:N material:category:N verdict:status:N
retention chemistry rid:record_id:N assay:reference_id:N:assays.qa archived:date:N custody_note:free_text:N
operator_training workforce cert:record_id:N employee:reference_id:L:operators.emp completion:date:L result:status:L
""",
"community_press": """
readers audience r:record_id:L caption:person_name:D reply_point:email_address:D tone:phone_number:D join_date:date:L
advertisers commerce a:record_id:N advertiser:organization_name:N callbacks:phone_number:N desk:email_address:N agency_code:business_identifier:N
issues publication issue:record_id:N edition_date:date:N phase:status:N blurb:free_text:N
subscriptions memberships s:record_id:N receiver:reference_id:L:readers.r subscribed:date:L plan:category:L annual_charge:price:L
subscription_renewals memberships row_id:record_id:N agreement:reference_id:L:subscriptions.s renewal_day:date:L method:payment_method:L result:status:L
placements commerce p:record_id:N buyer:reference_id:N:advertisers.a booked_in:reference_id:N:issues.issue slot_cost:price:N received_date:date:N
""",
"alpine_rescue": """
registrants registration pid:record_id:L display:person_name:D alert_destination:email_address:D return_number:phone_number:D home_base:city:L
response_staff response_team badge:record_id:L responder:person_name:D personal_mail:email_address:D cellphone:phone_number:D
stations infrastructure depot:record_id:N maintainer:organization_name:N hotline:phone_number:N contact:email_address:N hub:city:N
incidents interventions ir:record_id:N caller:reference_id:L:registrants.pid response_lead:reference_id:L:response_staff.badge dispatch_site:reference_id:N:stations.depot opened:date:L priority:status:L circumstances:free_text:L
incident_updates interventions event_id:record_id:N case_ref:reference_id:L:incidents.ir captured:date:L state:status:L mixed_note:unknown:U
"""
}
ROOT = Path("data/groq_ownership_holdout")


def prepare():
    ROOT.mkdir(parents=True, exist_ok=False)
    files = {}
    for i, (sector, specification) in enumerate(SOURCES.items()):
        rng = Random(75991 + i * 563)
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
        for mode in ("offline", "groq"):
            run(mode, [(ROOT, name) for name in SOURCES], ROOT / mode, None, None)
        verify()

