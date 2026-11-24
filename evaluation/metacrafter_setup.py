"""Materialize and verify the pinned wheel's bundled assets without network access."""
import hashlib
import sys
import tarfile
from importlib.metadata import version
from pathlib import Path, PurePosixPath

DEPS = Path(".deps/metacrafter-experiment")
ASSETS = Path(".deps/metacrafter-assets")


def use_dependency():
    if not DEPS.is_dir():
        raise SystemExit("Install the pinned experiment requirements into " + str(DEPS))
    sys.path.append(str(DEPS.resolve()))
    if version("metacrafter") != "2.0.0":
        raise RuntimeError("This evaluation expects Metacrafter 2.0.0.")


def prepare():
    use_dependency()
    from metacrafter.registry.adapter import read_bundled_snapshot, verify_snapshot
    from metacrafter.rules.pack import DEFAULT_SHA256, bundled_archive

    registry, rules = ASSETS / "registry", ASSETS / "rules"
    registry.mkdir(parents=True, exist_ok=True)
    rules.mkdir(parents=True, exist_ok=True)
    for name, content in read_bundled_snapshot().items():
        (registry / Path(name).name).write_bytes(content)
    if not verify_snapshot(registry):
        raise ValueError("Bundled registry failed manifest verification.")
    archive = bundled_archive()
    if hashlib.sha256(archive.read_bytes()).hexdigest() != DEFAULT_SHA256:
        raise ValueError("Rules archive failed pinned hash verification.")
    with tarfile.open(archive) as packed:
        for member in packed.getmembers():
            name = PurePosixPath(member.name)
            if name.is_absolute() or ".." in name.parts or any("\\" in part or ":" in part for part in name.parts):
                raise ValueError("Unsafe archive path.")
            if member.isfile():
                target = rules.joinpath(*name.parts)
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes(packed.extractfile(member).read())
    eligible = [p for p in rules.iterdir() if (p / "rules").is_dir()]
    if len(eligible) != 1:
        raise ValueError("Cannot locate pinned rule pack.")
    return registry.resolve(), eligible[0].resolve()


if __name__ == "__main__":
    print(prepare())
