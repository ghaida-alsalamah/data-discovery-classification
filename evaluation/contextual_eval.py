"""Development comparison and locked holdout evaluation for contextual cataloging."""
import argparse

import httpx

from backend.app.classification.context_provider import FreeCatalogProvider
from collections import Counter
from pathlib import Path
from subprocess import check_output
from time import perf_counter

from backend.app.classification.local_llm import launch, peak_memory
from evaluation.default_holdout import metrics
from evaluation.public_catalog import protocol_hashes
from evaluation.reliability_infer import digest, fingerprint
from evaluation.score import read, rows_for
from scripts.scan_data_asset import AssetScan, CONTEXT_MODEL, CONTEXT_SERVER, CONTEXT_THREADS, write_report

DEV = [
    (Path("data/default_release_validation"), "course_teach"),
    (Path("data/platform_adoption"), "community_care"),
    (Path("data/default_validation"), "dog_kennels"),
]
ROOT = Path("data/contextual_holdout")
THREADS = CONTEXT_THREADS


def configuration(model, server, selected, gpu_layers):
    from backend.app.classification.contextual_catalog import NER_ROOT
    from evaluation import contextual_holdout

    return {"commit": check_output(["git", "rev-parse", "HEAD"], text=True).strip(),
            "backend": fingerprint(Path(".")), "protocol": protocol_hashes(), "runner": digest(Path(__file__)),
            "fixtures": digest(Path(contextual_holdout.__file__)),
            "selected": selected,
            "model": model.name if selected == "local" else None,
            "gguf_sha256": digest(model) if selected == "local" else None,
            "server_sha256": digest(server) if selected == "local" else None,
            "dll_sha256": {p.name: digest(p) for p in sorted(server.parent.glob("*.dll"))} if selected == "local" else {},
            "ner": {p.relative_to(NER_ROOT).as_posix(): digest(p) for p in sorted(NER_ROOT.rglob("*"))
                    if p.is_file() and "__pycache__" not in p.parts},
            "threads": THREADS, "context_window": 6144, "gpu_layers": gpu_layers, "dictionary": None}


def run(mode, sources, out, model, server, gpu_layers=0):
    out.mkdir(parents=True, exist_ok=False)
    reports = {}
    startup = perf_counter()

    def scan(scanner):
        for root, name in sources:
            report = scanner.scan(root / (name + ".sqlite"))
            row = {
                "classifications": report["classifications"],
                "seconds": report["timing_seconds"]["total"],
                "context": report.get("context_summary", {}),
                "context_status": dict(Counter(r.get("context_status", "absent") for r in report["classifications"])),
                "domains": len(report["domains"]["domains"]),
                "opportunities": len(report["opportunities"]["opportunities"]),
            }
            reports[name] = row
            write_report(out / (name + ".json"), row)
            print(mode, name, row["context_status"], round(row["seconds"], 1), flush=True)

    if mode in {"groq", "gemini"}:
        with httpx.Client(timeout=35, trust_env=False, follow_redirects=False) as client:
            provider = FreeCatalogProvider(client, mode)
            scan(AssetScan("contextual", provider=provider))
            write_report(out / "runtime.json", provider.counters)
    elif mode == "local":
        with launch(server, model, threads=THREADS, context_size=6144, gpu_layers=gpu_layers) as runtime:
            scan(AssetScan("contextual", runtime=runtime))
            write_report(out / "runtime.json", {**runtime.counters, "startup_seconds": runtime.startup_seconds,
                                                "peak_server_mib": peak_memory(runtime.process.pid)})
    else:
        scan(AssetScan("default" if mode == "baseline" else "contextual", offline=True))
    writes = perf_counter() - startup
    pooled, entries, by_database = [], [], {}
    for root, name in sources:
        truth = read(root / (name + "_labels.json"))
        report = reports[name]
        rows = rows_for(name, truth, report["classifications"])
        index = {(row["table_name"], row["column_name"]): row for row in report["classifications"]}
        tagged = [(truth[r["table"]][r["column"]], index[r["table"], r["column"]], {}) for r in rows]
        pooled.extend(rows)
        entries.extend(tagged)
        by_database[name] = {**metrics(rows, tagged, "default"),
                             **{k: v for k, v in report.items() if k != "classifications"}}
    write_report(out / "metrics.json", {
        "overall": metrics(pooled, entries, "default"), "by_database": by_database,
        "seconds": sum(r["seconds"] for r in reports.values()), "wall_seconds": writes,
        "runtime": read(out / "runtime.json") if mode in {"local", "groq", "gemini"} else None,
    })


def final(action, model, server, selected, gpu_layers):
    from evaluation.contextual_holdout import SOURCES, materialize

    seal = ROOT / "seal.json"
    sources = [(ROOT, name) for name in SOURCES]
    inputs = ROOT / "fixture_inputs.json"
    if action == "prepare":
        if inputs.exists() or seal.exists():
            raise FileExistsError(inputs)
        write_report(inputs, materialize(ROOT))
        return
    if action == "freeze":
        if seal.exists():
            raise FileExistsError(seal)
        write_report(seal, {"configuration": configuration(model, server, selected, gpu_layers), "inputs": read(inputs)})
        return
    frozen = read(seal)

    def verify():
        if configuration(model, server, selected, gpu_layers) != frozen["configuration"]:
            raise ValueError("Frozen catalog settings changed.")
        if any(digest(ROOT / name) != checksum for name, checksum in frozen["inputs"].items()):
            raise ValueError("Frozen holdout input changed.")

    verify()
    for mode in ("baseline", selected):
        run(mode, sources, ROOT / mode, model, server, gpu_layers)
    verify()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("baseline", "offline", "local", "groq", "gemini", "prepare", "freeze", "final"))
    parser.add_argument("--out", type=Path, default=Path("data/contextual_development"))
    parser.add_argument("--model", type=Path, default=CONTEXT_MODEL)
    parser.add_argument("--server", type=Path, default=CONTEXT_SERVER)
    parser.add_argument("--selected", choices=("local", "offline"), default="local")
    parser.add_argument("--gpu-layers", type=int, default=0)
    args = parser.parse_args()
    if args.action in {"prepare", "freeze", "final"}:
        final(args.action, args.model, args.server, args.selected, args.gpu_layers)
    else:
        run(args.action, DEV, args.out / args.action, args.model, args.server, args.gpu_layers)
