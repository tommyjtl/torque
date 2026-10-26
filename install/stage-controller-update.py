"""Stage a matched grayscale update without modifying the running release or services."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent))
from torque_bundle import FIRMWARE_VERSION, FIRMWARE_PROTOCOL, bundle_identity, application_version


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def firmware_hash(root):
    h = hashlib.sha256()
    for path in sorted(root.rglob('*')):
        relative = path.relative_to(root)
        if any(p.startswith('.') or p in ('build', '__pycache__') for p in relative.parts):
            continue
        if path.is_file() and path.suffix in ('.ino', '.h', '.hpp', '.c', '.cc', '.cpp', '.yaml', '.py', '.txt'):
            h.update(relative.as_posix().encode() + b'\0' + path.read_bytes())
    return h.hexdigest()


def compiled_artifacts(compiled, fingerprint):
    compiled = compiled.resolve()
    manifest_path = compiled / 'build.json'
    if manifest_path.exists():
        manifest = json.loads(manifest_path.read_text())
        if (manifest.get('source_sha256') != fingerprint or
                manifest.get('firmware_version') != FIRMWARE_VERSION or manifest.get('profile_resolved') is not True):
            raise RuntimeError('Prepared build does not match the current pinned controller source')
        expected = manifest.get('artifacts')
        if not isinstance(expected, dict) or not expected:
            raise RuntimeError('Prepared build has no verified binary artifacts')
        artifacts = {}
        for name, checksum in expected.items():
            if not isinstance(name, str) or Path(name).name != name or not name.endswith('.bin'):
                raise RuntimeError('Invalid prepared artifact path')
            path = compiled / 'build' / name
            if digest(path) != checksum:
                raise RuntimeError('Prepared binary artifact changed')
            artifacts[str(path)] = checksum
    else:
        if fingerprint != firmware_hash(compiled / 'firmware/uno-q/controller'):
            raise RuntimeError('Staged firmware differs from the successful isolated compile')
        artifacts = {str(p): digest(p) for p in (compiled / 'build').glob('*.bin')}
    if not artifacts:
        raise RuntimeError('The successful compile has no retained binary artifacts')
    return artifacts


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source', '--payload', dest='payload', type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument('--compiled', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True, help='New private stage directory')
    args = parser.parse_args()
    payload = args.payload.resolve()
    current = Path('/opt/torque/current').resolve()
    size = sum(p.stat().st_size for p in current.rglob('*') if p.is_file() and not p.is_symlink())
    if shutil.disk_usage(payload.parent).free < size * 2 + 64 * 1024 * 1024:
        raise RuntimeError('Insufficient free space to stage and install a separate rollback-safe release')
    stage = args.output.resolve()
    stage.parent.mkdir(parents=True, exist_ok=True)
    stage.mkdir(mode=0o700)
    release = stage / 'release'
    shutil.copytree(current, release, symlinks=True, ignore=shutil.ignore_patterns('__pycache__', '.cache'))
    # Overlay the firmware, both Python source packages, and reference example.
    # The rest comes from the active release, preserving the other session's work.
    for relative in ('firmware/uno-q/controller', 'packages/device', 'packages/session', 'install',
                     'examples/06-dot-matrix-animations'):
        shutil.copytree(payload / relative, release / relative, dirs_exist_ok=True,
                        ignore=shutil.ignore_patterns('__pycache__', '.cache', '.venv'))
    shutil.copyfile(payload / 'pyproject.toml', release / 'pyproject.toml')
    python = release / 'runtime/python/bin/python'
    clean = {'PATH': '/usr/local/bin:/usr/bin:/bin', 'HOME': str(Path.home()), 'LANG': 'C.UTF-8'}
    log = stage / 'packages.log'
    with log.open('w') as output:
        result = subprocess.run([str(python), '-m', 'pip', '--isolated', '--disable-pip-version-check',
                                 'install', '--no-deps', '--no-cache-dir', '--force-reinstall',
                                 str(release / 'packages/device'), str(release)], env=clean,
                                stdout=output, stderr=subprocess.STDOUT, timeout=300)
    if result.returncode:
        raise RuntimeError('Package build failed; inspect ' + str(log))
    code = ('import sys,importlib.metadata as m;from torque import Frame;'
            f'assert m.version("unoq-control")=={FIRMWARE_VERSION!r};'
            'assert Frame((7,)*104,bits=3).to_hex()=="f"*78;'
            'assert Frame((1,)*104).to_hex()=="f"*26;'
            'print("Matched staged SDK imports and both frame formats passed")')
    subprocess.run([str(python), '-c', code], env=clean, check=True, timeout=30)
    fingerprint = firmware_hash(release / 'firmware/uno-q/controller')
    artifacts = compiled_artifacts(args.compiled, fingerprint)
    old = json.loads((current / 'release.json').read_text())
    files, links = {}, {}
    for path in sorted(release.rglob('*')):
        relative = str(path.relative_to(release))
        if relative == 'release.json' or any(p in ('__pycache__', '.cache') for p in path.relative_to(release).parts):
            continue
        if path.is_symlink():
            links[relative] = os.readlink(path)
        elif path.is_file():
            files[relative] = digest(path)
    identity = application_version(release) + '-' + hashlib.sha256(json.dumps(files, sort_keys=True).encode()).hexdigest()[:12]
    manifest = {**old, 'release': identity, **bundle_identity(),
                'files': files, 'links': links}
    (release / 'release.json').write_text(json.dumps(manifest, indent=2) + '\n')
    plan = dict(previous_release=str(current), release=identity, **bundle_identity(),
                source_sha256=fingerprint, compiled_artifacts=artifacts,
                stable_app='/var/lib/torque/device/uno-q/controller',
                preserves_boot_default=True, preserves_service_configuration=True)
    (stage / 'plan.json').write_text(json.dumps(plan, indent=2) + '\n')
    shutil.copyfile(payload / 'install/update-controller.py', stage / 'update-controller.py')
    print(json.dumps({'stage': str(stage), 'release': identity, **bundle_identity(), 'source_sha256': fingerprint,
                      'packages_checked': True, 'compiled_artifacts': artifacts}, indent=2))


if __name__ == '__main__':
    main()
