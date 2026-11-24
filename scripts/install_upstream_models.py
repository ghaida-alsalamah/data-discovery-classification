"""Fetch pinned pretrained assets for the local SQLite scanner."""
import argparse
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tarfile
from urllib.request import urlopen

ROOT = Path(".models/upstream")
DEPS = Path(".deps")
DODUO_COMMIT = "f3ae5aace5d8364065a3cc3b74ce6cde2c928679"
DODUO_MEMBER = "model/sato0_mosato_bert_bert-base-uncased-bs16-ml-32__sato0-1.00_best_micro_f1.pt"
DODUO_SIZE = 438258249


def install_pii():
    from huggingface_hub import snapshot_download

    snapshot_download("pii-engineer/PII-Engineer-Multi-NER-v2.1",
                      revision="efacd9242671d0300da535207d7952dc3f82f57e", local_dir=ROOT / "pii",
                      allow_patterns=["config.json", "tokenizer.json", "onnx/encoder_int8.onnx",
                                      "onnx/span_rep.onnx", "onnx/count_embed.onnx"])


def install_doduo():
    from huggingface_hub import snapshot_download

    source = DEPS / "upstream-doduo"
    source.parent.mkdir(parents=True, exist_ok=True)
    if not source.exists():
        subprocess.run(["git", "clone", "--no-checkout", "https://github.com/megagonlabs/doduo.git",
                        str(source)], check=True)
    subprocess.run(["git", "-C", str(source), "checkout", "--detach", DODUO_COMMIT], check=True)
    subprocess.run([sys.executable, "-m", "pip", "install", "--target", str(DEPS / "upstream-neural-v2"),
                    "torch==2.9.1+cpu", "transformers==4.57.6", "scikit-learn==1.7.2",
                    "--extra-index-url", "https://download.pytorch.org/whl/cpu"], check=True)
    snapshot_download("google-bert/bert-base-uncased", revision="86b5e0934494bd15c9632b12f734a8a67f723594",
                      local_dir=ROOT / "bert-tokenizer", allow_patterns=["config.json", "vocab.txt", "LICENSE"])
    target = ROOT / "doduo/viznet.pt"
    if target.is_file() and target.stat().st_size == DODUO_SIZE:
        return
    target.parent.mkdir(parents=True, exist_ok=True)
    staging = target.with_suffix(".part")
    with urlopen("https://doduo-data.s3-us-west-2.amazonaws.com/model.tar.gz", timeout=90) as response:
        with tarfile.open(fileobj=response, mode="r|gz") as archive:
            for member in archive:
                if member.name == DODUO_MEMBER and member.isfile() and member.size == DODUO_SIZE:
                    with archive.extractfile(member) as stream, staging.open("wb") as output:
                        shutil.copyfileobj(stream, output)
                    break
            else:
                raise RuntimeError("The official archive did not contain the expected VizNet checkpoint.")
    if staging.stat().st_size != DODUO_SIZE:
        raise RuntimeError("VizNet checkpoint is incomplete.")
    os.replace(staging, target)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("model", choices=("pii", "doduo"))
    args = parser.parse_args()
    {"pii": install_pii, "doduo": install_doduo}[args.model]()
