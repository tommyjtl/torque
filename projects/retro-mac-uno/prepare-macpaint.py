#!/usr/bin/env python3
"""Create a small HFS applications disk from the locally sourced MacPaint image.

Requires machfs. Run the upstream chunk-disk.mjs on the output afterwards.
"""
import copy
import json
from pathlib import Path

import machfs

source = Path(__file__).resolve().parent.parent / "retro-mac-browser"
manifest = json.loads((source / "public/mac/disks/macpaint-v1.json").read_text())
parts = [
    (source / "Images/build" / (chunk + ".chunk")).read_bytes()
    if chunk else bytes(manifest["chunkSize"])
    for chunk in manifest["chunks"]
]
original = machfs.Volume()
original.read(b"".join(parts)[:manifest["totalSize"]])
application = copy.deepcopy(original["System Folder"]["Startup Items"]["MacPaint"])
if application.type != b"APPL" or application.creator != b"MPNT" or not application.rsrc:
    raise SystemExit("The source does not contain the expected MacPaint application")
application.flags &= ~0x4000  # Make the application visible in the Finder.
output = machfs.Volume()
output.name = "MacPaint"
output["MacPaint"] = application
destination = source / "Images/system/torque-macpaint-apps.dsk"
destination.parent.mkdir(parents=True, exist_ok=True)
destination.write_bytes(output.write(size=4 * 1024 * 1024, desktopdb=True))
print(f"Created {destination}")
