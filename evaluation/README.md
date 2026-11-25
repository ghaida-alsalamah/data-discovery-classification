# Scanner Core evaluation index

The production handover is in the [Scanner Core guide](../docs/SCANNER_CORE_HANDOVER.md). This directory also retains historical experiments. Evaluation modules run only when explicitly invoked.

| Material | What it covers |
| --- | --- |
| [Published metrics](results/scanner_core_metrics.json) | Curated synthetic results with counts, runtime, coverage, fallback, and per-schema metrics |
| [Contextual catalog](CONTEXTUAL_CATALOG.md) | Core setup and the earlier evaluation workflow |
| [Recovery validation](GROQ_ARCHITECTURE_VALIDATION.md) | Batch recovery, confidence diagnostics, and its independent comparison |
| [Anchor validation](GROQ_ANCHOR_VALIDATION.md) | Person-link recovery with matched field responses |
| [Domain definition audit](GROQ_DOMAIN_DEFINITION_AUDIT.md) | Domain granularity, ownership ambiguity, and hierarchy experiments |
| [Future annotation guidelines](DOMAIN_ANNOTATION_GUIDELINES.md) | Protocol for separately sealed operational-purpose labels |
| [Verifier validation](GROQ_VERIFIER_VALIDATION.md) | Targeted second-pass verification at fixed review coverage |
| [Model comparison](GROQ_MODEL_COMPARISON.md) | GPT-OSS 120B, GPT-OSS 20B, and Qwen on Groq Free |

Historical reports reference local paths under `data/`. Those contain generated databases, labels, seals, and full reports and are kept out of Git. The metric snapshot provides a shareable subset. To rerun an experiment on a new checkout, create and seal a new output directory with the corresponding evaluator instead of reusing a seal from another checkout. Do not pool distinct holdouts or interpret a quota-triggered local fallback as model output.
