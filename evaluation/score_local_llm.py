import argparse
from collections import Counter
from pathlib import Path

from evaluation.fixtures import write_json
from evaluation.reliability_infer import digest
from evaluation.reliability_score import measured
from evaluation.run_local_llm import seal
from evaluation.score import phase3, read, rows_for

ROOT = Path("data/local_llm")


def score(final):
    if final:
        source = ROOT / "fresh_predictions"
        manifest = read(ROOT / "fresh/manifest.json")
        if digest(ROOT / "experiment_seal.json") != manifest["seal"] or read(ROOT / "experiment_seal.json") != seal():
            raise ValueError("Frozen experiment changed.")
        for name, expected in manifest["files"].items():
            if digest(ROOT / "fresh" / name) != expected:
                raise ValueError("Fresh fixture changed.")
        labels = {p.stem: p for p in (ROOT / "fresh/labels").glob("*.json")}
    else:
        source = ROOT / "diagnostics"
        labels = {"synthetic": Path("data/ground_truth.json")}
        for folder in ("data/generalization/labels", "data/reliability/final/labels", "data/metacrafter/fresh/labels"):
            labels.update((path.stem, path) for path in Path(folder).glob("*.json"))
    provenance = read(source / "provenance.json")
    versions = {name: {"sectors": {}, "phase3": {}, "_rows": []}
                for name in ("current", "local", "hybrid")}
    requests, times = Counter(), Counter()
    for name, label in sorted(labels.items()):
        if final and provenance["database_sha256"][name] != manifest["files"][f"databases/{name}.sqlite"]:
            raise ValueError("Inference input did not match the sealed database.")
        report = read(source / (name + ".json"))
        requests.update(report["requests"])
        times.update(report["timing"])
        for engine, variant in report["variants"].items():
            rows = rows_for(name, read(label), variant["hybrid"])
            current = versions[engine]
            current["sectors"][name] = measured(rows)
            current["_rows"].extend(rows)
            current["phase3"][name] = phase3(variant)
    for result in versions.values():
        result["combined"] = measured(result.pop("_rows"))
    write_json(ROOT / ("fresh_metrics.json" if final else "diagnostic_metrics.json"), {
        "scope": "fresh_holdout" if final else "previously_evaluated_diagnostic",
        "requests": dict(requests), "timing": dict(times), "versions": versions, "provenance": provenance,
    })


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    group = parser.add_mutually_exclusive_group()
    group.add_argument("--final", action="store_true")
    group.add_argument("--seal", action="store_true")
    args = parser.parse_args()
    if args.seal:
        path = ROOT / "experiment_seal.json"
        if path.exists():
            raise ValueError("Experiment already sealed.")
        write_json(path, seal())
    else:
        score(args.final)
