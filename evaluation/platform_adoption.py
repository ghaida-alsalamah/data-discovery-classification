"""Run vendor CLI workflows against sealed synthetic sources and score their native outputs."""
import argparse
from collections import Counter
import json
import os
from pathlib import Path
import subprocess
import sys
from tempfile import TemporaryDirectory
from time import perf_counter
from urllib.parse import quote

from evaluation.platform_fixtures import ROOT, digest, save

META_VERSION = "2.0.0"
DATAHUB_VERSION = "1.6.0.5"
META = Path(".deps/metacrafter-experiment")
ASSETS = Path(".deps/metacrafter-assets")
RULES = ASSETS / "rules/metacrafter-rules-0.0.8"
REGISTRY = ASSETS / "registry"
DATAHUB = Path(".deps/platform-datahub/Scripts/python.exe" if os.name == "nt"
               else ".deps/platform-datahub/bin/python")
META_ARGS = ["--format", "full", "--output-format", "json", "--registry-offline", "--quiet", "--stdout"]

# One-way mappings of equivalent native meanings. The file is sealed before inference.
META_TYPES = {
    "email": "email_address", "phone": "phone_number", "phone_e164": "phone_number",
    "person_fullname": "person_name", "person_firstname": "person_name", "person_lastname": "person_name",
    "date": "date", "datetime": "date", "timestamp": "date", "year": "year",
    "boolean": "boolean_flag", "iso4217curcode": "currency_code", "city": "city", "sacity": "city",
    "address": "location", "trackingnumber": "tracking_code", "percentage": "percentage",
}
DATAHUB_TYPES = {
    "EMAIL_ADDRESS": "email_address", "EMAIL": "email_address", "PHONE_NUMBER": "phone_number",
    "PERSON_NAME": "person_name", "PERSON": "person_name", "NAME": "person_name",
    "DATE": "date", "DATE_TIME": "date", "CITY": "city", "ADDRESS": "location",
}
DIRECT = {"person_name", "phone_number", "email_address", "saudi_national_id", "saudi_residency_id"}


def read(path):
    return json.loads(path.read_text(encoding="utf-8"))


def verify_inputs(root):
    fixture = read(root / "fixtures.json")
    if any(digest(root / name) != sha for name, sha in fixture["inputs"].items()):
        raise ValueError("Frozen source or labels changed.")
    return sorted(name.removesuffix(".sqlite") for name in fixture["inputs"] if name.endswith(".sqlite"))


def configuration(root):
    return {
        "scoring": digest(Path(__file__)), "fixture_manifest": digest(root / "fixtures.json"),
        "rules": {str(path.relative_to(RULES)): digest(path) for path in sorted(RULES.rglob("*"))
                  if path.is_file() and path.suffix in {".yaml", ".yml", ".py"}},
        "registry": {path.name: digest(path) for path in sorted(REGISTRY.glob("*")) if path.is_file()},
        "versions": {"metacrafter": META_VERSION, "datahub": DATAHUB_VERSION},
        "metacrafter_options": META_ARGS, "datahub_classification_sample": 100,
    }


def native_command(args, *, env, cwd=None):
    started = perf_counter()
    process = subprocess.run(args, cwd=cwd, env=env, capture_output=True, encoding="utf-8",
                             errors="replace", timeout=240)
    if process.returncode:
        # Neither driver errors nor native logs are published as benchmark artifacts.
        raise RuntimeError(f"Native {args[2]} workflow exited with code {process.returncode}.")
    return process.stdout, perf_counter() - started


def run_meta(root, name):
    env = {**os.environ, "PYTHONIOENCODING": "utf-8", "PYTHONPATH": str(META.resolve()),
           "METACRAFTER_RULES_DIR": str(RULES.resolve()), "METACRAFTER_RULES_OFFLINE": "1"}
    source = quote((root / (name + ".sqlite")).resolve().as_posix(), safe="/:")
    text, seconds = native_command(
        [sys.executable, "-m", "metacrafter", "scan", "sql", "sqlite:///file:" + source + "?mode=ro&uri=true",
         *META_ARGS, "--registry-path", str(REGISTRY.resolve())],
        env=env,
    )
    report = json.loads(text)
    if not report["complete"] or report["errors"]:
        raise ValueError(f"Metacrafter reported incomplete coverage for {name}.")
    fields = []
    for table in report["sources"]:
        if not table["complete"] or table["samples_included"] or table["effective_mode"] != "rules":
            raise ValueError("Unexpected native scan mode.")
        for field in table["data"]:
            matches = [{"datatype": m["datatype"], "confidence": m["confidence"], "rule": m["ruleid"]}
                       for m in field["matches"]]
            tags = set(field["tags"])
            native = matches[0]["datatype"] if matches else None
            semantic = ("reference_id" if "foreign_key" in tags else "record_id" if "primary_key" in tags
                        else META_TYPES.get(native))
            reported = bool(field["pii"]["is_pii"])
            fields.append({"table": table["table"].split(".", 1)[-1], "column": field["field"],
                           "semantic_type": semantic, "native": matches, "pii_reported": reported,
                           "direct": any(META_TYPES.get(p) in DIRECT or p == "said"
                                         for p in field["pii"]["datatypes"]),
                           "primary_key": "primary_key" in tags, "foreign_key": "foreign_key" in tags})
    return {"seconds": seconds, "fields": fields,
            "versions": {k: report["sources"][0][k] for k in ("report_version", "rules_version", "registry")}}


def datahub_recipe(name, outfile):
    return {
        "source": {"type": "postgres", "config": {
            "host_port": "127.0.0.1:55431", "database": name, "username": "fixture_reader",
            "password": "${NATIVE_CATALOG_POSTGRES_PASSWORD}",
            "schema_pattern": {"allow": ["^public$"]}, "include_views": False,
            "classification": {"enabled": True, "sample_size": 100, "max_workers": 1},
            "profiling": {"enabled": True, "profile_table_level_only": False,
                          "include_field_sample_values": False,
                          "include_field_min_value": False, "include_field_max_value": False},
            "stateful_ingestion": {"enabled": False},
        }},
        "sink": {"type": "file", "config": {"filename": str(outfile)}},
    }


def extract_terms(obj):
    return [item["urn"].rsplit(":", 1)[-1] for item in (obj or {}).get("terms", [])]


def datahub_fields(entries):
    for entry in entries:
        if entry.get("aspectName") != "schemaMetadata":
            continue
        aspect = entry["aspect"]
        schema = json.loads(aspect["value"]) if "value" in aspect else aspect
        table = entry["entityUrn"].split(",", 2)[1].rsplit(".", 1)[-1]
        primary = set(schema.get("primaryKeys") or [])
        foreign = {field for key in schema.get("foreignKeys") or [] for field in key.get("sourceFields", [])}
        for field in schema["fields"]:
            name = field["fieldPath"]
            native = extract_terms(field.get("glossaryTerms"))
            kinds = {DATAHUB_TYPES.get(label) for label in native}
            kinds.discard(None)
            semantic = ("reference_id" if name in foreign else "record_id" if name in primary
                        else next(iter(kinds)) if len(kinds) == 1 else None)
            yield {"table": table, "column": name, "semantic_type": semantic, "native": native,
                   "pii_reported": bool(kinds & DIRECT), "direct": bool(kinds & DIRECT),
                   "primary_key": name in primary, "foreign_key": name in foreign}


def run_datahub(_root, name):
    secret = os.environ["NATIVE_CATALOG_POSTGRES_PASSWORD"]
    env = {**os.environ, "DATAHUB_TELEMETRY_ENABLED": "false", "PYTHONIOENCODING": "utf-8",
           "NATIVE_CATALOG_POSTGRES_PASSWORD": secret}
    with TemporaryDirectory(prefix="datahub-native-") as folder:
        recipe = Path(folder) / "recipe.json"
        output = Path(folder) / "metadata.json"
        save(recipe, datahub_recipe(name, output))
        _, seconds = native_command([str(DATAHUB.resolve()), "-m", "datahub", "ingest", "-c", str(recipe)], env=env)
        fields = list(datahub_fields(read(output)))
    if not fields:
        raise ValueError("Native DataHub ingestion did not export schema fields.")
    return {"seconds": seconds, "fields": fields, "versions": {"datahub": DATAHUB_VERSION}}


def ratio(numerator, denominator):
    return numerator / denominator if denominator else None


def binary(pairs):
    hits = Counter(pairs)
    tp, fp, fn = (hits[key] for key in ((True, True), (False, True), (True, False)))
    return {"tp": tp, "fp": fp, "fn": fn, "tn": hits[False, False],
            "precision": ratio(tp, tp + fp), "recall": ratio(tp, tp + fn),
            "f1": ratio(2 * tp, 2 * tp + fp + fn)}


def field_results(root, name, fields):
    truth = {(table, field): label for table, columns in read(root / (name + "_labels.json")).items()
             for field, label in columns.items()}
    found = {(row["table"], row["column"]): row for row in fields}
    if truth.keys() != found.keys() or len(found) != len(fields):
        raise ValueError(f"Native field coverage differs from the sealed schema for {name}.")
    return [{"database": name, "truth": truth[key], **row} for key, row in found.items()]


def summarize(rows, supported):
    fields = len(rows)
    exact = sum(r["truth"]["semantic_type"] == r["semantic_type"] for r in rows)
    mapped = [r for r in rows if r["semantic_type"] is not None]
    supported_rows = [r for r in rows if r["truth"]["semantic_type"] in supported]
    return {
        "fields": fields, "exact_semantic_accuracy": ratio(exact, fields), "exact_matches": exact,
        "mapped_semantic_coverage": ratio(len(mapped), fields),
        "mapped_semantic_accuracy": ratio(exact, len(mapped)),
        "unsupported_truth_counts": dict(Counter(r["truth"]["semantic_type"] for r in rows
                                                  if r["truth"]["semantic_type"] not in supported)),
        "supported_exact_accuracy": ratio(exact, len(supported_rows)),
        "native_pii_vs_direct": binary([(r["truth"]["personal_linkage"] == "direct", r["pii_reported"]) for r in rows]),
        "direct_pii": binary([(r["truth"]["personal_linkage"] == "direct", r["direct"]) for r in rows]),
        "personal": binary([(r["truth"]["personal_data"] == "yes", r["pii_reported"]) for r in rows]),
        "person_linked": binary([(r["truth"]["personal_linkage"] == "linked", False) for r in rows]),
        "domain_grouping_f1": None, "automated_joint_accuracy": None, "automated_joint_coverage": 0.0,
    }


def evaluate(root, name):
    databases = verify_inputs(root)
    if configuration(root) != read(root / "protocol.json"):
        raise ValueError("Frozen platform configuration changed.")
    runner, mapping = {"metacrafter": (run_meta, META_TYPES), "datahub": (run_datahub, DATAHUB_TYPES)}[name]
    out = root / name
    out.mkdir(exist_ok=False)
    reports = {}
    # The native tools have access only to database connections and their upstream settings.
    for database in databases:
        report = runner(root, database)
        reports[database] = report
        save(out / (database + ".json"), report)
        print(name, database, len(report["fields"]), round(report["seconds"], 2), flush=True)
    verify_inputs(root)
    supported = set(mapping.values()) | {"record_id", "reference_id"}
    result, pooled = {}, []
    for database, report in reports.items():
        rows = field_results(root, database, report["fields"])
        pooled.extend(rows)
        result[database] = {**summarize(rows, supported), "seconds": report["seconds"]}
    save(out / "fields_with_truth.json", pooled)
    save(out / "metrics.json", {"overall": summarize(pooled, supported), "by_database": result,
                                  "seconds": sum(report["seconds"] for report in reports.values())})


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("freeze", "metacrafter", "datahub"))
    parser.add_argument("--root", type=Path, default=ROOT)
    args = parser.parse_args()
    if args.action == "freeze":
        verify_inputs(args.root)
        target = args.root / "protocol.json"
        if target.exists():
            raise FileExistsError(target)
        save(target, configuration(args.root))
    else:
        evaluate(args.root, args.action)
