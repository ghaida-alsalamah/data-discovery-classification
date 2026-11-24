"""Compare the local contextual classifier and hybrid using one proposal per table."""
import argparse
import os
from collections import Counter
from pathlib import Path
from time import perf_counter

from backend.app.classification.ai_evidence import DEFAULT_MODEL_PATH, PresidioEvidence, SemanticEvidence
from backend.app.classification.engine import HybridClassifier
from backend.app.classification.local_llm import classify_table, launch, peak_memory
from backend.app.connectors.sqlite import InformationAsset, SQLiteConnector
from backend.app.discovery.schema import discover
from backend.app.intelligence.service import analyze
from backend.app.profiling.columns import profile_database
from evaluation.local_llm_setup import MODEL, MODEL_SHA, SERVER
from evaluation.reliability_infer import digest, fingerprint, write
from evaluation.score import read


def seal():
    paths = [Path(__file__), Path("evaluation/score_local_llm.py"), Path("evaluation/DOMAIN_SCORING.md"),
             Path("evaluation/local_llm_setup.py")]
    return {"backend": fingerprint(Path(".")), "model_sha256": digest(MODEL),
            "runtime_sha256": {path.name: digest(path) for path in sorted(SERVER.parent.iterdir()) if path.is_file()},
            "evaluation_sha256": {path.name: digest(path) for path in paths}}


def run(output, databases, threads, frozen):
    provenance = seal()
    if provenance["model_sha256"] != MODEL_SHA:
        raise ValueError("Model differs from the publisher's pinned file.")
    if frozen and provenance != read(frozen):
        raise ValueError("Evaluator or runtime differs from the seal.")
    output.mkdir(parents=True, exist_ok=False)
    model = HybridClassifier(SemanticEvidence(DEFAULT_MODEL_PATH))
    detector = PresidioEvidence()
    peak_before_llm = peak_memory(os.getpid())
    started = perf_counter()
    with launch(SERVER, MODEL, threads) as runtime:
        for source_index, path in enumerate(databases, 1):
            statuses = Counter()
            with SQLiteConnector(path, InformationAsset(path.stem, "Synthetic local benchmark", "Evaluation")).connect() as con:
                tick = perf_counter()
                schema, links = discover(con)
                profiles = profile_database(con, schema, 500, detector)
                profiled = perf_counter()
                baseline = model.classify(schema, profiles)
                classified = perf_counter()
                cache = {(row["table_name"], row["column_name"]): row for row in baseline}
                local, hybrid = [], []
                for table_index, table in enumerate(schema["tables"], 1):
                    name = table["name"]
                    existing = {col["name"]: cache[name, col["name"]] for col in table["columns"]}
                    standalone, combined, status = classify_table(runtime, schema, table, profiles[name], existing)
                    local.extend(standalone)
                    hybrid.extend(combined)
                    statuses[status] += 1
                    print(f"source {source_index}, table {table_index}: {status}", flush=True)
                reasoned = perf_counter()
                variants = {}
                for name, rows in (("current", baseline), ("local", local), ("hybrid", hybrid)):
                    domains, quality, opportunities = analyze(con, schema, links, profiles, rows, use_environment=False)
                    variants[name] = {"hybrid": rows, "schema": schema, "domains": domains,
                                      "quality": quality, "opportunities": opportunities}
            write(output / (path.stem + ".json"), {"variants": variants, "requests": dict(statuses),
                "timing": {"profile": profiled - tick, "current": classified - profiled,
                           "llm_and_hybrid": reasoned - classified}})
        resources = {"server_peak_rss_mib": peak_memory(runtime.process.pid),
                     "python_peak_rss_before_server_mib": peak_before_llm,
                     "python_peak_rss_mib": peak_memory(os.getpid()),
                     "server_startup_seconds": runtime.startup_seconds,
                     "wall_seconds": perf_counter() - started, "threads": threads, **runtime.counters}
    write(output / "provenance.json", {**provenance, "resources": resources,
          "database_sha256": {p.stem: digest(p) for p in databases}})


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("output", type=Path)
    parser.add_argument("databases", nargs="+", type=Path)
    parser.add_argument("--threads", type=int, default=4)
    parser.add_argument("--seal", type=Path)
    args = parser.parse_args()
    if args.threads < 1:
        parser.error("--threads must be positive.")
    run(args.output, args.databases, args.threads, args.seal)
