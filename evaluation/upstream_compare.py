"""Benchmark on read-only databases. This runner never reads labels."""
import argparse
from pathlib import Path

from scripts.scan_data_asset import AssetScan, write_report
from evaluation.reliability_infer import digest, fingerprint


def run(mode, paths, out):
    before = fingerprint(Path("."))
    out.mkdir(parents=True, exist_ok=False)
    scanner = AssetScan(mode)
    files = {}
    for path in paths:
        files[path.name] = digest(path)
        report = scanner.scan(path)
        if files[path.name] != digest(path):
            raise RuntimeError("The source database changed.")
        write_report(out / (path.stem + ".json"), report)
        print(mode, path.stem, len(report["classifications"]), flush=True)
    if fingerprint(Path(".")) != before:
        raise RuntimeError("Backend changed during inference.")
    asset_root = Path(".models/upstream")
    weights = []
    if mode in {"pii", "upstream"}:
        weights += [asset_root / "pii" / name for name in ("onnx/encoder_int8.onnx", "onnx/span_rep.onnx",
                                                          "onnx/count_embed.onnx", "tokenizer.json", "config.json")]
    if mode in {"doduo", "upstream"}:
        weights += [asset_root / "doduo/viznet.pt", asset_root / "bert-tokenizer/vocab.txt"]
    write_report(out / "provenance.json", {"mode": mode, "input_sha256": files, "backend": before,
                                          "asset_sha256": {p.as_posix(): digest(p) for p in weights}})


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("mode", choices=("current", "pii", "doduo", "openmetadata", "upstream"))
    parser.add_argument("output", type=Path)
    parser.add_argument("inputs", nargs="+", type=Path)
    args = parser.parse_args()
    run(args.mode, args.inputs, args.output)
