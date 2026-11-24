"""Frozen inference accepts SQLite paths and has no labels input."""
import argparse
import hashlib
import json
import subprocess
from dataclasses import asdict
from importlib.metadata import version
from pathlib import Path

from backend.app.classification.ai_evidence import DEFAULT_MODEL_PATH, MODEL_ID, PresidioEvidence, SemanticEvidence
from backend.app.classification.engine import HybridClassifier, ReviewThresholds, name_only_baseline
from backend.app.connectors.sqlite import InformationAsset, SQLiteConnector
from backend.app.discovery.schema import discover
from backend.app.intelligence.service import analyze
from backend.app.profiling.columns import profile_database

REVISION = "dd58a8cbc040792aaa5d0d7eeb4c76d0b8e2c71c"


def digest(path):
    with path.open("rb") as source:
        return hashlib.file_digest(source, "sha256").hexdigest()


def write(path, payload):
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False, allow_nan=False) + "\n",
                    encoding="utf-8")


def run(output, inputs):
    head = subprocess.check_output(["git", "rev-parse", "HEAD"], text=True).strip()
    subprocess.run(["git", "diff", "--exit-code", REVISION, "--", "backend", "scripts"],
                   check=True, capture_output=True)
    output.mkdir(parents=True, exist_ok=False)
    thresholds = ReviewThresholds()
    semantic = SemanticEvidence(DEFAULT_MODEL_PATH)
    detector = PresidioEvidence()
    hybrid = HybridClassifier(semantic, thresholds)
    for path in inputs:
        connector = SQLiteConnector(path, InformationAsset(path.stem, "Synthetic holdout", "Evaluation"))
        with connector.connect() as connection:
            schema, relationships = discover(connection)
            profiles = profile_database(connection, schema, 500, detector)
            predictions = hybrid.classify(schema, profiles)
            domains, quality, opportunities = analyze(connection, schema, relationships, profiles,
                                                      predictions, use_environment=False)
        write(output / (path.stem + ".json"), {
            "schema": schema, "relationships": relationships,
            "hybrid": predictions, "baseline": name_only_baseline(schema),
            "domains": domains, "quality": quality, "opportunities": opportunities,
        })
    write(output / "provenance.json", {
        "frozen_revision": REVISION, "executed_head": head, "thresholds": asdict(thresholds),
        "sampling_limit": 500, "presidio": True, "embedding_model": MODEL_ID,
        "model_files_sha256": {name: digest(DEFAULT_MODEL_PATH / name)
                               for name in ("onnx/model.onnx", "tokenizer.json")},
        "dependencies": {pkg: version(pkg) for pkg in (
            "onnxruntime", "presidio-analyzer", "spacy", "tokenizers", "numpy", "SQLAlchemy")},
        "databases_sha256": {path.name: digest(path) for path in inputs},
        "phase3_llm": False,
    })


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("output", type=Path)
    parser.add_argument("databases", type=Path, nargs="+")
    args = parser.parse_args()
    run(args.output, args.databases)
