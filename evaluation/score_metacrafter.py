"""Crosswalk-based comparison with labels loaded only after inference."""
import argparse
from collections import Counter
from pathlib import Path

from evaluation.fixtures import write_json
from evaluation.reliability_infer import digest, fingerprint
from evaluation.reliability_score import measured
from evaluation.score import phase3, read, rows_for

ROOT = Path("data/metacrafter")
FILES = [Path("evaluation") / name for name in (
    "metacrafter_adapter.py", "metacrafter_setup.py", "requirements-metacrafter.txt",
    "metacrafter_rules/saudi.yaml", "run_metacrafter.py", "score_metacrafter.py")]


def current_seal():
    return {"adapter_and_evaluation": {path.as_posix(): digest(path) for path in FILES},
            "backend": fingerprint(Path("."))}


def compare(final):
    output = ROOT / ("fresh_predictions" if final else "development_verified")
    provenance = read(output / "provenance.json")
    if final:
        fixtures = ROOT / "fresh"
        manifest = read(fixtures / "manifest.json")
        seal = ROOT / "experiment_seal.json"
        if digest(seal) != manifest["experiment_seal"] or read(seal) != current_seal():
            raise ValueError("Frozen experiment changed.")
        if provenance["backend"] != read(seal)["backend"]:
            raise ValueError("Inference backend differs from seal.")
        for field, file in (("adapter_sha256", "evaluation/metacrafter_adapter.py"),
                            ("rule_sha256", "evaluation/metacrafter_rules/saudi.yaml")):
            if provenance[field] != read(seal)["adapter_and_evaluation"][file]:
                raise ValueError("Inference adapter differs from seal.")
        for name, expected in manifest["files"].items():
            if digest(fixtures / name) != expected:
                raise ValueError("Holdout seal changed.")
        selections = {name: fixtures / "labels" / (name + ".json")
                      for name in ("utilities", "procurement", "community")}
        for key in selections:
            if provenance["database_sha256"][key] != manifest["files"][f"databases/{key}.sqlite"]:
                raise ValueError("Different database used for inference.")
    else:
        selections = {sector: Path(folder) / (sector + ".json") for sectors, folder in (
            (("healthcare", "ecommerce", "education"), "data/generalization/labels"),
            (("logistics", "insurance", "hospitality"), "data/reliability/final/labels"))
                      for sector in sectors}
    versions = {name: {"combined_rows": [], "sectors": {}, "phase3": {}}
                for name in ("current", "metacrafter", "hybrid")}
    provider, time = Counter(), Counter()
    for sector, path in selections.items():
        report = read(output / (sector + ".json"))
        truth = read(path)
        provider.update(report["verifier_status"])
        time.update(report["seconds"])
        for name, variant in report["variants"].items():
            rows = rows_for(sector, truth, variant["hybrid"])
            versions[name]["combined_rows"].extend(rows)
            versions[name]["sectors"][sector] = measured(rows)
            versions[name]["phase3"][sector] = phase3(variant)
    for version in versions.values():
        version["combined"] = measured(version.pop("combined_rows"))
    write_json(ROOT / ("fresh_metrics.json" if final else "development_metrics.json"), {
        "scope": "fresh_holdout" if final else "development_previously_evaluated",
        "versions": versions, "verifier_table_status": dict(provider), "timing_seconds": dict(time),
        "provenance": provenance,
    })


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--final", action="store_true")
    parser.add_argument("--seal", action="store_true")
    args = parser.parse_args()
    if args.seal:
        target = ROOT / "experiment_seal.json"
        if target.exists():
            raise ValueError("Experiment is already sealed.")
        write_json(target, current_seal())
    else:
        compare(args.final)
