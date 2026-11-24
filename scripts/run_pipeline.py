import argparse
import json
from dataclasses import asdict
from pathlib import Path

from backend.app.connectors.sqlite import InformationAsset, SQLiteConnector
from backend.app.discovery.schema import discover
from backend.app.models.synthetic import generate_database
from backend.app.profiling.columns import profile_database


def run(output_dir: Path, sample_size=500):
    database = output_dir / "synthetic.sqlite"
    generate_database(database, output_dir / "ground_truth.json")
    asset = InformationAsset("Synthetic digital services", "Fictional Saudi services data", "Demo")
    with SQLiteConnector(database, asset).connect() as connection:
        schema, relationships = discover(connection)
        profiles = profile_database(connection, schema, sample_size)
        schema["asset"] = asdict(asset)

    for name, payload in (("schema", schema), ("relationships", relationships), ("profiles", profiles)):
        (output_dir / f"{name}.json").write_text(
            json.dumps(payload, indent=2, ensure_ascii=False, allow_nan=False) + "\n",
            encoding="utf-8",
        )


def main():
    parser = argparse.ArgumentParser(description="Generate, discover and profile a synthetic database.")
    parser.add_argument("--output-dir", type=Path, default=Path("data"))
    parser.add_argument("--sample-size", type=int, default=500)
    args = parser.parse_args()
    if args.sample_size < 1:
        parser.error("--sample-size must be positive")
    run(args.output_dir, args.sample_size)


if __name__ == "__main__":
    main()
