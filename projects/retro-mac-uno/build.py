#!/usr/bin/env python3
"""Assemble an immutable, checksummed local release from the macemu checkout."""
import hashlib
import json
import shutil
from pathlib import Path

ROOT = Path(__file__).resolve().parent
SOURCE = ROOT.parent / "retro-mac-browser"
VERSION = "0.1.11"
DEST = ROOT / "releases" / VERSION


def main():
    if DEST.exists():
        raise SystemExit(f"Release already exists: {DEST}; use a new version")
    manifests = [json.loads((SOURCE / "public/mac/disks" / (name + ".json")).read_text()) for name in ("system-7.5.3", "macos-8.0", "macos-8.5", "torque-macpaint-apps")]
    files = {
        ROOT / "index.html": "www/index.html",
        SOURCE / "public/mac/disks/system-7.5.3.json": "www/mac/disks/system-7.5.3.json",
        SOURCE / "public/mac/disks/macos-8.5.json": "www/mac/disks/macos-8.5.json",
        SOURCE / "public/mac/disks/macos-8.0.json": "www/mac/disks/macos-8.0.json",
        SOURCE / "public/mac/disks/torque-macpaint-apps.json": "www/mac/disks/torque-macpaint-apps.json",
        SOURCE / "Images/rom/Mac-IIfx.rom": "www/rom/Mac-IIfx.rom",
        SOURCE / "Images/rom/Power-Macintosh-9500.rom": "www/rom/Power-Macintosh-9500.rom",
        SOURCE / "Images/rom/Quadra-650.rom": "www/rom/Quadra-650.rom",
        ROOT / "serve.py": "serve.py",
        ROOT / "choose.py": "choose.py",
        ROOT / "launch.sh": "launch.sh",
        ROOT / "README.md": "README.md",
        ROOT.parent / "retro-infinite-proxy/serve.py": "infinite_proxy.py",
        ROOT.parent / "retro-infinite-proxy/embed.html": "embed.html",
        ROOT.parent / "retro-infinite-proxy/LICENSE-infinite-mac": "LICENSE-infinite-mac",
        SOURCE / "LICENSE": "LICENSE-macemu",
        SOURCE / "public/mac/NOTICE.md": "NOTICE-macemu.md",
        SOURCE / "notices/macpaint.md": "NOTICE-macpaint.md",
    }
    for name in ("mac-runtime.js", "worker.js", "emulator-service-worker.js", "emulator-audio-worklet.js", "BasiliskII.js", "BasiliskII.wasm", "SheepShaver.js", "SheepShaver.wasm"):
        files[SOURCE / "public/mac" / name] = "www/mac/" + name
    for chunk in {chunk for manifest in manifests for chunk in manifest["chunks"] if chunk}:
        files[SOURCE / "Images/build" / (chunk + ".chunk")] = "www/Disk/" + chunk + ".chunk"
    missing = [str(p) for p in files if not p.is_file()]
    if missing:
        raise SystemExit("Missing release inputs:\n" + "\n".join(missing))
    # The bundled Emscripten wrappers no longer forward their quit callback to
    # the worker's module overrides. Restore that contract without changing
    # the upstream checkout or WebAssembly. Fail closed if upstream changes.
    quit_anchor = "o=(e,t)=>{throw t}"
    quit_forwarder = "o=(e,t)=>{if(n.quit)n.quit(e,t);throw t}"
    patched = {}
    for name in ("BasiliskII.js", "SheepShaver.js"):
        source = SOURCE / "public/mac" / name
        text = source.read_text()
        if text.count(quit_anchor) != 1:
            raise SystemExit(f"Unexpected Emscripten quit wrapper in {source}")
        patched[source] = text.replace(quit_anchor, quit_forwarder, 1)
    checksums = {}
    for src, target in files.items():
        out = DEST / target
        out.parent.mkdir(parents=True, exist_ok=True)
        if src in patched:
            out.write_text(patched[src])
        else:
            shutil.copy2(src, out)
        checksums[target] = hashlib.sha256(out.read_bytes()).hexdigest()
    (DEST / "manifest.json").write_text(json.dumps({"version": VERSION, "macemu_commit": "a761617608b02931add10c287b5e1dd8f3086ce0", "files_sha256": checksums}, indent=2) + "\n")
    print(f"Built {DEST} ({len(checksums)} files)")


if __name__ == "__main__":
    main()
