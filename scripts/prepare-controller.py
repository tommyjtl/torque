#!/usr/bin/env python3
"""Compile the base controller and optionally install its native Python client. Never upload."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import urllib.request
import venv
from controller_common import CACHE, FIRMWARE, ROOT, clean_env, require_board, source_hash, firmware_version


def install_client(destination):
    destination = Path(destination).resolve()
    python = destination / 'bin/python'
    if not python.exists():
        venv.EnvBuilder(with_pip=False).create(destination)
    check = subprocess.run([str(python), '-c', 'import sys; assert sys.prefix != sys.base_prefix'], env=clean_env())
    if check.returncode:
        raise RuntimeError('Client destination must be a virtual environment.')
    pip = subprocess.run([str(python), '-m', 'pip', '--version'], capture_output=True, env=clean_env())
    if pip.returncode:
        # Debian may omit ensurepip. Use PyPA's supported bootstrap inside this venv only.
        print('Installing pip 26.2.2 inside the project environment.', flush=True)
        with tempfile.TemporaryDirectory(prefix='unoq-pip-') as temp:
            script = Path(temp) / 'get-pip.py'
            with urllib.request.urlopen('https://bootstrap.pypa.io/get-pip.py', timeout=30) as response:
                data = response.read(4 * 1024 * 1024 + 1)
            if len(data) > 4 * 1024 * 1024:
                raise RuntimeError('pip bootstrap exceeded its download limit.')
            script.write_bytes(data)
            subprocess.run([str(python), str(script), '--isolated', '--no-input', 'pip==26.2.2'],
                           env=clean_env(), check=True, timeout=300)
    subprocess.run([str(python), '-m', 'pip', '--isolated', '--disable-pip-version-check',
                    'install', '--no-input', str(ROOT / 'packages/device'), str(ROOT)],
                   env=clean_env(), check=True, timeout=300)
    print('Client installed: ' + str(destination / 'bin/unoq-control') + ' info', flush=True)
    if not os.access('/var/run/arduino-router.sock', os.W_OK):
        print('Native control pending: local router socket access is unavailable. No access settings were changed.', flush=True)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--client', action='store_true', help='Install the client in packages/device/.venv (network downloads)')
    parser.add_argument('--client-only', action='store_true', help='Install the client without compiling')
    parser.add_argument('--venv', type=Path, default=ROOT / 'packages/device/.venv')
    parser.add_argument('--resolve', action='store_true', help='Allow pinned Arduino profile dependency downloads')
    args = parser.parse_args(argv)
    try:
        require_board()
        if args.client or args.client_only:
            install_client(args.venv)
        if args.client_only:
            return 0
        if not shutil.which('arduino-cli'):
            raise RuntimeError('arduino-cli is missing; no system package was installed.')
        CACHE.mkdir(parents=True, exist_ok=True)
        manifest = CACHE / 'build.json'
        manifest.unlink(missing_ok=True)  # failed builds must not retain a deployable manifest
        fingerprint = source_hash()
        command = [sys.executable, str(ROOT / 'scripts/check-sketches.py'),
                   '--build-dir', str(CACHE / 'build')]
        if args.resolve:
            command.append('--resolve')
        command.append(str(FIRMWARE))
        subprocess.run(command, env=clean_env(), check=True, timeout=1000)
        if fingerprint != source_hash():
            raise RuntimeError('Firmware source changed during compilation; build it again.')
        artifacts = {p.name: hashlib.sha256(p.read_bytes()).hexdigest()
                     for p in (CACHE / 'build').glob('*.bin') if p.is_file()}
        if not artifacts:
            raise RuntimeError('Compilation produced no firmware binary.')
        compiler = subprocess.run(['arduino-cli', 'version'], capture_output=True, text=True,
                                  env=clean_env(), check=True).stdout.strip()
        manifest.write_text(json.dumps({'source_sha256': fingerprint, 'firmware_version': firmware_version(), 'fqbn': 'arduino:zephyr:unoq',
                                       'compiler': compiler, 'profile_resolved': args.resolve,
                                       'artifacts': artifacts}, indent=2) + '\n')
        print('Compile passed. No firmware uploaded. Manifest: ' + str(manifest))
        return 0
    except (RuntimeError, OSError, subprocess.SubprocessError) as error:
        print('Prepare controller: ' + str(error), file=sys.stderr)
        return 1


if __name__ == '__main__':
    sys.exit(main())
