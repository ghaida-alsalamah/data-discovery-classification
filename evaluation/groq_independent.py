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
    "seed_exchange": """
growers grower_accounts grower_key:record_id:L contact_full:person_name:D mailbox:email_address:D
lots stock lot_key:record_id:N cultivar:product_name:N lot_notes:free_text:N warehouse_city:city:N
sampling inspection check_key:record_id:N batch_ref:reference_id:N:lots.lot_key collected_on:date:N
sampling_values inspection row_key:record_id:N test_ref:reference_id:N:sampling.check_key reading_status:status:N
allocations distribution order_key:record_id:N grower_ref:reference_id:L:growers.grower_key batch_ref:reference_id:N:lots.lot_key ordered_on:date:L unit_price:price:L
dispatch distribution dispatch_key:record_id:N shipment_ref:reference_id:L:allocations.order_key route_name:route_name:N delivery_notes:free_text:L
""",
    "performing_arts": """
patrons patrons patron_key:record_id:L patron_name:person_name:D mobile:phone_number:D email:email_address:D
venues venues venue_key:record_id:N operator_name:organization_name:N host_city:city:N postcode:postal_code:N
shows programming show_key:record_id:N venue_ref:reference_id:N:venues.venue_key curtain_date:date:N curtain_time:time_of_day:N performance_notes:free_text:N
admissions ticketing entry_key:record_id:N guest_ref:reference_id:L:patrons.patron_key show_ref:reference_id:N:shows.show_key entry_status:status:L payment_method:payment_method:L ticket_price:price:L
supporters patrons supporter_key:record_id:L patron_ref:reference_id:L:patrons.patron_key enrolled_on:date:L membership_status:status:L
""",
    "equipment_repair": """
technicians workforce technician_key:record_id:L full_name:person_name:D direct_phone:phone_number:D work_email:email_address:D
depots facilities depot_key:record_id:N owner_org:organization_name:N depot_city:city:N location:location:N
equipment assets asset_key:record_id:N tracking_number:business_identifier:N product_name:product_name:N depot_ref:reference_id:N:depots.depot_key
work_requests maintenance job_key:record_id:N machine_ref:reference_id:N:equipment.asset_key logged_on:date:N request_notes:free_text:N work_status:status:N
assignments maintenance assignment_key:record_id:N mechanic_ref:reference_id:L:technicians.technician_key job_ref:reference_id:N:work_requests.job_key assigned_on:date:L
inspection_results quality result_key:record_id:N job_ref:reference_id:N:work_requests.job_key test_status:status:N test_notes:free_text:N mixed_flag:unknown:U
""",
}
ROOT = Path("data/groq_independent")


def prepare():
    ROOT.mkdir(parents=True, exist_ok=False)
    files = {}
    for i, (sector, specification) in enumerate(SOURCES.items()):
        rng = Random(37561 + i * 291)
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
        for mode in ("baseline", "offline", "groq"):
            run(mode, [(ROOT, name) for name in SOURCES], ROOT / mode, None, None)
        verify()

