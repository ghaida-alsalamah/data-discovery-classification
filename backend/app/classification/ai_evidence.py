"""Optional imports are confined to the local AI adapters."""
import re
from collections import Counter
from pathlib import Path

from .detectors import PATTERNS, normalize
from .taxonomy import DOMAINS, TYPES

MODEL_ID = "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2"
DEFAULT_MODEL_PATH = Path(".models/minilm")


class PresidioEvidence:
    def __init__(self):
        import spacy
        from presidio_analyzer import AnalyzerEngine, Pattern, PatternRecognizer, RecognizerRegistry
        from presidio_analyzer.nlp_engine import SpacyNlpEngine

        class TokenizerEngine(SpacyNlpEngine):
            def load(self):
                self.nlp = {"en": spacy.blank("en"), "ar": spacy.blank("ar")}

        languages = ["en", "ar"]
        registry = RecognizerRegistry(supported_languages=languages)
        for language in languages:
            for label, pattern in PATTERNS.items():
                if label == "date":
                    continue
                registry.add_recognizer(PatternRecognizer(
                    supported_entity=label, supported_language=language,
                    patterns=[Pattern(label, rf"\A(?:{pattern})\Z", 0.65)],
                ))
        self.analyzer = AnalyzerEngine(
            registry=registry, nlp_engine=TokenizerEngine(), supported_languages=languages,
            default_score_threshold=0.5, log_decision_process=False,
        )

    def summarize(self, values):
        counts = Counter()
        for text, frequency in Counter(map(normalize, values)).items():
            if not text or len(text) > 256:
                continue
            language = "ar" if re.search(r"[\u0600-\u06ff]", text) else "en"
            for entity in {match.entity_type for match in self.analyzer.analyze(text, language)}:
                counts[entity] += frequency
        return dict(counts)


class SemanticEvidence:
    def __init__(self, model_path=DEFAULT_MODEL_PATH):
        import numpy as np
        import onnxruntime as ort
        from tokenizers import Tokenizer

        directory = Path(model_path)
        weights = directory / "onnx" / "model.onnx"
        tokenizer = directory / "tokenizer.json"
        if not weights.is_file() or not tokenizer.is_file():
            raise FileNotFoundError(f"Download the MiniLM ONNX model and tokenizer into {directory}.")
        self.np = np
        self.tokenizer = Tokenizer.from_file(str(tokenizer))
        self.tokenizer.enable_padding(pad_id=self.tokenizer.token_to_id("<pad>"), pad_token="<pad>")
        self.tokenizer.enable_truncation(max_length=128)
        options = ort.SessionOptions()
        options.intra_op_num_threads = 4
        self.model = ort.InferenceSession(str(weights), sess_options=options,
                                          providers=["CPUExecutionProvider"])
        self.inputs = {item.name for item in self.model.get_inputs()}
        self.semantic_index = self._index({
            kind: (item.english, item.arabic, *item.aliases)
            for kind, item in TYPES.items() if kind != "unknown"
        })
        self.domain_index = self._index({
            kind: (english, arabic, *aliases) for kind, (english, arabic, aliases) in DOMAINS.items()
        })

    def _encode(self, texts):
        batches = []
        for start in range(0, len(texts), 32):
            tokens = self.tokenizer.encode_batch(texts[start:start + 32])
            arrays = {
                "input_ids": [item.ids for item in tokens],
                "attention_mask": [item.attention_mask for item in tokens],
                "token_type_ids": [item.type_ids for item in tokens],
            }
            inputs = {key: self.np.asarray(arrays[key], dtype=self.np.int64) for key in self.inputs}
            hidden, = self.model.run(["last_hidden_state"], inputs)
            mask = inputs["attention_mask"][..., None].astype(hidden.dtype)
            mean = (hidden * mask).sum(axis=1) / mask.sum(axis=1).clip(min=1)
            batches.append(mean / self.np.linalg.norm(mean, axis=1, keepdims=True).clip(min=1e-12))
        return self.np.concatenate(batches)

    def _index(self, descriptions):
        labels = [kind for kind, texts in descriptions.items() for _ in texts]
        matrix = self._encode([text for texts in descriptions.values() for text in texts])
        return labels, matrix

    @staticmethod
    def _similarities(index, queries):
        labels, matrix = index
        for row in queries @ matrix.T:
            scores = {}
            for kind, score in zip(labels, row):
                scores[kind] = max(scores.get(kind, -1.0), float(score))
            yield scores

    def compare(self, column_names, contexts, table_contexts):
        vectors = self._encode([*column_names, *contexts, *table_contexts])
        split = len(column_names)
        names = self._similarities(self.semantic_index, vectors[:split])
        context = self._similarities(self.semantic_index, vectors[split:2 * split])
        columns = [{kind: 0.8 * named[kind] + 0.2 * nearby[kind] for kind in named}
                   for named, nearby in zip(names, context)]
        domains = list(self._similarities(self.domain_index, vectors[2 * split:]))
        return columns, domains
