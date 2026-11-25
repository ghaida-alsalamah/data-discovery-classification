"""Prepare, seal, and evaluate independent synthetic relational schemas."""
import argparse
import json
import sqlite3
from pathlib import Path
from random import Random

from evaluation.contextual_eval import run
from evaluation.catalog_verifier import verify, evidence_scores
from evaluation.groq_hierarchy_holdout import schema_evidence
from evaluation.groq_architecture_holdout import classification_confidence
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
"equipment_leasing": """
lessees customer_accounts lessee_key:record_id:L listing_name:person_name:D relay:email_address:D return_line:phone_number:D registered:date:L
leasing_partners supplier_registry ref:record_id:N business_name:organization_name:N reach:email_address:N line:phone_number:N district:city:N
machines equipment_inventory code:record_id:N title:product_name:N registry:business_identifier:N partner:reference_id:N:leasing_partners.ref description:free_text:N
agreements lease_lifecycle agreement:record_id:N lessee_ref:reference_id:L:lessees.lessee_key asset:reference_id:N:machines.code began:date:L phase:status:L price:price:L
agreement_charges lease_lifecycle seq:record_id:N agreement_ref:reference_id:L:agreements.agreement added:date:L charge:financial_amount:L detail:free_text:L
maintenance_audits maintenance_oversight serial:record_id:N asset:reference_id:N:machines.code inspected:date:N decision:status:N notes:free_text:N
""",
"regional_health_transport": """
riders rider_registrations r:record_id:L display:person_name:D contact_point:email_address:D callback:phone_number:D home_city:city:L
responders workforce_directory staff_key:record_id:L staff_name:person_name:D inbox:email_address:D mobile:phone_number:D enrolled:date:L
depots depot_inventory depot:record_id:N manager_name:organization_name:N switchboard:phone_number:N mailstop:email_address:N district:city:N
trips trip_lifecycle job:record_id:N requested_by:reference_id:L:riders.r assigned_to:reference_id:L:responders.staff_key site:reference_id:N:depots.depot requested:date:L progress:status:L instructions:free_text:L
trip_updates trip_lifecycle change_key:record_id:N trip_ref:reference_id:L:trips.job written:date:L status:status:L details:free_text:L
dispatch_reviews service_oversight report:record_id:N dispatch:reference_id:N:trips.job reviewed_at:date:N outcome:status:N record_notes:free_text:N
""",
"aquaculture_supply": """
operators supplier_registry op:record_id:N organization_name:organization_name:N front_desk:email_address:N offices:phone_number:N home_port:city:N
inspectors workforce_directory emp:record_id:L identity_label:person_name:D route_mail:email_address:D voice_contact:phone_number:D appointed:date:L
brood_stock stock_inventory lot:record_id:N stock_serial:business_identifier:N line_name:product_name:N supplier:reference_id:N:operators.op origin:location:N
harvests harvest_lifecycle harvest:record_id:N source_lot:reference_id:N:brood_stock.lot assigned_to:reference_id:L:inspectors.emp logged_at:date:N phase:status:N notes:free_text:N
harvest_items harvest_lifecycle item_key:record_id:N parent:reference_id:N:harvests.harvest class:category:N description:free_text:N
permits regulatory_oversight permit:record_id:N harvest_ref:reference_id:N:harvests.harvest issued:date:N licensing_ref:business_identifier:N circumstance:free_text:N
"""
}
ROOT = Path("data/groq_verifier_holdout")


def prepare():
    ROOT.mkdir(parents=True, exist_ok=False)
    files = {}
    for i, (sector, specification) in enumerate(SOURCES.items()):
        rng = Random(28311 + i * 487)
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
            "dictionary": None, "verifier": digest(Path("evaluation/catalog_verifier.py")),
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




def verification_diagnostics(sources, mode):
    fields = []
    for root, name in sources:
        truth = read(root / (name + "_labels.json"))
        rows = read(ROOT / mode / (name + ".json"))["classifications"]
        scored = rows_for(name, truth, rows)
        bad = {(r["table"], r["column"]) for r in joint_by_membership(
            [dict(r, review_required=False) for r in scored])["errors"]}
        fields.extend((evidence_scores(r), r["privacy_score"] if "privacy_score" in r else r["confidence"],
                       (r["table_name"], r["column_name"]) not in bad, not r["review_required"],
                       r.get("verification_privacy"), r.get("verification_domains"))
                      for r in rows)
    def auc(samples):
        pos = [x for x, ok in samples if ok]
        neg = [x for x, ok in samples if not ok]
        return sum((a > b) + .5 * (a == b) for a in pos for b in neg)/(len(pos)*len(neg)) if pos and neg else None
    report = {}
    for name, subset in (("all", fields), ("automatic", [r for r in fields if r[3]]),
                         ("verified_automatic", [r for r in fields if r[3] and r[4]])):
        report[name] = {"fields": len(subset),
                        "existing_semantic_auc": auc([(r[1], r[2]) for r in subset]),
                        "verifier_evidence_auc": auc([(r[0], r[2]) for r in subset]),
                        "bins": {str(level): [sum(r[2] for r in subset if r[0] == level),
                                              sum(r[0] == level for r in subset)] for level in range(4)},
                        "recommended_privacy_reviews": sum(bool(r[4] and r[4]["action"] == "review") for r in subset),
                        "recommended_domain_reviews": sum(bool(r[5] and any(v["action"] == "review" for v in r[5]))
                                                         for r in subset)}
    write_report(ROOT / mode / "verifier_diagnostics.json", report)


def development():
    output = Path("data/groq_verifier_development")
    saved = Path("data/groq_ownership_development/groq")
    with httpx.Client(timeout=35, trust_env=False, follow_redirects=False) as client:
        provider = contextual_eval.FreeCatalogProvider(client, "groq")
        for root, name in contextual_eval.DEV:
            rows = read(saved / (name + ".json"))["classifications"]
            truth = read(root / (name + "_labels.json"))
            before = joint_by_membership(rows_for(name, truth, rows))
            verify(provider, rows, *schema_evidence(root / (name + ".sqlite")))
            after = joint_by_membership(rows_for(name, truth, rows))
            write_report(output / (name + ".json"), {"baseline": before, "verified": after})
        write_report(output / "runtime.json", provider.counters)


def paired_run(sources):
    original = contextual_eval.FreeCatalogProvider
    scanner = contextual_eval.AssetScan
    calls = {}

    class SharedGroq(original):
        replay = False

        def request(self, payload, count, system, schema):
            key = json.dumps([payload, count, system, schema], sort_keys=True)
            if self.replay and not (isinstance(payload, dict) and "domain_pairs" in payload):
                assert key in calls, "Production request differs from the recorded baseline."
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

    class VerifiedScan(scanner):
        def scan(self, path, **kwargs):
            report = super().scan(path, **kwargs)
            verify(self.provider, report["classifications"], *schema_evidence(path))
            return report

    contextual_eval.FreeCatalogProvider = SharedGroq
    try:
        run("groq", sources, ROOT / "baseline", None, None)
        SharedGroq.replay = True
        contextual_eval.AssetScan = VerifiedScan
        run("groq", sources, ROOT / "verifier", None, None)
    finally:
        contextual_eval.FreeCatalogProvider = original
        contextual_eval.AssetScan = scanner
    confidence_report(sources, ("baseline", "verifier"))
    verification_diagnostics(sources, "verifier")


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
        def validate_seal():
            if config() != frozen["config"] or any(
                    digest(ROOT / name) != sha for name, sha in frozen["fixtures"].items()):
                raise ValueError("Frozen evaluation configuration or fixtures changed.")

        validate_seal()
        paired_run([(ROOT, name) for name in SOURCES])
        validate_seal()

