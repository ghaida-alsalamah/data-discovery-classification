"""Read-only SQLite data discovery with optional upstream pretrained classifiers."""
import argparse
from dataclasses import asdict
import json
import sys
from pathlib import Path
from time import perf_counter

from backend.app.classification.ai_evidence import DEFAULT_MODEL_PATH, PresidioEvidence, SemanticEvidence
from backend.app.classification.discovery_evidence import descriptions, enrich
from backend.app.classification.english import EnglishMetadata, classify_content, refine
from backend.app.classification.engine import HybridClassifier
from backend.app.classification.evidence_catalog import classify as classify_evidence
from backend.app.classification.pretrained import DIRECT_NATIVE, DODUO_MAP, DoDuo, PIIEngineer
from backend.app.classification.relational_catalog import refine as refine_relational
from backend.app.classification.reviews import apply_reviews
from backend.app.classification.taxonomy import TYPES
from backend.app.classification.upstream import collect, merge
from backend.app.connectors.sqlite import InformationAsset, SQLiteConnector
from backend.app.discovery.schema import discover
from backend.app.intelligence.domains import PURPOSES
from backend.app.intelligence.quality import verify_relationships
from backend.app.intelligence.service import analyze
from backend.app.profiling.columns import profile_database

ASSETS = Path(".models/upstream")


class AssetScan:
    def __init__(self, mode="evidence", assets=ASSETS, dependency_root=Path(".deps")):
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
        model_ready = all((DEFAULT_MODEL_PATH / name).is_file() for name in ("tokenizer.json", "onnx/model.onnx"))
        semantic = SemanticEvidence(DEFAULT_MODEL_PATH) if model_ready or mode not in {"enhanced", "english", "evidence", "relational"} else None
        self.baseline = HybridClassifier(EnglishMetadata(semantic) if mode == "english" and semantic else semantic)

    def scan(self, db_path, *, dictionary=None, owner=None, description=None, reviews=None):
        started = perf_counter()
        name = db_path.stem
        asset = InformationAsset(name, description or "Read-only data discovery", owner or "unknown")
        with SQLiteConnector(db_path, asset).connect() as connection:
            if self.mode in {"enhanced", "english", "evidence", "relational"}:
                connection.exec_driver_sql("BEGIN")
            schema, relationships = discover(connection)
            profiles = profile_database(connection, schema, 500, self.detector)
            base = self.baseline.classify(schema, profiles)
            checks = None
            if self.mode in {"enhanced", "english", "evidence", "relational"}:
                schema["asset"] = asdict(asset)
                checks = verify_relationships(connection, schema, relationships)
                if self.mode in {"english", "evidence", "relational"}:
                    metadata = descriptions(dictionary)
                    samples_by_table = {t["name"]: collect(connection, t, profiles[t["name"]])
                                        for t in schema["tables"]}
                if self.mode in {"evidence", "relational"}:
                    base = classify_evidence(base, schema, profiles, samples_by_table, relationships,
                                             checks, metadata, asset_description=description)
                    if self.mode == "relational":
                        base = refine_relational(connection, base, schema, profiles, samples_by_table,
                                                 relationships, checks, metadata)
                else:
                    if self.mode == "english":
                        classify_content(base, profiles, samples_by_table, metadata)
                    base = enrich(base, profiles, relationships, checks, dictionary, schema=schema,
                                  asset_description=description)
                    if self.mode == "english":
                        base = refine(base, profiles, metadata, relationships, checks, schema)
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
            review_history = apply_reviews(predictions, reviews) if reviews is not None else []
            if self.mode in {"enhanced", "english", "evidence", "relational"}:
                for row in predictions:
                    row["field_meaning"] = TYPES[row["semantic_type"]].english
                    row["potential_value"] = PURPOSES.get(row["data_domain"], "Confirm the domain before using this field.")
                    row.setdefault("review_status", "pending" if row["review_required"] else "unreviewed")
            inference_seconds = perf_counter() - started - baseline_seconds
            domains, quality, opportunities = analyze(connection, schema, relationships, profiles,
                                                       predictions, use_environment=False,
                                                       relationship_checks=checks)
        report = {
            "mode": self.mode, "schema": schema, "relationships": relationships, "profiles": profiles,
            "classifications": predictions, "native_predictions": native, "domains": domains,
            "quality": quality, "opportunities": opportunities, "timing_seconds": {
                "discovery_profile_current": baseline_seconds, "added_model_inference": inference_seconds,
                "total": perf_counter() - started,
            },
        }
        if self.mode in {"enhanced", "english", "evidence", "relational"}:
            report["review_history"] = review_history
        return report


def write_report(path, report):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(report, ensure_ascii=False, indent=2, allow_nan=False) + "\n", encoding="utf-8")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("database", type=Path)
    parser.add_argument("output", type=Path)
    parser.add_argument("--engine", choices=("relational", "evidence", "english", "enhanced", "current", "pii", "doduo", "openmetadata", "upstream"), default="evidence")
    parser.add_argument("--dictionary", type=Path, help="Optional JSON database, table and field descriptions")
    parser.add_argument("--owner", help="Source asset owner as supplied by the operator")
    parser.add_argument("--description", help="Asset description supplied by the operator and included in the export")
    parser.add_argument("--reviews", type=Path, help="Ordered JSON specialist corrections to apply to the catalog")
    args = parser.parse_args()
    if (args.dictionary or args.reviews) and args.engine not in {"enhanced", "english", "evidence", "relational"}:
        parser.error("--dictionary and --reviews require a catalog scanner")
    data = json.loads(args.dictionary.read_text(encoding="utf-8")) if args.dictionary else None
    reviews = json.loads(args.reviews.read_text(encoding="utf-8")) if args.reviews else None
    write_report(args.output, AssetScan(args.engine).scan(
        args.database, dictionary=data, owner=args.owner, description=args.description, reviews=reviews,
    ))
