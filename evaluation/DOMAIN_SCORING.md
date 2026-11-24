# Predefined reliability domain scoring

Literal domain labels are scored first. Hierarchical agreement is a separate deterministic measure.

| Parent | Exact labels |
| --- | --- |
| Person and workforce services | customer, workforce |
| Commercial offerings | catalog, commerce |
| Financial administration | finance, insurance |
| Service delivery | support, hospitality |
| Operational coordination | operations, logistics |
| Health services | healthcare |
| Learning services | education |
| Unresolved | unknown |

Each label belongs to exactly one parent. Unexpected labels map to unresolved for hierarchical scoring only. No semantic similarity, manual adjudication, or post-result reassignment is used. A parent match can conceal important differences, so it never replaces the exact metric.

For semantic category agreement the comparison uses one shared mapping for both versions. Record, reference, national, residency, business, generic, service, shipment, policy, and reservation identifiers map to Identifier. Other known categories follow the updated taxonomy. Unsupported truth maps to unknown for open-set detection and category agreement, but remains a miss for strict exact accuracy.
