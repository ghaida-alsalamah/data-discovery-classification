"""Fetch only pinned public weights/runtime. No benchmark inputs are used."""
import hashlib
import io
import re
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from shutil import copyfileobj
from urllib.request import Request, urlopen
from zipfile import ZipFile

ROOT = Path(".models/local-llm")
MODEL = ROOT / "qwen2.5-1.5b-instruct-q4_k_m.gguf"
SERVER = ROOT / "bin/llama-server.exe"
MODEL_REV = "91cad51170dc346986eccefdc2dd33a9da36ead9"
MODEL_SHA = "6a1a2eb6d15622bf3c96857206351ba97e1af16c30d7a74ee38970e434e9407e"
MODEL_URL = ("https://huggingface.co/Qwen/Qwen2.5-1.5B-Instruct-GGUF/resolve/"
             + MODEL_REV + "/" + MODEL.name)
RT_URL = "https://github.com/ggml-org/llama.cpp/releases/download/b6500/llama-b6500-bin-win-cpu-x64.zip"
RT_SHA = "73e00267e852e666a6fce2c3fb7a2603dd1934a37259f3f45c2c1b6983fa605a"


def sha(path):
    with path.open("rb") as handle:
        return hashlib.file_digest(handle, "sha256").hexdigest()


def fetch(url, path, expected, size, workers):
    if path.is_file() and path.stat().st_size == size and sha(path) == expected:
        return
    folder = ROOT / (path.stem + "-parts")
    folder.mkdir(exist_ok=True)
    size_per_part = 8 * 1024 * 1024

    def part(start):
        stop = min(size, start + size_per_part)
        target = folder / str(start)
        for attempt in range(18):
            n = target.stat().st_size if target.exists() else 0
            if start + n == stop:
                return target
            try:
                bounds = f"{start+n}-{stop-1}"
                # A query parameter prevents caches from serving a truncated prior range.
                req = Request(url + f"?download=true&offset={start+n}", headers={
                    "User-Agent": "local-model-bootstrap", "Range": f"bytes={bounds}"})
                with urlopen(req, timeout=45) as reply:
                    if reply.headers.get("Content-Range") != f"bytes {bounds}/{size}":
                        raise OSError("Range not served")
                    with target.open("ab") as disk:
                        copyfileobj(reply, disk, length=65536)
            except OSError:
                if attempt == 17:
                    raise
        if target.stat().st_size != stop - start:
            raise OSError("Incomplete range")
        return target

    try:
        with ThreadPoolExecutor(max_workers=workers) as pool:
            pieces = list(pool.map(part, range(0, size, size_per_part)))
    except OSError:
        print("Range transfer unavailable. Trying publisher URL directly.", flush=True)
        with urlopen(Request(url, headers={"User-Agent": "local-model-bootstrap"}), timeout=120) as reply, path.open("wb") as disk:
            copyfileobj(reply, disk, length=1048576)
    else:
        with path.open("wb") as disk:
            for piece in pieces:
                with piece.open("rb") as source:
                    copyfileobj(source, disk, length=1048576)
    if path.stat().st_size != size or sha(path) != expected:
        raise OSError("Publisher hash verification failed")
    if 'pieces' in locals():
        for piece in pieces:
            piece.unlink()


def runtime():
    ROOT.mkdir(parents=True, exist_ok=True)
    archive = ROOT / "llama-b6500.zip"
    if not archive.exists() or sha(archive) != RT_SHA:
        request = Request(RT_URL, headers={"User-Agent": "local-model-bootstrap"})
        with urlopen(request, timeout=90) as response, archive.open("wb") as output:
            copyfileobj(response, output, length=262144)
    if sha(archive) != RT_SHA:
        raise OSError("Runtime hash verification failed")
    SERVER.parent.mkdir(exist_ok=True)
    with ZipFile(archive) as package:
        for info in package.infolist():
            basename = Path(info.filename).name
            if re.fullmatch(r"(llama-server\.exe|[a-zA-Z0-9_.\-]+\.dll|LICENSE(?:\.txt)?)", basename):
                (SERVER.parent / basename).write_bytes(package.read(info))
    print("Verified llama.cpp b6500", flush=True)


def weights():
    ROOT.mkdir(parents=True, exist_ok=True)
    fetch(MODEL_URL, MODEL, MODEL_SHA, 1117320736, 18)
    print("Verified Qwen Q4_K_M weights", flush=True)


def open_weights():
    from scripts.scan_data_asset import OPEN_MODEL

    ROOT.mkdir(parents=True, exist_ok=True)
    revision = "a06e946bb6b655725eafa393f4a9745d460374c9"
    url = "https://huggingface.co/unsloth/Qwen3-4B-Instruct-2507-GGUF/resolve/" + revision + "/" + OPEN_MODEL.name
    fetch(url, OPEN_MODEL, "9c6e0763577125a994a9bea0bbd7a737ac4498b8a6a4e0f788727553af1806c9", 2075618400, 24)
    print("Verified Qwen 4B Q3_K_M weights", flush=True)


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("asset", choices=["runtime", "weights", "open-weights"])
    args = parser.parse_args()
    {"runtime": runtime, "weights": weights, "open-weights": open_weights}[args.asset]()
