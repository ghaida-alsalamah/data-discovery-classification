"""Prepare, seal, and evaluate independent synthetic relational schemas."""
import argparse
import json
import sqlite3
from pathlib import Path
from collections import Counter
from random import Random

from evaluation.contextual_eval import run
from backend.app.classification import contextual_catalog
from backend.app.classification.evidence_catalog import domain_subject, verified_graph
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
"event_hospitality": """
guests lodging guest:record_id:L name_line:person_name:D inbound:email_address:D callback:phone_number:D created:date:L
venues facilities venue:record_id:N operating_body:organization_name:N enquiries:email_address:N line:phone_number:N city:city:N
reservations bookings reservation:record_id:N booker:reference_id:L:guests.guest site:reference_id:N:venues.venue requested:date:L phase:status:L rate:price:L
reservation_items bookings rownum:record_id:N reservation_ref:reference_id:L:reservations.reservation nights:category:L date_booked:date:L meal_plan:category:L
receipts bookings receipt:record_id:N reservation_ref:reference_id:L:reservations.reservation paid_on:date:L payment_method:payment_method:L note:free_text:L
""",
"commercial_fisheries": """
cooperatives operators coop:record_id:N registered_operator:organization_name:N contact:email_address:N dial:phone_number:N district:city:N
vessels fleet vessel:record_id:N sorting_code:business_identifier:N title:product_name:N managing_coop:reference_id:N:cooperatives.coop
skippers staffing badge:record_id:L heading:person_name:D return_to:email_address:D cell:phone_number:D entitled_on:date:L
hauls operations haul:record_id:N boat:reference_id:N:vessels.vessel skipper:reference_id:L:skippers.badge hauled_on:date:N stage:status:N report:free_text:N
haul_items operations item:record_id:N haul_ref:reference_id:N:hauls.haul category:category:N item_notes:free_text:N
landing_documents compliance doc:record_id:N haul_ref:reference_id:N:hauls.haul issued:date:N registration_no:business_identifier:N
""",
"appliance_warranty": """
owners holders key_no:record_id:L identity_caption:person_name:D point:email_address:D alternate:phone_number:D hometown:city:L
vendors suppliers id:record_id:N legal_entity:organization_name:N customer_line:phone_number:N feedback:email_address:N operating_city:city:N
catalog assets model:record_id:N display_name:product_name:N manufacturer_ref:reference_id:N:vendors.id stock_code:business_identifier:N description:free_text:N
policies service policy:record_id:N holder_ref:reference_id:L:owners.key_no equipment:reference_id:N:catalog.model purchased:date:L fee:price:L condition:status:L
policy_claims service claim:record_id:N policy_ref:reference_id:L:policies.policy raised_at:date:L status:status:L comment:free_text:L
claim_actions service action:record_id:N claim_ref:reference_id:L:policy_claims.claim action_date:date:L action_comment:free_text:L
"""
}
ROOT = Path("data/groq_architecture_holdout")


def prepare():
    ROOT.mkdir(parents=True, exist_ok=False)
    files = {}
    for i, (sector, specification) in enumerate(SOURCES.items()):
        rng = Random(28087 + i * 653)
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



def corroborate_process_links(grouped, tables, relationships, checks, person_entities):
    """Refine domains only for tables with a verified operational parent and shared purpose terms."""
    _, outgoing = verified_graph(tables, relationships, checks)
    original = {name: Counter(row["data_domain"] for row in fields.values()).most_common(1)[0][0]
                for name, fields in grouped.items()}
    for child, fields in grouped.items():
        links = outgoing[child]
        if len(links) != 1 or child in person_entities:
            continue
        edge = links[0]
        parent = edge["target"]
        if parent in person_entities or not outgoing[parent]:
            continue
        if any(row["personal_linkage"] == "direct" for row in (*fields.values(), *grouped[parent].values())):
            continue
        source, target = original[child], original[parent]
        parent_terms = domain_subject(parent)
        terms = domain_subject(child) | {term for col in edge["data"]["source_columns"] for term in domain_subject(col)}
        if source == target or target == "unknown" or not (parent_terms & terms):
            continue
        for row in fields.values():
            if row["data_domain"] == source:
                row.update(data_domain=target, domain_resolution="verified_relationship_group")


def classification_confidence(row, *, include_joint=True):
    """Evidence strengths per output dimension, without changing review routing."""
    review = set(row["review_dimensions"])
    semantic = row["confidence"]
    domain_state = row["domain_resolution"]
    if row["data_domain"] == "unknown" or "domain" in review:
        domain = .4
    elif domain_state == "verified_relationship_group":
        domain = .85
    elif domain_state in {"table_subject", "dictionary", "dictionary_description"}:
        domain = .8
    else:
        domain = .65
    evidence = row.get("personal_linkage_evidence", {})
    if row["personal_data"] == "uncertain" or "privacy" in review:
        privacy = .4
    elif (evidence.get("method") == "measured_subject_path"
          and evidence.get("matched_source_rows") == evidence.get("source_rows")):
        privacy = .75 if evidence.get("subject_evidence") == "corroborated_entity" else .9
    elif evidence.get("method") in {"independent_content_check", "shared_contact_scope"}:
        privacy = .85
    else:
        privacy = .65
    scores = {"semantic": semantic, "domain": domain, "privacy": privacy}
    if include_joint:
        scores["joint"] = min(semantic, domain, privacy)
    return scores


def confidence_report(sources, modes):
    for mode in modes:
        rows, scores = [], {}
        for root, name in sources:
            truth = read(root / (name + "_labels.json"))
            predictions = read(ROOT / mode / (name + ".json"))["classifications"]
            rows.extend(rows_for(name, truth, predictions))
            for row in predictions:
                scores[name, row["table_name"], row["column_name"]] = classification_confidence(row)
        def key(row):
            return row["sector"], row["table"], row["column"]
        errors = {key(row): row["wrong_dimensions"] for row in
                  joint_by_membership([dict(row, review_required=False) for row in rows])["errors"]}
        report = {}
        for score, outcome in (("semantic", "semantic"), ("domain", "group"), ("privacy", "privacy"),
                               ("semantic", "joint"), ("joint", "joint")):
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


def paired_run(sources):
    original = contextual_eval.FreeCatalogProvider
    original_groups = contextual_catalog.contextual_domains

    def experimental_groups(provider, grouped, tables, relationships, checks):
        original_groups(provider, grouped, tables, relationships, checks)
        person_entities = {name for name, rows in grouped.items() if any(
            row["personal_linkage"] == "direct" or row.get("personal_linkage_evidence", {}).get(
                "subject_evidence") == "corroborated_entity" for row in rows.values()
        )}
        corroborate_process_links(grouped, tables, relationships, checks, person_entities)
    calls = {}

    class SharedGroq(original):
        replay = False

        def request(self, payload, count, system, schema):
            key = json.dumps([payload, count, system, schema], sort_keys=True)
            if self.replay and key in calls:
                result, error = calls[key]
                if error:
                    raise error
                return result
            if self.replay:
                assert "groups" in schema["properties"], "Unexpected field request during replay."
            try:
                result = super().request(payload, count, system, schema)
            except Exception as error:
                calls[key] = (None, error)
                raise
            calls[key] = (result, None)
            return result

    run("offline", sources, ROOT / "offline", None, None)
    contextual_eval.FreeCatalogProvider = SharedGroq
    try:
        run("groq", sources, ROOT / "recovery", None, None)
        SharedGroq.replay = True
        SharedGroq.recover_field_batches = False
        run("groq", sources, ROOT / "baseline", None, None)
        SharedGroq.recover_field_batches = True
        contextual_catalog.contextual_domains = experimental_groups
        run("groq", sources, ROOT / "process_links", None, None)
    finally:
        contextual_eval.FreeCatalogProvider = original
        contextual_catalog.contextual_domains = original_groups
    confidence_report(sources, ("offline", "baseline", "recovery", "process_links"))


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

