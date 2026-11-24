import argparse
from collections import Counter
from pathlib import Path

from evaluation.fixtures import digest, write_json
from evaluation.score import accuracy, binary, phase3, ratio, read, rows_for, summarize

PARENTS = {
    "customer": "people", "workforce": "people",
    "catalog": "commercial", "commerce": "commercial",
    "finance": "financial", "insurance": "financial",
    "support": "delivery", "hospitality": "delivery",
    "operations": "operations", "logistics": "operations",
    "healthcare": "health", "education": "learning", "unknown": "unresolved",
}
IDS = {"record_id", "reference_id", "saudi_national_id", "saudi_residency_id", "identifier",
       "business_identifier", "service_code", "tracking_code", "policy_number", "reservation_code"}


def broad(kind):
    from evaluation.score import category
    return "identifier" if kind in IDS else category(kind)


def measured(rows):
    stats = summarize(rows)
    high = [row for row in rows if row["confidence"] >= .85]
    business = [row for row in rows if row["semantic_true"] in IDS and row["personal_true"] == "no"
                and row["semantic_true"] not in {"record_id", "reference_id"}]
    stats.update({
        "common_category_accuracy": accuracy([(broad(row["semantic_true"]), broad(row["semantic_pred"]))
                                              for row in rows]),
        "hierarchical_domain_accuracy": accuracy([(PARENTS.get(row["domain_true"], "unresolved"),
                                                    PARENTS.get(row["domain_pred"], "unresolved"))
                                                   for row in rows]),
        "automated_coverage": ratio(sum(not row["review_required"] for row in rows), len(rows)),
        "high_confidence_strict_error": {"count": sum(row["semantic_true"] != row["semantic_pred"] for row in high),
                                         "denominator": len(high),
                                         "rate": ratio(sum(row["semantic_true"] != row["semantic_pred"]
                                                           for row in high), len(high))},
        "business_identifier_false_positives": {
            "eligible": len(business), "personal_yes": sum(row["personal_pred"] == "yes" for row in business),
            "saudi_identity_predictions": sum(row["semantic_pred"] in {"saudi_national_id", "saudi_residency_id"}
                                             for row in business),
            "rows": [row for row in business if row["personal_pred"] == "yes" or
                     row["semantic_pred"] in {"saudi_national_id", "saudi_residency_id"}]},
    })
    return stats


def comparison(root, folders, names, label_paths, output, manifest=None):
    report = {"scope": "final_unseen_holdout" if manifest else "original_demo_and_development_diagnostics",
              "versions": {}, "domain_mapping": PARENTS}
    expected = read(manifest)["files"] if manifest else {}
    if manifest:
        for name, sha in expected.items():
            if digest(root / name) != sha:
                raise ValueError(f"Holdout seal mismatch for {name}")
    for version, folder in folders.items():
        pooled, by_sector, phases = [], {}, {}
        provenance = read(folder / "provenance.json") if (folder / "provenance.json").exists() else {}
        for name, path in zip(names, label_paths):
            source = read(folder / (name + ".json"))
            if manifest and provenance["databases"][name] != expected[f"databases/{name}.sqlite"]:
                raise ValueError(f"Inference consumed a different {name} database")
            rows = rows_for(name, read(path), source["hybrid"])
            by_sector[name] = measured(rows)
            pooled.extend(rows)
            phases[name] = {**phase3(source), "seconds": source.get("seconds")}
        report["versions"][version] = {
            "by_sector": by_sector, "combined": measured(pooled), "phase3": phases,
            "provenance": provenance,
        }
    write_json(output, report)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--final", action="store_true")
    args = parser.parse_args()
    root = Path("data/reliability")
    if args.final:
        holdout = root / "final"
        names = ("logistics", "insurance", "hospitality")
        comparison(holdout, {name: root / ("final_" + name) for name in ("original", "improved")},
                   names, [holdout / "labels" / (name + ".json") for name in names],
                   root / "final_metrics.json", holdout / "manifest.json")
    else:
        names = ("synthetic", "healthcare", "ecommerce", "education")
        comparison(root, {"original": Path("data/generalization/predictions"), "improved": root / "dev_final"},
                   names, [Path("data/ground_truth.json"), *[Path("data/generalization/labels") / (name + ".json")
                                                              for name in names[1:]]],
                   root / "diagnostic_metrics.json")
