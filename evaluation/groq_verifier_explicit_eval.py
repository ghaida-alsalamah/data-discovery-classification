"""Evaluate the development-validated output contract on sealed production decisions."""
import argparse
from pathlib import Path
from time import perf_counter
from collections import Counter

import httpx

from backend.app.classification.context_provider import FreeCatalogProvider
from evaluation import groq_verifier_holdout as holdout
from evaluation.catalog_verifier_explicit import verify
from evaluation.default_holdout import metrics
from evaluation.reliability_infer import digest
from evaluation.score import read, rows_for
from scripts.scan_data_asset import write_report

ROOT = holdout.ROOT
OUT = ROOT / "explicit_verifier"


def config():
    return {p: digest(Path(p)) for p in ("evaluation/catalog_verifier_explicit.py",
            "evaluation/groq_verifier_explicit_eval.py", "evaluation/groq_verifier_holdout.py",
            "evaluation/default_holdout.py")}


def main(action):
    original = read(ROOT / "seal.json")
    files = original["fixtures"]
    seal = ROOT / "explicit_seal.json"
    baseline = {name: digest(ROOT / "baseline" / (name + ".json")) for name in holdout.SOURCES}
    current = {"configuration": config(), "fixtures": files, "baseline": baseline}
    if any(digest(ROOT / name) != sha for name, sha in files.items()):
        raise ValueError("Frozen fixtures changed.")
    if action == "freeze":
        if seal.exists():
            raise FileExistsError(seal)
        write_report(seal, current)
        return
    if read(seal) != current:
        raise ValueError("Verifier or baseline changed.")
    OUT.mkdir(exist_ok=False)
    started, pooled, entries, per_database = perf_counter(), [], [], {}
    with httpx.Client(timeout=35, trust_env=False, follow_redirects=False) as client:
        provider = FreeCatalogProvider(client, "groq")
        for name in holdout.SOURCES:
            report = read(ROOT / "baseline" / (name + ".json"))
            rows = report["classifications"]
            begin = perf_counter()
            verify(provider, rows, *holdout.schema_evidence(ROOT / (name + ".sqlite")))
            seconds = perf_counter() - begin
            truth = read(ROOT / (name + "_labels.json"))
            scored = rows_for(name, truth, rows)
            index = {(r["table_name"], r["column_name"]): r for r in rows}
            tagged = [(truth[r["table"]][r["column"]], index[r["table"], r["column"]], {}) for r in scored]
            pooled.extend(scored)
            entries.extend(tagged)
            per_database[name] = {**metrics(scored, tagged, "default"), "seconds": seconds,
                                  "context_status": dict(Counter(r["context_status"] for r in rows))}
            write_report(OUT / (name + ".json"), {**report, "verifier_seconds": seconds})
        write_report(OUT / "metrics.json", {"overall": metrics(pooled, entries, "default"),
                     "by_database": per_database, "runtime": provider.counters,
                     "seconds": sum(r["seconds"] for r in per_database.values()),
                     "wall_seconds": perf_counter() - started})
    sources = [(ROOT, name) for name in holdout.SOURCES]
    holdout.verification_diagnostics(sources, "explicit_verifier")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("freeze", "run"))
    main(parser.parse_args().action)
