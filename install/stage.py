#!/usr/bin/env python3
"""Build a private Torque release and workspace before the administrator step."""
import argparse
import base64
import getpass
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import shutil
import stat
import subprocess
import sys
import tarfile
import tempfile
import urllib.request
import warnings

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts'))
sys.path.insert(0, str(ROOT / 'install'))
from torque_bundle import FIRMWARE_VERSION, bundle_identity, application_version
from fx_common import SetupError, atomic_write, discover_models, load_catalog, saved_key, select_model, validate_key
from controller_common import require_board

NODE = '24.22.1'
LIBFX_INTEGRITY = '8wIEkRlKuQnbueyt6NBwi4xEiEnoRpwvAocKolzzmyz/r14s4gXiE3XivGk4QJpNnMMGHAJRKlH0WhW//q7B5Q=='


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def file_manifest(stage):
    stage = Path(stage)
    return {'files': {str(p.relative_to(stage)): digest(p) for p in sorted(stage.rglob('*'))
                      if p.is_file() and not p.is_symlink() and
                      not any(x in p.relative_to(stage).parts for x in ('__pycache__', '.cache'))},
            'links': {str(p.relative_to(stage)): os.readlink(p) for p in stage.rglob('*') if p.is_symlink()}}


def source_fingerprint(root):
    root = Path(root)
    result = hashlib.sha256()
    for path in sorted(root.rglob('*')):
        relative = path.relative_to(root)
        if any(p.startswith('.') or p in ('build', 'dist', '__pycache__', 'node_modules') or p.endswith('.egg-info') for p in relative.parts):
            continue
        if relative.parts[0] == 'projects' or not path.is_file():
            continue
        result.update(str(relative).encode() + b'\0' + path.read_bytes())
    return result.hexdigest()


def copy_source(target):
    def ignore(directory, entries):
        return [name for name in entries if name in ('.git', '.cache', '.venv', '__pycache__', 'node_modules', 'build', 'dist')
                or name.startswith('._') or name.endswith(('.egg-info', '.pyc')) or
                (Path(directory) == ROOT and name == 'projects')]
    shutil.copytree(ROOT, target, ignore=ignore)


def extract(archive, target, strip=False):
    with tarfile.open(archive) as bundle:
        members = bundle.getmembers()
        for member in members:
            path = Path(member.name)
            if path.is_absolute() or '..' in path.parts or not (member.isfile() or member.isdir() or member.issym()):
                raise RuntimeError('Unsafe release archive')
            if member.issym() and Path(member.linkname).is_absolute():
                raise RuntimeError('Unexpected absolute archive link')
            if strip:
                member.name = str(Path(*path.parts[1:])) if len(path.parts) > 1 else '.'
            if member.issym() and not (target / member.name).parent.joinpath(member.linkname).resolve().is_relative_to(target.resolve()):
                raise RuntimeError('Archive link escapes the release')
        bundle.extractall(target, members=members, filter='data')


def dependencies(stage, cache):
    cache.mkdir(parents=True, exist_ok=True)
    name = f'node-v{NODE}-linux-arm64.tar.xz'
    archive = cache / name
    base = f'https://nodejs.org/dist/v{NODE}/'
    sums = urllib.request.urlopen(base + 'SHASUMS256.txt', timeout=30).read().decode()
    expected = next(line.split()[0] for line in sums.splitlines() if line.split()[-1] == name)
    if not archive.exists() or digest(archive) != expected:
        with urllib.request.urlopen(base + name, timeout=60) as response, archive.open('wb') as output:
            shutil.copyfileobj(response, output)
    if digest(archive) != expected:
        raise RuntimeError('Node download integrity mismatch')
    extract(archive, stage / 'runtime/node', strip=True)
    archive = cache / 'libfx-0.0.14.tgz'
    if not archive.exists():
        archive.write_bytes(urllib.request.urlopen('https://registry.npmjs.org/libfx/-/libfx-0.0.14.tgz', timeout=60).read())
    if base64.b64encode(hashlib.sha512(archive.read_bytes()).digest()).decode() != LIBFX_INTEGRITY:
        raise RuntimeError('libfx download integrity mismatch')
    extract(archive, stage / 'node_modules/libfx', strip=True)
    spec = importlib.util.spec_from_file_location('prepare', ROOT / 'scripts/prepare-controller.py')
    prepare = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(prepare)
    prepare.install_client(stage / 'runtime/python')
    return {'node_sha256': expected, 'libfx_sha512': LIBFX_INTEGRITY}


def seed_workspace(workspace):
    workspace.mkdir(parents=True, exist_ok=True)
    for name in ('projects', 'skills'):
        (workspace / name).mkdir(exist_ok=True)
    instructions = workspace / 'AGENTS.md'
    if not instructions.exists():
        shutil.copyfile(ROOT / 'templates/workspace/AGENTS.md', instructions)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--reuse-fx-key', action='store_true', help='Privately import the existing owner-only Modular credential')
    parser.add_argument('--replace-key', action='store_true')
    parser.add_argument('--model')
    parser.add_argument('--stage-only', action='store_true')
    parser.add_argument('--enable-unattended-updates', action='store_true',
                        help='Enable the reviewed Linux runtime update delegation after fresh installation')
    args = parser.parse_args(argv)
    try:
        os.umask(0o022)
        require_board()
        if os.geteuid() == 0:
            raise RuntimeError('Run setup as the board user; only the final system step uses sudo')
        home = Path.home()
        config = home / '.config/torque'
        key_path = config / 'credentials/modular-api-key'
        key = None
        if key_path.exists() and not args.replace_key:
            info = key_path.lstat()
            if not stat.S_ISREG(info.st_mode) or info.st_uid != os.getuid() or stat.S_IMODE(info.st_mode) != 0o600:
                raise RuntimeError('Unsafe existing Torque credential file')
            key = validate_key(key_path.read_text().strip())
        if key is None and args.reuse_fx_key and not args.replace_key:
            key = saved_key(home)
        if key is None:
            # getpass must have a private terminal; do not allow its echoing fallback.
            with open('/dev/tty', 'r+') as tty:
                with warnings.catch_warnings():
                    warnings.simplefilter('error', getpass.GetPassWarning)
                    key = validate_key(getpass.getpass('Modular API key (hidden): ', stream=tty))
        catalog = load_catalog()
        visible = discover_models(key)
        model = select_model(catalog, visible, args.model)
        config.mkdir(mode=0o700, parents=True, exist_ok=True)
        key_path.parent.mkdir(mode=0o700, exist_ok=True)
        os.chmod(config, 0o700)
        os.chmod(key_path.parent, 0o700)
        atomic_write(key_path, (key + '\n').encode())
        del key
        workspace = home / 'torque'
        seed_workspace(workspace)
        release = application_version(ROOT) + '-' + source_fingerprint(ROOT)[:12]
        cache = home / '.cache/torque'
        stage = cache / 'staging' / release
        if stage.exists():
            shutil.rmtree(stage)
        stage.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        print('Staging Torque ' + release + '; user projects and global fx settings are preserved.', flush=True)
        copy_source(stage)
        integrity = dependencies(stage, cache / 'downloads')
        from controller_common import source_hash
        preflight = cache / 'firmware-preflight'
        previous = json.loads((preflight / 'build.json').read_text()) if (preflight / 'build.json').exists() else {}
        valid = (previous.get('source_sha256') == source_hash() and previous.get('profile_resolved') is True
                 and bool(previous.get('artifacts')) and all((preflight / name).is_file() and digest(preflight / name) == checksum
                     for name, checksum in previous.get('artifacts', {}).items()))
        if not valid:
            subprocess.run([sys.executable, str(stage / 'scripts/prepare-controller.py'), '--resolve'],
                           check=True, timeout=1100)
            built = stage / '.cache/base-controller'
            preflight.mkdir(exist_ok=True)
            shutil.copyfile(built / 'build.json', preflight / 'build.json')
            for binary in (built / 'build').glob('*.bin'):
                shutil.copyfile(binary, preflight / binary.name)
        else:
            print('Reusing the verified compile for the unchanged controller source.', flush=True)
        artifacts = stage / 'firmware/uno-q/artifacts'
        artifacts.mkdir()
        shutil.copyfile(preflight / 'build.json', artifacts / 'build.json')
        for binary in preflight.glob('*.bin'):
            shutil.copyfile(binary, artifacts / binary.name)
        models = {name: {''.join([parts[0], *[p.title() for p in parts[1:]]]): value
                         for key, value in metadata.items() for parts in [key.split('_')]}
                  for name, metadata in catalog['provider']['model_metadata'].items() if name in visible}
        settings = {'schema': 1, 'release_root': '/opt/torque/current', 'workspace': str(workspace),
                    'state_dir': '/var/lib/torque', 'socket': '/run/torque/control.sock',
                    'key_file': str(key_path), 'model': model, 'models': models,
                    'node': '/opt/torque/current/runtime/node/bin/node',
                    'python': '/opt/torque/current/runtime/python/bin/python',
                    'libfx_path': '/opt/torque/current/node_modules/libfx'}
        settings_path = config / 'settings.json'
        if settings_path.exists():
            atomic_write(config / 'settings.before-install.json', settings_path.read_bytes())
        atomic_write(settings_path, (json.dumps(settings, indent=2) + '\n').encode())
        manifest = {'release': release, 'engine': 'libfx@0.0.14', 'node': NODE,
                    **bundle_identity(), **integrity,
                    **file_manifest(stage)}
        atomic_write(stage / 'release.json', (json.dumps(manifest, indent=2) + '\n').encode())
        print('Staged release: ' + str(stage), flush=True)
        command = ['sudo', 'python3', str(stage / 'install/system.py'), '--stage', str(stage), '--user', getpass.getuser(), '--install-controller']
        if args.enable_unattended_updates:
            command.append('--enable-unattended-updates')
        import shlex
        print(f'System installation will select the controller at boot and may upload its {FIRMWARE_VERSION} firmware.\n' + shlex.join(command), flush=True)
        if not args.stage_only:
            return subprocess.call(command)
        return 0
    except (SetupError, RuntimeError, OSError, ValueError, getpass.GetPassWarning, subprocess.SubprocessError) as error:
        print('Torque setup: ' + str(error), file=sys.stderr)
        return 1


if __name__ == '__main__':
    sys.exit(main())
