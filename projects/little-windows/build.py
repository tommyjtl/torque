#!/usr/bin/env python3
"""Build a checksummed, immutable release from locally downloaded v86 assets."""
import hashlib
import json
import shutil
from pathlib import Path

ROOT = Path(__file__).resolve().parent
VERSION = "0.1.3"
DEST = ROOT / "releases" / VERSION

def main():
    if DEST.exists():
        raise SystemExit(f"Release already exists: {DEST}")
    sources = {ROOT / "index.html": "www/index.html"}
    for name in ("serve.py", "launch.sh", "README.md", "PROVENANCE.md", "LICENSE-v86"):
        sources[ROOT / name] = name
    for name in ("build/libv86.js", "build/v86.wasm", "bios/seabios.bin", "bios/vgabios.bin", "images/windows95-local-640.zst"):
        sources[ROOT / "vendor" / name] = "www/" + name
    missing = [str(path) for path in sources if not path.is_file()]
    if missing:
        raise SystemExit("Missing inputs:\n" + "\n".join(missing))
    checksums = {}
    for source, target in sources.items():
        dest = DEST / target
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, dest)
        checksums[target] = hashlib.sha256(dest.read_bytes()).hexdigest()
    (DEST / "manifest.json").write_text(json.dumps({"version": VERSION, "files_sha256": checksums}, indent=2) + "\n")
    print(f"Built {DEST} ({len(checksums)} files)")

if __name__ == "__main__":
    main()
