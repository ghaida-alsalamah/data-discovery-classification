"""Compare Groq models without changing the production scanner."""
import argparse
from pathlib import Path
from time import perf_counter

import httpx

from backend.app.classification.context_provider import FreeCatalogProvider
from evaluation import contextual_eval as harness
from scripts.scan_data_asset import write_report

MODELS = {
    "oss120": "openai/gpt-oss-120b",
    "oss20": "openai/gpt-oss-20b",
    "qwen27": "qwen/qwen3.8-27b",
}
ROOT = Path("data/groq_model_comparison")


def smoke():
    out = {}
    fixture = [{"table": "order", "fields": [["date", "d", "", "D10"]]}]
    with httpx.Client(timeout=25, trust_env=False, follow_redirects=False) as client:
        provider = FreeCatalogProvider(client, "groq")
        response = client.get("https://api.groq.com/openai/v1/models",
                              headers={"Authorization": f"Bearer {provider.key}"})
        response.raise_for_status()
        available = {model["id"]: model for model in response.json()["data"]}
        for slug, model in MODELS.items():
            provider = FreeCatalogProvider(client, "groq")
            provider.model = model
            record = {"model": model, "listed": model in available}
            if model in available:
                record["listed_context"] = available[model].get("context_window")
                try:
                    roles, fields = provider.classify(fixture, 1)
                    record.update(structured=True, fixture_expected=fields[0][0] == "date")
                except (httpx.HTTPError, ValueError, KeyError, IndexError, TypeError):
                    record["structured"] = False
            record["counters"] = provider.counters
            out[slug] = record
            print(slug, record, flush=True)
    write_report(ROOT / "availability.json", out)


def run_model(slug, sources, output, *, minimum_spacing=0):
    original = harness.FreeCatalogProvider

    class SelectedModel(original):
        def __init__(self, *args, **kwargs):
            super().__init__(*args, **kwargs)
            self.model = MODELS[slug]

        def request(self, *args, **kwargs):
            try:
                return super().request(*args, **kwargs)
            finally:
                if minimum_spacing:
                    self.next_request = max(self.next_request, perf_counter() + minimum_spacing)

    harness.FreeCatalogProvider = SelectedModel
    try:
        harness.run("groq", sources, output, None, None)
    finally:
        harness.FreeCatalogProvider = original


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("smoke", "development", "repeat", "quota-recheck"))
    parser.add_argument("--model", choices=MODELS)
    args = parser.parse_args()
    if args.action == "smoke":
        smoke()
    elif not args.model:
        parser.error("Select a model.")
    else:
        selected = harness.DEV[-1:] if args.action == "repeat" else harness.DEV
        run_model(args.model, selected, ROOT / args.action / args.model,
                  minimum_spacing=30 if args.action == "quota-recheck" else 0)
