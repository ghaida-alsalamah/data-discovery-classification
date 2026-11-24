"""Run three classifier variants locally. This runner never reads labels."""
import argparse
from collections import Counter
from pathlib import Path
from time import perf_counter

from evaluation.metacrafter_setup import use_dependency
from evaluation.reliability_infer import digest, fingerprint, write


def run(output, paths, verifier):
    use_dependency()
    from backend.app.classification.ai_evidence import DEFAULT_MODEL_PATH, PresidioEvidence, SemanticEvidence
    from backend.app.classification.engine import HybridClassifier
    from backend.app.connectors.sqlite import InformationAsset, SQLiteConnector
    from backend.app.discovery.schema import discover
    from backend.app.intelligence.service import analyze
    from backend.app.profiling.columns import profile_database
    from evaluation.metacrafter_adapter import Adapter
    from metacrafter.config import ConfigLoader

    if ConfigLoader.get_config_file_path():
        raise RuntimeError("Run in an environment without external .metacrafter configuration.")
    output.mkdir(parents=True, exist_ok=False)
    adapter = Adapter(Path("evaluation/metacrafter_rules"), verifier)
    model = HybridClassifier(SemanticEvidence(DEFAULT_MODEL_PATH))
    detector = PresidioEvidence()
    for path in paths:
        started = perf_counter()
        with SQLiteConnector(path, InformationAsset(path.stem, "Synthetic comparison", "Evaluation")).connect() as con:
            schema, links = discover(con)
            profiles = profile_database(con, schema, 500, detector)
            profiled = perf_counter()
            current = model.classify(schema, profiles)
            classified = perf_counter()
            by_table = {(row["table_name"], row["column_name"]): row for row in current}
            native, hybrid, statuses = [], [], Counter()
            for table in schema["tables"]:
                name = table["name"]
                expected = {col["name"]: by_table[name, col["name"]] for col in table["columns"]}
                plain, combined, status = adapter.scan(con, table, profiles[name], expected)
                native.extend(plain)
                hybrid.extend(combined)
                statuses[status] += 1
            scanned = perf_counter()
            variants = {}
            for name, predictions in (("current", current), ("metacrafter", native), ("hybrid", hybrid)):
                domains, quality, opportunities = analyze(con, schema, links, profiles, predictions, use_environment=False)
                variants[name] = {"hybrid": predictions, "schema": schema, "domains": domains,
                                  "quality": quality, "opportunities": opportunities}
        write(output / (path.stem + ".json"), {
            "variants": variants, "verifier_status": dict(statuses),
            "seconds": {"local_profiling": profiled - started, "current_classification": classified - profiled,
                        "metacrafter_native_and_hybrid_scan": scanned - classified},
        })
        print(path.stem, dict(statuses), flush=True)
    write(output / "provenance.json", {
        "backend": fingerprint(Path(".")), "database_sha256": {path.stem: digest(path) for path in paths},
        "metacrafter": adapter.metadata, "sample_limit": 500, "verifier_requested": verifier,
        "adapter_sha256": digest(Path("evaluation/metacrafter_adapter.py")),
        "rule_sha256": digest(Path("evaluation/metacrafter_rules/saudi.yaml")),
    })


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("output", type=Path)
    parser.add_argument("databases", type=Path, nargs="+")
    parser.add_argument("--verify", action="store_true")
    args = parser.parse_args()
    run(args.output, args.databases, args.verify)
