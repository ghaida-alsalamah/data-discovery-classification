"""Keep native model coverage and direct-PPI/linkage scores separate."""
import argparse
from collections import Counter
from pathlib import Path

from backend.app.classification.pretrained import DIRECT_NATIVE, DODUO_MAP, PII_LABELS
from evaluation.reliability_infer import digest, fingerprint
from evaluation.reliability_score import measured
from evaluation.score import accuracy, binary, category, ratio, read, rows_for
from scripts.scan_data_asset import write_report

ROOT = Path("data/upstream")
FILES = (Path("evaluation/upstream_compare.py"), Path("evaluation/upstream_score.py"),
         Path("evaluation/upstream_holdout.py"), Path("scripts/scan_data_asset.py"),
         Path("scripts/upstream_openmetadata.py"), Path("evaluation/UPSTREAM_SCORING.md"))


def seal():
    return {"backend": fingerprint(Path(".")),
            "evaluation": {file.as_posix(): digest(file) for file in FILES if file.is_file()}
            }


def summarize_native(native_rows):
    # None is an abstention or a type outside the predefined crosswalk.
    doduo = [(tag["semantic_type"], row["doduo_mapped"], row["doduo"][0]["type"] if row["doduo"] else "abstain")
              for tag, row in native_rows]
    covered = [(actual, predicted, native) for actual, predicted, native in doduo
               if actual in DODUO_MAP.values()]
    native_accuracy = accuracy([(a, p) for a, p, _ in doduo])
    broader = accuracy([(category(a), "duration" if native == "duration" else category(p))
                        for a, p, native in doduo])
    return {
        "fields_inferred": sum(native != "abstain" for _, _, native in doduo),
        "total_fields": len(doduo), "overall_exact_accuracy": native_accuracy,
        "broader_accuracy": broader,
        "supported_truth_fields": len(covered),
        "supported_truth_exact_accuracy": accuracy([(a, p) for a, p, _ in covered]),
        "unsupported_truth_counts": dict(Counter(a for a, _, _ in doduo if a not in DODUO_MAP.values())),
        "unsupported_prediction_counts": dict(Counter(n for _, p, n in doduo if p is None)),
        "native_prediction_counts": dict(Counter(n for _, _, n in doduo)),
    }


def direct_truth(label):
    if "personal_linkage" in label:
        return label["personal_linkage"]
    personal = label["personal_data"]
    if personal == "uncertain":
        return "uncertain"
    if personal in ("yes", True):
        return "direct" if label["semantic_type"] in DIRECT_NATIVE else "linked"
    return "none"


def direct_report(entries, mode):
    judged = [(label, row, native) for label, row, native in entries if direct_truth(label) != "uncertain"]
    if mode == "pii_native":
        predict = lambda row, native: set(native["pii"]["native_majority"])
    elif mode == "openmetadata":
        predict = lambda row, native: set(native["openmetadata"]["native_tags"])
    else:
        predict = lambda row, native: {row["direct_pii_type"]} if row.get("direct_pii_type") else set()
    assigned = [(label, row, predict(row, native)) for label, row, native in judged]
    observed = binary([(direct_truth(label) == "direct", bool(pred)) for label, _, pred in assigned])
    typed = [(DIRECT_NATIVE.get(label["semantic_type"]), pred)
             for label, _, pred in assigned if direct_truth(label) == "direct"]
    observed.update({
        "excluded_uncertain_truth": len(entries) - len(judged),
        "typed_recall": ratio(sum(expected in labels for expected, labels in typed), len(typed))
            if mode != "openmetadata" else None,
        "predicted_native_labels": dict(Counter(key for _, _, pred in assigned for key in pred)),
        "false_positive_fields": [
            {"table": row["table_name"], "column": row["column_name"], "truth": direct_truth(label),
             "native_labels": sorted(pred)} for label, row, pred in assigned
            if direct_truth(label) != "direct" and pred
        ],
    })
    return observed


def evaluate(out, labels, scope):
    reports = {}
    for mode in ("current", "pii", "doduo", "openmetadata", "upstream"):
        folder = out / mode
        if not (folder / "provenance.json").is_file():
            continue
        provenance = read(folder / "provenance.json")
        by_database, combined, native, all_entries = {}, [], [], []
        seconds = Counter()
        for label_path in labels:
            if scope == "fresh":
                truth_hash = read(ROOT / "fresh/manifest.json")["files"]
                if digest(label_path) != truth_hash[f"labels/{label_path.name}"]:
                    raise ValueError("Fresh labels were changed.")
                if provenance["input_sha256"][label_path.stem + ".sqlite"] != truth_hash[
                    f"databases/{label_path.stem}.sqlite"]:
                    raise ValueError("Different fixture used for inference.")
                if provenance["backend"] != read(ROOT / "seal.json")["backend"]:
                    raise ValueError("Fresh predictions did not use the sealed backend.")
            truth = read(label_path)
            result = read(folder / label_path.name)
            rows = rows_for(label_path.stem, truth, result["classifications"])
            by_database[label_path.stem] = measured(rows)
            combined.extend(rows)
            seconds.update(result["timing_seconds"])
            for row in result["classifications"]:
                key, column = row["table_name"], row["column_name"]
                tag, raw = truth[key][column], result["native_predictions"][key][column]
                native.append((tag, raw))
                all_entries.append((tag, row, raw))
        result = {
            "sectors": by_database, "combined": measured(combined), "timing_seconds": dict(seconds),
            "direct_pii": direct_report(all_entries, mode),
        }
        if mode in ("doduo", "upstream"):
            result["native_semantics"] = summarize_native(native)
        if mode in ("pii", "upstream"):
            result["native_pii_engineer"] = direct_report(all_entries, "pii_native")
        reports[mode] = result
    write_report(out / "metrics.json", {"scope": scope, "engines": reports})


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    group = parser.add_mutually_exclusive_group()
    group.add_argument("--seal", action="store_true")
    group.add_argument("--fresh", action="store_true")
    args = parser.parse_args()
    if args.seal:
        target = ROOT / "seal.json"
        if target.exists():
            raise ValueError("Already sealed.")
        write_report(target, seal())
    elif args.fresh:
        manifest = read(ROOT / "fresh/manifest.json")
        if digest(ROOT / "seal.json") != manifest["seal_sha256"] or read(ROOT / "seal.json") != seal():
            raise ValueError("Frozen configuration changed.")
        evaluate(ROOT / "final", sorted((ROOT / "fresh/labels").glob("*.json")), "fresh")
    else:
        # The demo uses a different filename from prediction outputs, so score the nine prior sectors here.
        labels = [path for root in ("data/generalization/labels", "data/reliability/final/labels",
                                    "data/metacrafter/fresh/labels") for path in sorted(Path(root).glob("*.json"))]
        evaluate(ROOT / "development", labels, "development")
