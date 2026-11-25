"""Execute DoDuo's published fold-0 prediction script against its released artifacts."""
import argparse
import ast
from itertools import islice
import os
from pathlib import Path
import shutil
import sys
from time import perf_counter
import warnings

ROOT = Path(__file__).resolve().parents[1]
RUNTIME = ROOT / ".deps/upstream-neural-v2"
UPSTREAM = ROOT / ".deps/upstream-doduo/doduo"
ASSETS = ROOT / ".models/upstream"
WORK = ROOT / "data/root_cause/official_doduo"
TAG = "sato0_mosato_bert_bert-base-uncased-bs16-ml-32__sato0-1.00"


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--first-batches", type=int, help="Time an explicitly marked prefix of the official fold.")
    args = parser.parse_args()
    if args.first_batches is not None and args.first_batches < 1:
        parser.error("--first-batches must be positive")
    sys.path.insert(0, str(RUNTIME))
    sys.path.insert(0, str(UPSTREAM))
    import torch
    from transformers import BertConfig, BertTokenizer
    from model import BertForMultiOutputClassification

    torch.set_num_threads(4)
    tokenizer_path = str(ASSETS / "bert-tokenizer")
    load_tokenizer = BertTokenizer.from_pretrained
    BertTokenizer.from_pretrained = lambda _: load_tokenizer(tokenizer_path, local_files_only=True)
    # The checkpoint replaces the entire model. Avoid fetching unused initialization weights.
    def construct(cls, _base, **options):
        config = BertConfig(**options)
        config._attn_implementation = "eager"
        return cls(config).eval()

    BertForMultiOutputClassification.from_pretrained = classmethod(construct)
    load = torch.load

    def load_checkpoint(path, **kwargs):
        state = load(path, **kwargs, weights_only=True)
        legacy = state.pop("bert.embeddings.position_ids", None)
        if legacy is not None and not torch.equal(legacy, torch.arange(512).reshape(1, -1)):
            raise ValueError("Unexpected legacy position index buffer.")
        return state

    torch.load = load_checkpoint
    source = UPSTREAM / "predict_multi.py"
    tree = ast.parse(source.read_text(encoding="utf-8"))
    # The official archive has this fold's micro checkpoint only. Its predictions
    # still yield both macro and micro F1 in the original evaluator.
    loops = [node for node in ast.walk(tree) if isinstance(node, ast.For)
             and isinstance(node.target, ast.Tuple)
             and [item.id for item in node.target.elts if isinstance(item, ast.Name)] == ["f1_name", "model_path"]]
    if len(loops) != 1 or not isinstance(loops[0].iter, ast.List) or len(loops[0].iter.elts) != 2:
        raise ValueError("Unexpected official evaluation loop.")
    loops[0].iter.elts = loops[0].iter.elts[1:]
    if args.first_batches is not None:
        for node in ast.walk(tree):
            if (isinstance(node, ast.For) and isinstance(node.iter, ast.Call)
                    and ast.unparse(node.iter) == "enumerate(test_dataloader)"):
                node.iter = ast.parse("enumerate(probe(test_dataloader))", mode="eval").body
            if (isinstance(node, ast.Assign) and len(node.targets) == 1
                    and ast.unparse(node.targets[0]) == "output_filepath"):
                node.value = ast.BinOp(node.value, ast.Add(), ast.Constant(f".first-{args.first_batches}-batches.json"))
    code = compile(ast.fix_missing_locations(tree), str(source), "exec")

    (WORK / "model").mkdir(exist_ok=True)
    checkpoint = WORK / "model" / (TAG + "_best_micro_f1.pt")
    if not checkpoint.exists():
        shutil.copyfile(ASSETS / "doduo/viznet.pt", checkpoint)
    os.chdir(WORK)
    sys.argv = [str(source), "model/" + TAG]
    warnings.filterwarnings("ignore", category=UserWarning, module="sklearn.metrics")
    def probe(loader):
        started = perf_counter()
        count = min(len(loader), args.first_batches)
        print(f"Timing the first {count} of {len(loader)} official batches.", flush=True)
        yield from islice(loader, count)
        print(f"{count} batches completed in {perf_counter() - started:.1f} seconds.", flush=True)

    with torch.inference_mode():
        exec(code, {"__name__": "__main__", "__file__": str(source), "probe": probe})


if __name__ == "__main__":
    main()
