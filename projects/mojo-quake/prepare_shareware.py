"""Prepare a local Quake 1.06 shareware installation and retain the original archive."""
import argparse
import hashlib
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
from urllib.request import urlopen
from zipfile import ZipFile

DISTRIBUTION = "https://ftp.gwdg.de/pub/misc/ftp.idsoftware.com/idstuff/quake/quake106.zip"
ZIP_SHA = "ec6c9d34b1ae0252ac0066045b6611a7919c2a0d78a3a66d9387a8f597553239"
RESOURCE_SHA = "c192c9c71bee41750dd7d14c99378766d61e077977b9d13d1a457b8d9eabe34a"
PAK_SHA = "35a9c55e5e5a284a159ad2a62e0e8def23d829561fe2f54eb402dbc0a9a946af"


def verify(path, expected):
    with path.open("rb") as stream:
        actual = hashlib.file_digest(stream, "sha256").hexdigest()
    if actual != expected:
        raise ValueError(f"Unexpected Quake 1.06 data in {path.name}")


def prepare(directory, archive=None):
    directory.mkdir(exist_ok=True, parents=True)
    with tempfile.TemporaryDirectory(dir=directory) as temporary:
        stage = Path(temporary)
        source = stage / "quake106.zip"
        retained = directory / "archive/quake106.zip"
        if archive is not None or retained.is_file():
            shutil.copyfile(archive or retained, source)
        else:
            with urlopen(DISTRIBUTION, timeout=60) as response, source.open("wb") as output:
                shutil.copyfileobj(response, output)
        verify(source, ZIP_SHA)
        resource = stage / "resource.1"
        with ZipFile(source) as zipped:
            resource.write_bytes(zipped.read("resource.1"))
        verify(resource, RESOURCE_SHA)
        files = {"archive/quake106.zip": source}
        for member in ("ID1/PAK0.PAK", "LICINFO.TXT", "SLICNSE.TXT", "READV106.TXT", "README.TXT"):
            output = stage / Path(member).name
            with output.open("wb") as stream:
                subprocess.run(["bsdtar", "-xOf", resource, member], check=True, stdout=stream)
            files[member.lower() if member.startswith("ID1") else member] = output
        verify(files["id1/pak0.pak"], PAK_SHA)
        for name, path in files.items():
            target = directory / name
            if target.exists() and target.read_bytes() != path.read_bytes():
                raise ValueError(f"Existing file differs: {target}")
        for name, path in files.items():
            target = directory / name
            if not target.exists():
                target.parent.mkdir(parents=True, exist_ok=True)
                os.replace(path, target)
        print(directory / "id1/pak0.pak", PAK_SHA)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("directory", type=Path)
    parser.add_argument("--archive", type=Path)
    args = parser.parse_args()
    prepare(args.directory, args.archive)
