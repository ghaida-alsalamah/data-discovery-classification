"""Adapters to pretrained upstream checkpoints. Source values remain in process."""
import json
import re
import sys
from collections import Counter
from functools import lru_cache
from pathlib import Path

import numpy as np

# PII Engineer native labels. Never interpret its government_id as a Saudi subtype.
PII_LABELS = ("person_name", "phone_number", "government_id", "street_address",
              "date_of_birth", "email_address", "passport_number", "license_plate", "bank_account_number")
EXACT_PII = {"person_name", "phone_number", "email_address"}
SAUDI = {"saudi_national_id", "saudi_residency_id", "saudi_iban"}
DIRECT_NATIVE = {
    "saudi_national_id": "government_id", "saudi_residency_id": "government_id",
    "saudi_iban": "bank_account_number", **{label: label for label in EXACT_PII},
}
# VizNet only. Related labels are deliberately excluded when a conservative exact mapping is unavailable.
DODUO_MAP = {
    "city": "city", "location": "location",
    "category": "category", "classification": "category", "status": "status",
    "description": "free_text", "notes": "free_text", "code": "identifier",
}


class PIIEngineer:
    """GLiNER2 span inference with the official INT8 weights.

    Port of PII Engineer's v2_full.rs/shared.rs inference glue at 4ff53986a53351b3a516872a557832b44b166628.
    The ONNX graphs, nine labels, first-subword pooling and overlap handling are upstream.
    See licenses/PII-Engineer.txt.
    """

    # Same tokenizer word boundaries, not a detector.
    words = re.compile(r"\w+(?:[-_]\w+)*|\S")

    def __init__(self, model_dir, threads=4):
        import onnxruntime as ort
        from tokenizers import Tokenizer

        location = Path(model_dir)
        config = json.loads((location / "config.json").read_text(encoding="utf-8"))
        self.width = config["max_width"]
        self.hidden = config["hidden_size"]
        self.tokenizer = Tokenizer.from_file(str(location / "tokenizer.json"))
        options = ort.SessionOptions()
        options.intra_op_num_threads = threads
        options.inter_op_num_threads = 1
        options.log_severity_level = 3
        self.encoder, self.span_rep, self.count = [
            ort.InferenceSession(str(location / "onnx" / name), sess_options=options,
                                 providers=["CPUExecutionProvider"])
            for name in ("encoder_int8.onnx", "span_rep.onnx", "count_embed.onnx")]
        self.prompt = ["(", "[P]", "entities", "("]
        self.label_positions = []
        for label in PII_LABELS:
            self.label_positions.append(len(self.prompt))
            self.prompt.extend(("[E]", label))
        self.prompt.extend((")", ")", "[SEP_TEXT]"))

    @lru_cache(maxsize=64)
    def indices(self, count):
        starts = np.repeat(np.arange(count), self.width)
        ends = starts + np.tile(np.arange(self.width), count)
        return np.stack((starts, ends.clip(max=count - 1)), axis=-1)[None], starts, ends

    def labels(self, value):
        if not isinstance(value, (str, int, float)) or isinstance(value, bool):
            return set()
        tokens = self.words.findall(str(value)[:512].lower())[:96]
        if not tokens:
            return set()
        encoding = self.tokenizer.encode(self.prompt + tokens, is_pretokenized=True, add_special_tokens=False)
        first = []
        previous = None
        for index, word in enumerate(encoding.word_ids):
            if word is not None and word != previous:
                first.append(index)
            previous = word
        if len(first) != len(self.prompt) + len(tokens):
            return set()
        embeddings = self.encoder.run(None, {
            "input_ids": np.asarray([encoding.ids], dtype=np.int64),
            "attention_mask": np.asarray([encoding.attention_mask], dtype=np.int64),
        })[0]
        spans, starts, ends = self.indices(len(tokens))
        values = embeddings[:, first[len(self.prompt):]]
        pieces = self.span_rep.run(None, {"word_embs": values, "span_idx": spans})[0]
        field_embeddings = embeddings[0, [first[index] for index in self.label_positions]]
        projected = self.count.run(None, {"field_embs": field_embeddings})[0]
        logits = pieces.reshape(-1, self.hidden) @ projected.reshape(-1, len(PII_LABELS), self.hidden)[0].T
        # Sigmoid score >= 0.5 is equivalent to nonnegative logit. Greedy non-overlapping spans.
        valid, label_ids = np.nonzero((logits >= 0) & (ends[:, None] < len(tokens)))
        ranking = np.argsort(-logits[valid, label_ids], kind="stable")
        occupied, labels = set(), set()
        for position in ranking:
            span = valid[position]
            words = set(range(starts[span], ends[span] + 1))
            if occupied.isdisjoint(words):
                occupied.update(words)
                labels.add(PII_LABELS[label_ids[position]])
        return labels

    def scan_column(self, values):
        counts = Counter()
        for value in values:
            counts.update(self.labels(value))
        return {"samples": len(values), "native_counts": dict(sorted(counts.items())),
                "native_majority": sorted(label for label, count in counts.items() if count * 2 > len(values))}


class DoDuo:
    """Official VizNet checkpoint and Megagon table serializer / model classes."""

    def __init__(self, source, checkpoint, tokenizer, threads=4):
        sys.path.insert(0, str(Path(source).resolve()))
        import torch
        from transformers import BertConfig, BertTokenizer
        from doduo.doduo import DFColTypeTablewiseDataset, sato_coltypes
        from doduo.model import BertForMultiOutputClassification

        torch.set_num_threads(threads)
        self.torch, self.dataset = torch, DFColTypeTablewiseDataset
        self.native_labels = tuple(sato_coltypes)
        self.tokenizer = BertTokenizer.from_pretrained(str(tokenizer), local_files_only=True)
        config = BertConfig(num_labels=len(self.native_labels), output_attentions=True, output_hidden_states=True)
        config._attn_implementation = "eager"
        self.model = BertForMultiOutputClassification(config)
        state = torch.load(checkpoint, map_location="cpu", weights_only=True)
        if "bert.embeddings.position_ids" in state and "bert.embeddings.position_ids" not in self.model.state_dict():
            position = state.pop("bert.embeddings.position_ids")
            if not torch.equal(position, torch.arange(512).reshape(1, -1)):
                raise ValueError("Unexpected legacy position index buffer.")
        self.model.load_state_dict(state, strict=True)
        self.model.eval()

    def scan_table(self, data):
        import pandas as pd

        rows = {}
        names = [name for name, values in data.items() if values]
        for offset in range(0, len(names), 15):
            frame = pd.DataFrame({name: pd.Series([str(value)[:256] for value in data[name]])
                                  for name in names[offset:offset + 15]})
            dataset = self.dataset(frame, self.tokenizer, max_length=32, device=self.torch.device("cpu"))
            table = dataset.table_df.iloc[0]
            with self.torch.inference_mode():
                logits, = self.model(table["data_tensor"].unsqueeze(0))
                logits = logits.reshape(-1, len(self.native_labels))[table["cls_indexes"]]
                probs = logits.softmax(-1)
            for name, scores in zip(frame.columns, probs):
                top = scores.topk(3)
                rows[name] = [{"type": self.native_labels[int(index)], "score": float(score)}
                              for score, index in zip(top.values, top.indices)]
        return rows
