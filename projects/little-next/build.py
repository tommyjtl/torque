#!/usr/bin/env python3
"""Assemble a checksummed, self-contained launcher release."""
import hashlib
import json
import shutil
from pathlib import Path

ROOT = Path(__file__).resolve().parent
COMMON = ROOT.parent / "retro-infinite-proxy"
VERSION = "0.1.0"
DEST = ROOT / "releases" / VERSION


def main():
    if DEST.exists():
        raise SystemExit(f"Release already exists: {DEST}")
    inputs = {
        COMMON / "serve.py": "serve.py",
        COMMON / "embed.html": "embed.html",
        COMMON / "LICENSE-infinite-mac": "LICENSE-infinite-mac",
        ROOT / "launch.sh": "launch.sh",
        ROOT / "README.md": "README.md",
    }
    missing = [str(source) for source in inputs if not source.is_file()]
    if missing:
        raise SystemExit("Missing inputs:\n" + "\n".join(missing))
    checksums = {}
    for source, name in inputs.items():
        target = DEST / name
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, target)
        checksums[name] = hashlib.sha256(target.read_bytes()).hexdigest()
    (DEST / "manifest.json").write_text(json.dumps({"version": VERSION, "files_sha256": checksums}, indent=2) + "\n")
    print(f"Built {DEST}")


if __name__ == "__main__":
    main()
