import argparse
import json
from pathlib import Path
from time import perf_counter

from backend.app.classification.engine import name_only_baseline
from backend.app.classification.taxonomy import TYPES
from scripts.run_pipeline import write_json


def category(kind):
    return TYPES[kind].category if kind in TYPES else kind


def ratio(numerator, denominator):
    return numerator / denominator if denominator else None


def evaluate_predictions(truth, predictions):
    expected = {(table, name): label for table, columns in truth.items() for name, label in columns.items()}
    actual = {(row["table_name"], row["column_name"]): row for row in predictions}
    if expected.keys() != actual.keys() or len(actual) != len(predictions):
        raise ValueError("Predictions must cover exactly the labeled columns, once each.")

    def semantic_accuracy(keys):
        return {
            "columns": len(keys),
            "exact": ratio(sum(expected[key]["semantic_type"] == actual[key]["semantic_type"]
                               for key in keys), len(keys)),
            "category": ratio(sum(category(expected[key]["semantic_type"]) ==
                                  category(actual[key]["semantic_type"]) for key in keys), len(keys)),
        }

    positive = {key for key, label in expected.items() if label["personal_data"]}
    predicted_positive = {key for key, row in actual.items() if row["personal_data"] == "yes"}
    tp = len(positive & predicted_positive)
    misses = sorted(positive - predicted_positive)
    return {
        "semantic_accuracy": semantic_accuracy(expected.keys()),
        "domain_accuracy": ratio(sum(label["domain"] == actual[key]["data_domain"]
                                     for key, label in expected.items()), len(expected)),
        "personal_data": {
            "precision": ratio(tp, len(predicted_positive)),
            "recall": ratio(tp, len(positive)),
            "f1": ratio(2 * tp, len(positive) + len(predicted_positive)),
            "true_positives": tp,
            "false_positives": len(predicted_positive - positive),
            "false_negative_count": len(misses),
            "false_negatives": [{"table_name": table, "column_name": name,
                                 "predicted_status": actual[table, name]["personal_data"]}
                                for table, name in misses],
        },
        "difficult_names": {
            label: semantic_accuracy([key for key, item in expected.items()
                                      if item.get("column_name_quality") in qualities])
            for label, qualities in {
                "ambiguous": {"ambiguous"}, "misleading": {"misleading"},
                "combined": {"ambiguous", "misleading"},
            }.items()
        },
        "unknown_rate": ratio(sum(row["semantic_type"] == "unknown" for row in predictions), len(actual)),
        "human_review_rate": ratio(sum(row["review_required"] for row in predictions), len(actual)),
    }


def run(directory):
    def load(name):
        return json.loads((directory / f"{name}.json").read_text(encoding="utf-8"))

    truth = load("ground_truth")
    schema = load("schema")
    hybrid = load("classifications")
    started = perf_counter()
    baseline = name_only_baseline(schema)
    baseline_time = perf_counter() - started
    report = {
        "methodology": {
            "baseline": "Taxonomy alias matching on column names alone.",
            "personal_positive": "Only yes counts as positive. Uncertain on a personal column is a false negative.",
            "timing": "Baseline inference only. Hybrid reports inference, profiling, initialization and total separately.",
        },
        "baseline": {**evaluate_predictions(truth, baseline), "execution_seconds": baseline_time},
        "hybrid": {**evaluate_predictions(truth, hybrid["columns"]),
                   "execution_seconds": hybrid["timings_seconds"]["classification"],
                   "pipeline_timings_seconds": hybrid["timings_seconds"],
                   "components": hybrid["components"]},
    }
    write_json(directory / "evaluation.json", report)
    return report


def main():
    parser = argparse.ArgumentParser(description="Evaluate saved classification predictions.")
    parser.add_argument("--data-dir", type=Path, default=Path("data"))
    run(parser.parse_args().data_dir)


if __name__ == "__main__":
    main()
