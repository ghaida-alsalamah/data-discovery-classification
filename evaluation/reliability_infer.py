"""Comparable inference runner for the current or an archived engine tree."""
import argparse
import hashlib
import json
import sys
from dataclasses import asdict
from pathlib import Path
from time import perf_counter


def digest(path):
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def fingerprint(tree):
    return {path.relative_to(tree).as_posix(): digest(path)
            for path in sorted((tree / "backend").rglob("*.py"))}


def write(path, value):
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False) + "\n", encoding="utf-8")


def run(tree, output, inputs, seal):
    tree = tree.resolve()
    files = fingerprint(tree)
    if seal and files != json.loads(seal.read_text(encoding="utf-8")):
        raise ValueError("Engine sources differ from the sealed version.")
    sys.path.insert(0, str(tree))
    from backend.app.classification.ai_evidence import MODEL_ID, PresidioEvidence, SemanticEvidence
    from backend.app.classification.engine import HybridClassifier, ReviewThresholds
    from backend.app.connectors.sqlite import InformationAsset, SQLiteConnector
    from backend.app.discovery.schema import discover
    from backend.app.intelligence.service import analyze
    from backend.app.profiling.columns import profile_database

    output.mkdir(parents=True, exist_ok=False)
    started = perf_counter()
    model = Path(".models/minilm").resolve()
    classifier = HybridClassifier(SemanticEvidence(model), ReviewThresholds())
    presidio = PresidioEvidence()
    initialization = perf_counter() - started
    for path in inputs:
        started = perf_counter()
        with SQLiteConnector(path, InformationAsset(path.stem, "Synthetic reliability evaluation", "Evaluation")).connect() as con:
            schema, links = discover(con)
            profiles = profile_database(con, schema, 500, presidio)
            profiled = perf_counter()
            predictions = classifier.classify(schema, profiles)
            classified = perf_counter()
            domains, quality, opportunities = analyze(con, schema, links, profiles, predictions, use_environment=False)
        write(output / (path.stem + ".json"), {
            "schema": schema, "relationships": links, "hybrid": predictions, "domains": domains,
            "quality": quality, "opportunities": opportunities, "seconds": {
                "discovery_and_profiling": profiled - started,
                "classification": classified - profiled, "phase3": perf_counter() - classified,
            },
        })
    if files != fingerprint(tree):
        raise ValueError("Engine sources changed during inference.")
    write(output / "provenance.json", {
        "engine_files": files, "thresholds": asdict(classifier.thresholds), "sample_limit": 500,
        "model": MODEL_ID, "model_files": {name: digest(model / name) for name in ("onnx/model.onnx", "tokenizer.json")},
        "databases": {path.stem: digest(path) for path in inputs}, "initialization_seconds": initialization,
        "phase3_llm": False,
    })


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("tree", type=Path)
    parser.add_argument("output", type=Path)
    parser.add_argument("databases", type=Path, nargs="+")
    parser.add_argument("--seal", type=Path)
    args = parser.parse_args()
    run(args.tree, args.output, args.databases, args.seal)
