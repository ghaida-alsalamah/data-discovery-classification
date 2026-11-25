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
"water_reclamation": """
subscribers customer_accounts rec:record_id:L holder:person_name:D mail_route:email_address:D callback:phone_number:D activated:date:L
operators staffing staff_no:record_id:L operator_name:person_name:D work_mail:email_address:D work_mobile:phone_number:D shift_time:time_of_day:L
plants facilities plant_no:record_id:N operator_company:organization_name:N township:city:N dispatch_line:phone_number:N inquiries:email_address:N
discharge_permits permits pnum:record_id:N plant_ref:reference_id:N:plants.plant_no billed_to:reference_id:L:subscribers.rec permit_fee:price:L expiration:date:L state:status:L permit_no:business_identifier:N
compliance_visits permits visit_no:record_id:N p_ref:reference_id:L:discharge_permits.pnum assigned_staff:reference_id:L:operators.staff_no visited_at:date:L inspection_result:status:L summary:free_text:L
""",
"museum_conservation": """
lenders lenders refnum:record_id:L display_caption:person_name:D reply_to:email_address:D destination_dial:phone_number:D residence_city:city:L
studios providers seq:record_id:N firm_title:organization_name:N help_tel:phone_number:N desk_mail:email_address:N local_city:city:N
artifacts collection object_key:record_id:N maker_catalog_no:business_identifier:N object_title:product_name:N inscription:free_text:N state_of_repair:status:N
temporary_loans lending loan_key:record_id:N lender_ref:reference_id:L:lenders.refnum object_ref:reference_id:N:artifacts.object_key received_on:date:L agreement_state:status:L
conservation_tasks conservation task_key:record_id:N accession_ref:reference_id:N:artifacts.object_key studio_ref:reference_id:N:studios.seq quoted_price:price:N scheduled:date:N work_notes:free_text:N
loan_extensions lending ext_key:record_id:N grant_ref:reference_id:L:temporary_loans.loan_key expires:date:L decision:status:L
""",
"food_certification": """
operators applicant_accounts user_code:record_id:L display_label:person_name:D correspondence:email_address:D call_to:phone_number:D home_town:city:L
laboratories laboratories lab_code:record_id:N brand:organization_name:N test_centre_city:city:N reception:phone_number:N group_mail:email_address:N
assessors workforce empno:record_id:L legal_name:person_name:D assessor_email:email_address:D cellphone:phone_number:D
applications accreditation application_key:record_id:N applicant_no:reference_id:L:operators.user_code licence_number:business_identifier:N assessment_fee:price:L filed:date:L progress:status:L
reviews accreditation report_key:record_id:N application_ref:reference_id:L:applications.application_key evaluator:reference_id:L:assessors.empno lab_ref:reference_id:N:laboratories.lab_code tested_date:date:L report:free_text:L
""",
"tool_rental": """
members membership mkey:record_id:L person_label:person_name:D transmission:email_address:D voice:phone_number:D started:date:L
branches facilities bkey:record_id:N branch_operator:organization_name:N branch_mail:email_address:N central_phone:phone_number:N region:location:N
machinery inventory serial_key:record_id:N barcode:business_identifier:N catalog_label:product_name:N stored_at:reference_id:N:branches.bkey register_text:free_text:N
hire_agreements hiring contract_key:record_id:N hired_by:reference_id:L:members.mkey machine:reference_id:N:machinery.serial_key agreed:date:L hire_charge:price:L state:status:L
hire_adjustments hiring change_key:record_id:N contract:reference_id:L:hire_agreements.contract_key adjustment_date:date:L payment_method:payment_method:L misc_code:unknown:U
"""
}
ROOT = Path("data/groq_scope_holdout")


def prepare():
    ROOT.mkdir(parents=True, exist_ok=False)
    files = {}
    for i, (sector, specification) in enumerate(SOURCES.items()):
        rng = Random(31289 + i * 641)
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

