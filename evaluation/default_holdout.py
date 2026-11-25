"""A sealed, same-input comparison on four project-held-out Spider databases."""
import argparse
import json
import sqlite3
from collections import Counter
from pathlib import Path
from subprocess import check_output
from time import perf_counter

from backend.app.classification.local_llm import launch, peak_memory
from backend.app.classification.production_catalog import EXTENDED
from backend.app.classification.taxonomy import TYPES
from evaluation.public_catalog import LINKAGE, PERSONAL, protocol_hashes, score
from evaluation.reliability_infer import digest, fingerprint
from evaluation.score import ratio, read, rows_for, summarize
from scripts.scan_data_asset import AssetScan, FAST_MODEL, LOCAL_SERVER, write_report

ROOT = Path("data/default_validation")
THREADS = 4
GROUP_MINIMUM = .85
# Metadata and schema roles annotated before exploring classifier output. D: direct,
# L: person-linked, N: neither, U: insufficient evidence to judge privacy.
# A foreign key to a business object does not inherit the privacy of other fields.
LABELS = {
    "battle_death": {
        "battle": ("military_events", """id:record_id:N name:battle_name:N date:date:N
            bulgarian_commander:person_name:D latin_commander:person_name:D result:category:N"""),
        "ship": ("vessel_registry", """lost_in_battle:reference_id:N id:record_id:N name:vessel_name:N
            tonnage:mass:N ship_type:category:N location:location:N disposition_of_ship:status:N"""),
        "death": ("casualty_statistics", "caused_by_ship_id:reference_id:N id:record_id:N note:free_text:U killed:count:N injured:count:N"),
    },
    "dog_kennels": {
        "Breeds": ("animal_reference", "breed_code:record_id:N breed_name:category:N"),
        "Sizes": ("animal_reference", "size_code:record_id:N size_description:category:N"),
        "Charges": ("billing", "charge_id:record_id:N charge_type:category:N charge_amount:price:N"),
        "Treatment_Types": ("animal_care", "treatment_type_code:record_id:N treatment_type_description:free_text:N"),
        "Owners": ("owner_directory", """owner_id:record_id:L first_name:person_name:D last_name:person_name:D
            street:location:L city:city:L state:location:L zip_code:postal_code:L email_address:email_address:D
            home_phone:phone_number:D cell_number:phone_number:D"""),
        "Dogs": ("animal_registry", """dog_id:record_id:N owner_id:reference_id:L abandoned_yn:boolean_flag:N
            breed_code:reference_id:N size_code:reference_id:N name:animal_name:N age:age:N date_of_birth:date:N
            gender:category:N weight:mass:N date_arrived:date:N date_adopted:date:N date_departed:date:N"""),
        "Professionals": ("practitioner_directory", """professional_id:record_id:L role_code:identifier:L first_name:person_name:D
            street:location:L city:city:L state:location:L zip_code:postal_code:L last_name:person_name:D
            email_address:email_address:D home_phone:phone_number:D cell_number:phone_number:D"""),
        "Treatments": ("animal_care", """treatment_id:record_id:N dog_id:reference_id:N professional_id:reference_id:L
            treatment_type_code:reference_id:N date_of_treatment:date:L cost_of_treatment:price:L"""),
    },
    "hospital_1": {
        "Physician": ("clinical_workforce", "EmployeeID:record_id:L Name:person_name:D Position:job_title:L SSN:ssn:D"),
        "Nurse": ("clinical_workforce", "EmployeeID:record_id:L Name:person_name:D Position:job_title:L Registered:boolean_flag:L SSN:ssn:D"),
        "Department": ("organization", "DepartmentID:record_id:N Name:department:N Head:reference_id:L"),
        "Affiliated_With": ("organization", "Physician:reference_id:L Department:reference_id:N PrimaryAffiliation:boolean_flag:L"),
        "Procedures": ("clinical_catalog", "Code:record_id:N Name:procedure_name:N Cost:price:N"),
        "Trained_In": ("staff_credentials", "Physician:reference_id:L Treatment:reference_id:N CertificationDate:date:L CertificationExpires:date:L"),
        "Patient": ("patient_directory", "SSN:ssn:D Name:person_name:D Address:location:L Phone:phone_number:D InsuranceID:policy_number:L PCP:reference_id:L"),
        "Appointment": ("patient_care", """AppointmentID:record_id:N Patient:reference_id:L PrepNurse:reference_id:L
            Physician:reference_id:L Start:date:L End:date:L ExaminationRoom:location:L"""),
        "Medication": ("clinical_catalog", "Code:record_id:N Name:medication_name:N Brand:brand_name:N Description:free_text:N"),
        "Prescribes": ("patient_care", "Physician:reference_id:L Patient:reference_id:L Medication:reference_id:N Date:date:L Appointment:reference_id:L Dose:medication_dose:L"),
        "Block": ("clinical_facilities", "BlockFloor:record_id:N BlockCode:record_id:N"),
        "Room": ("clinical_facilities", "RoomNumber:record_id:N RoomType:category:N BlockFloor:reference_id:N BlockCode:reference_id:N Unavailable:boolean_flag:N"),
        "On_Call": ("clinical_staff_scheduling", "Nurse:reference_id:L BlockFloor:reference_id:N BlockCode:reference_id:N OnCallStart:date:L OnCallEnd:date:L"),
        "Stay": ("patient_care", "StayID:record_id:N Patient:reference_id:L Room:reference_id:N StayStart:date:L StayEnd:date:L"),
        "Undergoes": ("patient_care", "Patient:reference_id:L Procedures:reference_id:N Stay:reference_id:L DateUndergoes:date:L Physician:reference_id:L AssistingNurse:reference_id:L"),
    },
    "voter_1": {
        "AREA_CODE_STATE": ("telephone_geography", "area_code:record_id:N state:location:N"),
        "CONTESTANTS": ("contestant_directory", "contestant_number:record_id:L contestant_name:person_name:D"),
        "VOTES": ("voting_activity", "vote_id:record_id:N phone_number:phone_number:D state:reference_id:L contestant_number:reference_id:L created:date:L"),
    },
}


def configuration(model, server):
    return {
        "commit": check_output(["git", "rev-parse", "HEAD"], text=True).strip(),
        "backend": fingerprint(Path(".")), "protocol": protocol_hashes(),
        "evaluator": digest(Path(__file__)), "requirements": digest(Path("backend/requirements.txt")),
        "gguf": digest(model), "server": digest(server),
        "runtime_dlls": {p.name: digest(p) for p in server.parent.glob("*.dll")},
        "model_name": model.name, "threads": THREADS, "dictionary": None,
        "group_membership_minimum": GROUP_MINIMUM, "modes": ["evidence", "default_offline", "default"],
    }


def freeze(root, model, server):
    seal = root / "seal.json"
    if seal.exists():
        raise FileExistsError(seal)
    inputs = {}
    for name, tables in LABELS.items():
        db = root / (name + ".sqlite")
        truth = {}
        for table, (domain, specification) in tables.items():
            truth[table] = {}
            for item in specification.split():
                field, semantic, privacy = item.split(":")
                truth[table][field] = {"semantic_type": semantic, "domain": domain,
                                       "personal_data": PERSONAL[privacy], "personal_linkage": LINKAGE[privacy]}
        with sqlite3.connect(db.resolve().as_uri() + "?mode=ro", uri=True) as connection:
            actual = {table: {col[1] for col in connection.execute("PRAGMA table_info(" + json.dumps(table) + ")")}
                      for table, in connection.execute("SELECT name FROM sqlite_master "
                                                       "WHERE type='table' AND name NOT LIKE 'sqlite_%'")}
        if actual != {table: set(fields) for table, fields in truth.items()}:
            raise ValueError(f"Incomplete label coverage for {name}: {actual}")
        tags = root / (name + "_labels.json")
        write_report(tags, truth)
        inputs.update({p.name: digest(p) for p in (db, tags)})
    write_report(seal, {"configuration": configuration(model, server), "inputs": inputs})


def joint_by_membership(rows):
    expected = Counter((r["sector"], r["domain_true"]) for r in rows)
    predicted = Counter((r["sector"], r["domain_pred"]) for r in rows)
    overlap = Counter((r["sector"], r["domain_true"], r["domain_pred"]) for r in rows)
    automatic = [r for r in rows if not r["review_required"]]
    errors = []
    for row in automatic:
        sector, actual, guess = row["sector"], row["domain_true"], row["domain_pred"]
        membership = (2 * overlap[sector, actual, guess] / (expected[sector, actual] + predicted[sector, guess])
                      if guess != "unknown" else 0)
        wrong = [dimension for dimension, ok in (
            ("semantic", row["semantic_true"] == row["semantic_pred"]),
            ("group", membership >= GROUP_MINIMUM),
            ("privacy", row["personal_true"] in {"uncertain", row["personal_pred"]}),
        ) if not ok]
        if wrong:
            errors.append({**row, "wrong_dimensions": wrong, "membership_f1": membership})
    return {"accuracy": ratio(len(automatic) - len(errors), len(automatic)),
            "correct": len(automatic) - len(errors), "fields": len(automatic),
            "coverage": ratio(len(automatic), len(rows)), "errors": errors}


def metrics(rows, entries, mode):
    result = score(rows, entries, mode)
    original_distribution = summarize(rows)
    result["strict_semantic_confusion"] = original_distribution["confusions"]["semantic_strict"]
    result["confidence"] = original_distribution["confidence"]
    result["group_membership_joint"] = joint_by_membership(rows)
    for label, subset in (
            ("verified_extension_truth", [r for r in rows if r["semantic_true"] in EXTENDED]),
            ("open_type_truth", [r for r in rows if r["semantic_true"] not in TYPES | EXTENDED])):
        result[label] = {"fields": len(subset), "exact_hits": sum(r["semantic_true"] == r["semantic_pred"] for r in subset)}
    result["direct"]["misses"] = [{"sector": key["sector"], "table": key["table"], "column": key["column"],
                                   "expected": key["semantic_true"], "predicted": key["semantic_pred"]}
                                  for key, (truth, row, _) in zip(rows, entries)
                                  if truth["personal_linkage"] == "direct" and not row["direct_pii_type"]]
    return result


def evaluate(root, model, server):
    seal = read(root / "seal.json")

    def verify():
        if (configuration(model, server) != seal["configuration"]
                or any(digest(root / name) != sha for name, sha in seal["inputs"].items())):
            raise ValueError("Frozen inputs or configuration changed.")

    verify()
    started = perf_counter()
    outputs = {}
    for mode in seal["configuration"]["modes"]:
        (root / mode).mkdir(exist_ok=False)

    def scan(mode, scanner):
        by_database = {}
        for name in LABELS:
            report = scanner.scan(root / (name + ".sqlite"))
            classifiers = report["classifications"]
            by_database[name] = {
                "classifications": classifiers,
                "seconds": report["timing_seconds"]["total"],
                "context_status": dict(Counter(r.get("context_status", "absent") for r in classifiers)),
                "requirements": {
                    "asset_tables": len(report["schema"]["tables"]),
                    "relationship_edges": len(report["relationships"]["edges"]),
                    "domains": len(report["domains"]["domains"]),
                    "quality_produced": bool(report["quality"]),
                    "opportunities": len(report["opportunities"]["opportunities"]),
                    "review_history": isinstance(report["review_history"], list),
                },
            }
            write_report(root / mode / (name + ".json"), by_database[name])
            print(mode, name, by_database[name]["context_status"], flush=True)
        return by_database

    outputs["evidence"] = scan("evidence", AssetScan("evidence"))
    outputs["default_offline"] = scan("default_offline", AssetScan(offline=True))
    with launch(server, model, threads=THREADS) as runtime:
        outputs["default"] = scan("default", AssetScan(runtime=runtime))
        runtime_report = {**runtime.counters, "startup_seconds": runtime.startup_seconds,
                          "peak_server_memory_mib": peak_memory(runtime.process.pid)}
    verify()
    result = {"configuration": seal["configuration"], "runtime": runtime_report,
              "wall_seconds": perf_counter() - started}
    for mode, databases in outputs.items():
        pooled, pooled_entries, per_database = [], [], {}
        for name, report in databases.items():
            truth = read(root / (name + "_labels.json"))
            predicts = report["classifications"]
            rows = rows_for(name, truth, predicts)
            by_key = {(row["table_name"], row["column_name"]): row for row in predicts}
            entries = [(truth[r["table"]][r["column"]], by_key[r["table"], r["column"]], {}) for r in rows]
            pooled.extend(rows)
            pooled_entries.extend(entries)
            per_database[name] = {**metrics(rows, entries, mode),
                                  **{k: v for k, v in report.items() if k != "classifications"}}
        result[mode] = {"overall": metrics(pooled, pooled_entries, mode), "by_database": per_database,
                        "seconds": sum(report["seconds"] for report in databases.values())}
    write_report(root / "metrics.json", result)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("freeze", "evaluate"))
    parser.add_argument("--model", type=Path, default=FAST_MODEL)
    parser.add_argument("--server", type=Path, default=LOCAL_SERVER)
    args = parser.parse_args()
    {"freeze": freeze, "evaluate": evaluate}[args.action](ROOT, args.model, args.server)
