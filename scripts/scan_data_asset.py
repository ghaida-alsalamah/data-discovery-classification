"""Read-only SQLite data discovery with optional upstream pretrained classifiers."""
import argparse
import json
import sys
from pathlib import Path
from time import perf_counter

from backend.app.classification.ai_evidence import DEFAULT_MODEL_PATH, PresidioEvidence, SemanticEvidence
from backend.app.classification.engine import HybridClassifier
from backend.app.classification.pretrained import DIRECT_NATIVE, DODUO_MAP, DoDuo, PIIEngineer
from backend.app.classification.upstream import collect, merge
from backend.app.connectors.sqlite import InformationAsset, SQLiteConnector
from backend.app.discovery.schema import discover
from backend.app.intelligence.service import analyze
from backend.app.profiling.columns import profile_database

ASSETS = Path(".models/upstream")


class AssetScan:
    def __init__(self, mode="current", assets=ASSETS, dependency_root=Path(".deps")):
        self.mode = mode
        self.pii = PIIEngineer(assets / "pii") if mode in {"pii", "upstream"} else None
        self.doduo = None
        self.openmetadata = None
        if mode in {"doduo", "upstream"}:
            sys.path.append(str((dependency_root / "upstream-neural-v2").resolve()))
            self.doduo = DoDuo(dependency_root / "upstream-doduo",
                               assets / "doduo/viznet.pt", assets / "bert-tokenizer")
        if mode == "openmetadata":
            sys.path.append(str((dependency_root / "upstream-om").resolve()))
            from .upstream_openmetadata import OpenMetadataPII
            self.openmetadata = OpenMetadataPII()
        self.detector = PresidioEvidence()
        self.baseline = HybridClassifier(SemanticEvidence(DEFAULT_MODEL_PATH))

    def scan(self, db_path):
        started = perf_counter()
        name = db_path.stem
        with SQLiteConnector(
            db_path, InformationAsset(name, "Read-only data discovery", "Local scanner")
        ).connect() as connection:
            schema, relationships = discover(connection)
            profiles = profile_database(connection, schema, 500, self.detector)
            base = self.baseline.classify(schema, profiles)
            baseline = {(row["table_name"], row["column_name"]): row for row in base}
            baseline_seconds = perf_counter() - started
            predictions, native = [], {}
            for table in schema["tables"]:
                tname = table["name"]
                samples = (collect(connection, table, profiles[tname])
                           if (self.pii or self.doduo or self.openmetadata) else {})
                semantic = self.doduo.scan_table(samples) if self.doduo else {}
                for col in table["columns"]:
                    cname = col["name"]
                    key = (tname, cname)
                    prior = baseline[key]
                    ner = self.pii.scan_column(samples[cname]) if self.pii else None
                    om = self.openmetadata.classify(samples[cname], col) if self.openmetadata else None
                    scores = semantic.get(cname)
                    if self.mode == "upstream" or self.mode == "pii":
                        prediction = merge(prior, profiles[tname][cname], ner, scores, tname, cname)
                    else:
                        prediction = dict(prior)
                        label = DIRECT_NATIVE.get(prior["semantic_type"]) if prior["personal_data"] == "yes" else None
                        prediction.update(direct_pii_type=label, direct_pii_status="yes" if label else "uncertain")
                    predictions.append(prediction)
                    native.setdefault(tname, {})[cname] = {
                        "pii": ner, "doduo": scores, "openmetadata": om,
                        "doduo_mapped": DODUO_MAP.get(scores[0]["type"]) if scores else None,
                    }
            inference_seconds = perf_counter() - started - baseline_seconds
            domains, quality, opportunities = analyze(connection, schema, relationships, profiles,
                                                       predictions, use_environment=False)
        return {
            "mode": self.mode, "schema": schema, "relationships": relationships, "profiles": profiles,
            "classifications": predictions, "native_predictions": native, "domains": domains,
            "quality": quality, "opportunities": opportunities, "timing_seconds": {
                "discovery_profile_current": baseline_seconds, "added_model_inference": inference_seconds,
                "total": perf_counter() - started,
            },
        }


def write_report(path, report):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(report, ensure_ascii=False, indent=2, allow_nan=False) + "\n", encoding="utf-8")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("database", type=Path)
    parser.add_argument("output", type=Path)
    parser.add_argument("--engine", choices=("current", "pii", "doduo", "openmetadata", "upstream"), default="current")
    args = parser.parse_args()
    write_report(args.output, AssetScan(args.engine).scan(args.database))
