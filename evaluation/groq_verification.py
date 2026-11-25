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
"municipal_permitting": """
requestors parties rid:record_id:L caption:person_name:D postbox:email_address:D ext:phone_number:D entered_on:date:L
inspectors workforce badge:record_id:L inspector_name:person_name:D contact:email_address:D mobile:phone_number:D shift_start:time_of_day:L
district_offices districts did:record_id:N centre:organization_name:N municipality:city:N hotline:phone_number:N office_email:email_address:N
applications permits filing:record_id:N applicant:reference_id:L:requestors.rid district:reference_id:N:district_offices.did tracking:business_identifier:N stage:status:L received:date:L fee:price:L details:free_text:L
site_checks permits cid:record_id:N filing_ref:reference_id:L:applications.filing agent:reference_id:L:inspectors.badge inspection_day:date:L outcome:status:L memo:free_text:L
""",
"marine_freight": """
crew_manifest personnel seq:record_id:L display:person_name:D radio_contact:phone_number:D inbox:email_address:D onboarded:date:L
consignees personnel account_key:record_id:L addressee:person_name:D sms_to:phone_number:D invoice_mail:email_address:D billing_city:city:L
terminals infrastructure k:record_id:N terminal_label:organization_name:N city:city:N ops_number:phone_number:N comms:email_address:N
voyages movement trip:record_id:N origin:reference_id:N:terminals.k destination:reference_id:N:terminals.k master:reference_id:L:crew_manifest.seq departure:date:N segment:route_name:N
consignments bookings docket:record_id:N voyage:reference_id:N:voyages.trip recipient:reference_id:L:consignees.account_key contact_code:business_identifier:N freight_rate:price:L progress:status:L goods_desc:free_text:L
""",
"research_grants": """
fellows researchers no:record_id:L heading:person_name:D reach:phone_number:D addr:email_address:D place_of_origin:city:L appointment:date:L
referees reviewers evaluator_key:record_id:L reviewer_name:person_name:D reviewer_mail:email_address:D phone:phone_number:D
sponsors organizations funder:record_id:N sponsor_title:organization_name:N office_line:phone_number:N sponsor_mail:email_address:N registry_no:business_identifier:N
submissions grants proposal_no:record_id:N lead:reference_id:L:fellows.no funder_no:reference_id:N:sponsors.funder synopsis:free_text:L submitted:date:L requested_fee:price:L decision:status:L
assessments grants assessment:record_id:N submission_ref:reference_id:L:submissions.proposal_no referee:reference_id:L:referees.evaluator_key stage:status:L narrative:free_text:L posted:date:L misc:unknown:U
""",
"building_energy": """
occupiers customers key_no:record_id:L legal_name:person_name:D dispatch_to:email_address:D dial:phone_number:D move_in:date:L
contractors suppliers vendor:record_id:N trading_as:organization_name:N name:business_identifier:N phone:phone_number:N support:email_address:N
metering_points equipment mp:record_id:N serial:business_identifier:N site_city:city:N product_name:product_name:N notes:free_text:N
service_accounts customers agreement:record_id:N user_ref:reference_id:L:occupiers.key_no meter_ref:reference_id:N:metering_points.mp created_at:date:L state:status:L billing:payment_method:L
field_visits maintenance visit_id:record_id:N unit:reference_id:N:metering_points.mp vendor_ref:reference_id:N:contractors.vendor slot:time_of_day:N completed_on:date:N narrative:free_text:N resolution:status:N
"""
}
ROOT = Path("data/groq_verification")


def prepare():
    ROOT.mkdir(parents=True, exist_ok=False)
    files = {}
    for i, (sector, specification) in enumerate(SOURCES.items()):
        rng = Random(96241 + i * 379)
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
    original = read(Path("data/groq_independent/seal.json"))["config"]
    if (fingerprint(Path(".")) != original["backend"]
            or digest(Path("scripts/scan_data_asset.py")) != original["scan"]
            or digest(Path("evaluation/contextual_eval.py")) != original["runner"]
            or protocol_hashes() != original["protocol"]
            or digest(Path("evaluation/contextual_holdout.py")) != original["value_generator"]):
        raise ValueError("Current scanner or evaluator differs from the previous sealed benchmark.")
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

