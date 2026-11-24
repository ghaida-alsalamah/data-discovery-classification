import argparse
import json
from dataclasses import asdict
from pathlib import Path
from time import perf_counter

from backend.app.classification.ai_evidence import (
    DEFAULT_MODEL_PATH, MODEL_ID, PresidioEvidence, SemanticEvidence,
)
from backend.app.classification.engine import HybridClassifier, ReviewThresholds
from backend.app.connectors.sqlite import InformationAsset, SQLiteConnector
from backend.app.discovery.schema import discover
from backend.app.models.synthetic import generate_database
from backend.app.profiling.columns import profile_database


def write_json(path, payload):
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False, allow_nan=False) + "\n",
                    encoding="utf-8")


def run(output_dir: Path, sample_size=500, *, phase_one_only=False,
        model_path=DEFAULT_MODEL_PATH, thresholds=None):
    started = perf_counter()
    presidio = None if phase_one_only else PresidioEvidence()
    semantic = SemanticEvidence(model_path) if not phase_one_only and model_path is not None else None
    classifier = HybridClassifier(semantic=semantic, thresholds=thresholds)
    initialized = perf_counter()
    database = output_dir / "synthetic.sqlite"
    generate_database(database, output_dir / "ground_truth.json")
    asset = InformationAsset("Synthetic digital services", "Fictional Saudi services data", "Demo")
    scanning = perf_counter()
    with SQLiteConnector(database, asset).connect() as connection:
        schema, relationships = discover(connection)
        profiles = profile_database(connection, schema, sample_size, presidio)
        schema["asset"] = asdict(asset)
    profiled = perf_counter()

    if not phase_one_only:
        predictions = classifier.classify(schema, profiles)
        classified = perf_counter()
        write_json(output_dir / "classifications.json", {
            "components": {"presidio": True, "semantic_model": MODEL_ID if semantic else None,
                           "semantic_runtime": "onnxruntime_cpu" if semantic else None},
            "thresholds": asdict(classifier.thresholds),
            "timings_seconds": {
                "initialization": initialized - started,
                "discovery_and_profiling": profiled - scanning,
                "classification": classified - profiled,
                "total_through_classification": classified - started,
            },
            "columns": predictions,
        })

    for name, payload in (("schema", schema), ("relationships", relationships), ("profiles", profiles)):
        write_json(output_dir / f"{name}.json", payload)


def main():
    parser = argparse.ArgumentParser(description="Generate, discover, profile and classify a synthetic database.")
    parser.add_argument("--output-dir", type=Path, default=Path("data"))
    parser.add_argument("--sample-size", type=int, default=500)
    parser.add_argument("--model-path", type=Path, default=DEFAULT_MODEL_PATH, help="Local MiniLM model directory")
    parser.add_argument("--without-embeddings", action="store_true", help="Explicitly disable embedding evidence")
    parser.add_argument("--review-confidence", type=float, default=0.70)
    parser.add_argument("--review-margin", type=float, default=0.14)
    args = parser.parse_args()
    if args.sample_size < 1:
        parser.error("--sample-size must be positive")
    try:
        thresholds = ReviewThresholds(minimum_confidence=args.review_confidence,
                                      minimum_margin=args.review_margin)
    except ValueError as error:
        parser.error(str(error))
    run(args.output_dir, args.sample_size,
        model_path=None if args.without_embeddings else args.model_path, thresholds=thresholds)


if __name__ == "__main__":
    main()
