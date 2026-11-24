from collections import Counter

from .domains import build_domains
from .llm import apply_reasoning, configured_provider
from .opportunities import OpportunityEngine
from .quality import assess_quality


def analyze(connection, schema, relationships, profiles, predictions, *, provider=None,
            use_environment=True, relationship_checks=None):
    quality = assess_quality(connection, schema, relationships, profiles, predictions,
                             relationship_checks=relationship_checks)
    domains = build_domains(predictions, relationships, quality)
    engine = OpportunityEngine(schema, relationships, profiles, predictions, quality)
    opportunities = engine.deterministic_results()
    reasoning_status = "offline"
    if provider is None and use_environment:
        provider, reasoning_status = configured_provider()
    if provider is not None:
        reasoning_status = apply_reasoning(provider, engine, domains, opportunities)
    return domains, quality, {
        "llm_status": reasoning_status,
        "readiness_scope": "Readiness describes technical suitability only. Confirm permitted use separately.",
        "readiness_counts": dict(Counter(row["readiness_status"] for row in opportunities)),
        "opportunities": opportunities,
    }
