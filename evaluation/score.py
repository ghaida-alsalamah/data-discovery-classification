"""Read labels after inference, verify fixture integrity, and report benchmark metrics."""
import argparse
import json
from collections import Counter, defaultdict
from pathlib import Path
from statistics import mean, median

from backend.app.classification.taxonomy import DOMAINS, TYPES
from evaluation.fixtures import digest, write_json


def read(path):
    return json.loads(path.read_text(encoding="utf-8"))


def ratio(num, den):
    return num / den if den else None


def category(kind):
    return TYPES[kind].category if kind in TYPES else "unknown"


def domain(kind):
    return kind if kind in DOMAINS else "unknown"


def accuracy(pairs):
    return ratio(sum(a == b for a, b in pairs), len(pairs))


def matrix(pairs):
    rows = defaultdict(Counter)
    for expected, predicted in pairs:
        rows[expected][predicted] += 1
    return {key: dict(sorted(counts.items())) for key, counts in sorted(rows.items())}


def binary(pairs):
    counts = Counter(pairs)
    tp, fp, fn, tn = (counts[key] for key in ((True, True), (False, True), (True, False), (False, False)))
    return {"tp": tp, "fp": fp, "fn": fn, "tn": tn, "precision": ratio(tp, tp + fp),
            "recall": ratio(tp, tp + fn), "f1": ratio(2 * tp, 2 * tp + fp + fn)}


def rows_for(sector, truth, predictions):
    expected = {(table, name): label for table, columns in truth.items() for name, label in columns.items()}
    actual = {(row["table_name"], row["column_name"]): row for row in predictions}
    if expected.keys() != actual.keys() or len(actual) != len(predictions):
        raise ValueError(f"Nonidentical label/prediction coverage for {sector}")
    rows = []
    for key, label in expected.items():
        row = actual[key]
        personal = label["personal_data"]
        if isinstance(personal, bool):
            personal = "yes" if personal else "no"
        rows.append({
            "sector": sector, "table": key[0], "column": key[1],
            "semantic_true": label["semantic_type"], "semantic_pred": row["semantic_type"],
            "domain_true": label["domain"], "domain_pred": row["data_domain"],
            "personal_true": personal, "personal_pred": row["personal_data"],
            "difficulty": label.get("difficulty", label.get("column_name_quality", "clear")),
            "review_required": row["review_required"], "confidence": row.get("confidence"),
            "sources": sorted({item["source"] for item in row.get("supporting_evidence", ())}),
        })
    return rows


def semantic_ok(row):
    expected = row["semantic_true"]
    return (expected if expected in TYPES else "unknown") == row["semantic_pred"]


def failures(row):
    return ([dim for dim, ok in (
        ("semantic", semantic_ok(row)),
        ("domain", domain(row["domain_true"]) == row["domain_pred"]),
        ("personal", row["personal_true"] == "uncertain" or row["personal_true"] == row["personal_pred"]),
    ) if not ok])


def summarize(rows):
    strict = [(r["semantic_true"], r["semantic_pred"]) for r in rows]
    opened = [(a if a in TYPES else "unknown", b) for a, b in strict]
    broad = [(category(a), category(b)) for a, b in strict]
    in_taxonomy = [(a, b) for a, b in strict if a in TYPES and a != "unknown"]
    domains = [(r["domain_true"], r["domain_pred"]) for r in rows]
    open_domains = [(domain(a), b) for a, b in domains]
    personal = [(r["personal_true"], r["personal_pred"]) for r in rows if r["personal_true"] != "uncertain"]
    review = [r for r in rows if not r["review_required"]]
    labels = sorted({kind for pair in strict for kind in pair})
    difficult = {}
    for group, subset in (("ambiguous", {"ambiguous"}), ("misleading", {"misleading"}),
                          ("combined", {"ambiguous", "misleading"})):
        selected = [r for r in rows if r["difficulty"] in subset]
        difficult[group] = {
            "count": len(selected), "open_set_accuracy": ratio(sum(map(semantic_ok, selected)), len(selected)),
            "strict_accuracy": accuracy([(r["semantic_true"], r["semantic_pred"]) for r in selected]),
        }
    odds = {
        "fields": len(rows), "strict_exact_accuracy": accuracy(strict),
        "open_set_exact_accuracy": accuracy(opened), "supported_known_exact_accuracy": accuracy(in_taxonomy),
        "broader_accuracy": accuracy(broad),
        "supported_known_broader_accuracy": accuracy([(category(a), category(b)) for a, b in in_taxonomy]),
        "strict_domain_accuracy": accuracy(domains), "open_set_domain_accuracy": accuracy(open_domains),
        "personal": {**binary([(a == "yes", b == "yes") for a, b in personal]),
                     "excluded_uncertain_truth": len(rows) - len(personal),
                     "uncertain_predictions_on_known_truth": sum(b == "uncertain" for _, b in personal),
                     "false_negatives": [r for r in rows if r["personal_true"] == "yes" and r["personal_pred"] != "yes"],
                     "false_positives": [r for r in rows if r["personal_true"] == "no" and r["personal_pred"] == "yes"]},
        "unknown": {**binary([(a == "unknown", b == "unknown") for a, b in opened]),
                    "truth_native_unknown": sum(a == "unknown" for a, _ in strict),
                    "native_unknown_recall": ratio(sum(a == b == "unknown" for a, b in strict),
                                                  sum(a == "unknown" for a, _ in strict)),
                    "truth_unsupported": sum(a not in TYPES for a, _ in strict),
                    "unsupported_abstention_rate": ratio(sum(a not in TYPES and b == "unknown" for a, b in strict),
                                                         sum(a not in TYPES for a, _ in strict)),
                    "prediction_rate": ratio(sum(b == "unknown" for _, b in strict), len(rows))},
        "difficult_names": difficult,
        "review_rate": ratio(len(rows) - len(review), len(rows)),
        "unreviewed_fields": len(review),
        "unreviewed_semantic_accuracy": ratio(sum(map(semantic_ok, review)), len(review)),
        "unreviewed_strict_semantic_accuracy": accuracy([(r["semantic_true"], r["semantic_pred"]) for r in review]),
        "unreviewed_joint_accuracy": ratio(sum(not failures(r) for r in review), len(review)),
        "unreviewed_errors": [{**r, "wrong_dimensions": failures(r)} for r in review if failures(r)],
        "confusions": {"semantic_strict": matrix(strict), "semantic_open": matrix(opened),
                       "category": matrix(broad), "domain": matrix(domains), "personal": matrix(personal)},
        "per_class": {kind: {"support": sum(a == kind for a, _ in strict), **binary(
            [(a == kind, b == kind) for a, b in strict])} for kind in labels},
    }
    scored = [r for r in rows if r["confidence"] is not None]
    if scored:
        bins = []
        bounds = (0, .4, .6, .7, .85, 1)
        for low, high in zip(bounds, bounds[1:]):
            selected = [r for r in scored if low <= r["confidence"] < high or high == 1 == r["confidence"]]
            bins.append({"interval": [low, high], "fields": len(selected),
                         "open_accuracy": ratio(sum(map(semantic_ok, selected)), len(selected)),
                         "strict_accuracy": accuracy([(r["semantic_true"], r["semantic_pred"]) for r in selected])})
        correct = [r["confidence"] for r in scored if semantic_ok(r)]
        incorrect = [r["confidence"] for r in scored if not semantic_ok(r)]
        odds["confidence"] = {
            "bins": bins, "correct_mean": mean(correct) if correct else None,
            "incorrect_mean": mean(incorrect) if incorrect else None,
            "correct_median": median(correct) if correct else None,
            "incorrect_median": median(incorrect) if incorrect else None,
            "confident_semantic_errors": [r for r in scored if r["confidence"] >= .85 and not semantic_ok(r)],
            "confident_unreviewed_errors": [{**r, "wrong_dimensions": failures(r)} for r in scored
                                            if r["confidence"] >= .85 and not r["review_required"] and failures(r)],
        }
    return odds


def phase3(result):
    opportunities = result["opportunities"]
    return {
        "domains": {row["domain_name"]: sum(len(table["columns"]) for table in row["included_tables"])
                    for row in result["domains"]["domains"]},
        "mixed_predicted_domain_tables": sorted(table["name"] for table in result["schema"]["tables"]
            if len({row["data_domain"] for row in result["hybrid"] if row["table_name"] == table["name"]}) > 1),
        "quality_issues": dict(Counter(row["code"] for row in result["quality"]["issues"])),
        "relationship_checks": result["quality"]["relationships"],
        "readiness": opportunities["readiness_counts"],
        "opportunities": {row["template_id"]: {
            "readiness": row["readiness_status"], "missing_prerequisites": row["missing_prerequisites"],
            "required_relationships": row["required_relationships"],
            "quality_limitations": row["data_quality_limitations"],
            "required_fields": row["required_fields"],
        } for row in opportunities["opportunities"]},
        "ready_with_missing_prerequisites": [row["template_id"] for row in opportunities["opportunities"]
              if row["readiness_status"] == "Ready for technical analysis" and row["missing_prerequisites"]],
        "ready_with_unverified_relations": [row["template_id"] for row in opportunities["opportunities"]
              if row["readiness_status"] == "Ready for technical analysis" and any(
                  result["quality"]["relationships"].get(key, {}).get("status") != "passed"
                  for key in row["required_relationships"])],
    }


def run(root, original_labels):
    manifest = read(root / "fixture_manifest.json")
    for name, expected in manifest["files"].items():
        if digest(root / name) != expected:
            raise ValueError(f"Sealed fixture changed: {name}")
    predictions = root / "predictions"
    provenance = read(predictions / "provenance.json")
    for name, expected in provenance["databases_sha256"].items():
        if name != "synthetic.sqlite" and manifest["files"]["databases/" + name] != expected:
            raise ValueError(f"Inference used a different input: {name}")
    report = {
        "methodology": {
            "strict": "Literal match; unsupported truth remains a miss even if the engine abstains.",
            "open_set": "Unsupported semantics and domains map to unknown for separate open-set metrics.",
            "personal": "Uncertain truth excluded. Only yes predicts positive; uncertain on true yes is a false negative.",
            "joint": "Open-set semantic and domain accuracy plus exact known personal status. Uncertain personal truth is skipped.",
            "confidence": "Heuristic semantic score. Open-set accuracy uses bins lower-inclusive and upper-exclusive except 1.0.",
        },
        "provenance": provenance, "original_label_sha256": digest(original_labels),
        "benchmarks": {}, "phase3": {},
    }
    pooled = defaultdict(list)
    for sector in ("synthetic", "healthcare", "ecommerce", "education"):
        truth = read(original_labels if sector == "synthetic" else root / "labels" / (sector + ".json"))
        result = read(predictions / (sector + ".json"))
        report["benchmarks"][sector] = {}
        for engine in ("baseline", "hybrid"):
            rows = rows_for(sector, truth, result[engine])
            report["benchmarks"][sector][engine] = summarize(rows)
            if sector != "synthetic":
                pooled[engine].extend(rows)
        if sector != "synthetic":
            report["phase3"][sector] = phase3(result)
    report["benchmarks"]["combined_holdout"] = {key: summarize(rows) for key, rows in pooled.items()}
    for variant in ("ecommerce_stress", "ecommerce_unlinked"):
        report["phase3"][variant] = phase3(read(predictions / (variant + ".json")))
    write_json(root / "metrics.json", report)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("fixture_root", type=Path)
    parser.add_argument("original_labels", type=Path)
    args = parser.parse_args()
    run(args.fixture_root, args.original_labels)
