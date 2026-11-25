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
from backend.app.classification import contextual_catalog
from evaluation import contextual_eval

# Field entries encode name, exact meaning, and privacy. References use table.field.
SOURCES = {
"municipal_services": """
residents residency nr:record_id:L caption:person_name:D msg:email_address:D voice_channel:phone_number:D tenure_start:date:L
utility_offices sites site_code:record_id:N management:organization_name:N contact:email_address:N ext:phone_number:N township:city:N
permits licences permit:record_id:N participant:reference_id:L:residents.nr office:reference_id:N:utility_offices.site_code received:date:L disposition:status:L price:price:L
permit_actions licences action_no:record_id:N licence_ref:reference_id:L:permits.permit action_date:date:L action_state:status:L notes:free_text:L
station_assets facilities item:record_id:N serial_number:business_identifier:N label:product_name:N base:reference_id:N:utility_offices.site_code
""",
"agricultural_cooperative": """
members membership mid:record_id:L line1:person_name:D reply:email_address:D callback:phone_number:D enrolment:date:L
buyers membership buyer_key:record_id:L legal_caption:person_name:D address_text:email_address:D contact_number:phone_number:D municipality:city:L
storage_sites infrastructure node:record_id:N operating_body:organization_name:N helpdesk:email_address:N voice:phone_number:N region:location:N
transactions trade pk:record_id:N seller:reference_id:L:members.mid addressee:reference_id:L:buyers.buyer_key site:reference_id:N:storage_sites.node effective:date:L net:financial_amount:L phase:status:L
payments trade slip:record_id:N origin:reference_id:L:transactions.pk processed:date:L payment_method:payment_method:L narrative:free_text:L
""",
"freight_audit": """
inspectors staff ref:record_id:L printable:person_name:D work_inbox:email_address:D direct_line:phone_number:D start:date:L
customers accounts id:record_id:L legal_name:person_name:D mail:email_address:D direct_phone:phone_number:D home_city:city:L
carriers vendors carrier_no:record_id:N shipper:organization_name:N support_address:email_address:N number:phone_number:N registry:business_identifier:N
consignments dispatch serial:record_id:N account:reference_id:L:customers.id transport:reference_id:N:carriers.carrier_no submitted:date:L freight:price:L state:status:L
audits compliance case_no:record_id:N item_ref:reference_id:L:consignments.serial inspector_ref:reference_id:L:inspectors.ref entered:date:N result:status:N comments:free_text:N
""",
"membership_education": """
trainees learner_records tr:record_id:L subject_text:person_name:D exchange:email_address:D phone_route:phone_number:D arrived:date:L
providers vendors pr:record_id:N trading:organization_name:N inquiries:email_address:N phone_line:phone_number:N place:city:N
modules learning_catalog module_key:record_id:N module_name:product_name:N level:category:N remarks:free_text:N
registrations course_activity registration_key:record_id:N attendee:reference_id:L:trainees.tr class_ref:reference_id:N:modules.module_key location_provider:reference_id:N:providers.pr registration_date:date:L standing:status:L
assessments course_activity mark_key:record_id:N register_ref:reference_id:L:registrations.registration_key evaluated:date:L outcome:status:L comment:free_text:L
"""
}
ROOT = Path("data/groq_anchor_holdout")


def prepare():
    ROOT.mkdir(parents=True, exist_ok=False)
    files = {}
    for i, (sector, specification) in enumerate(SOURCES.items()):
        rng = Random(83521 + i * 419)
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
    """One real Groq response set for both decision engines."""
    original = contextual_eval.FreeCatalogProvider
    anchor_check = contextual_catalog.corroborated_subjects
    calls = {}

    class SharedGroq(original):
        replay = False

        def request(self, payload, count, system, schema):
            key = json.dumps([payload, count, system, schema], sort_keys=True)
            if self.replay:
                assert key in calls, "Baseline and candidate submitted different model requests."
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
        contextual_catalog.corroborated_subjects = lambda *args: set()
        run("groq", sources, ROOT / "prior_decision_logic", None, None)
    finally:
        contextual_eval.FreeCatalogProvider = original
        contextual_catalog.corroborated_subjects = anchor_check


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

