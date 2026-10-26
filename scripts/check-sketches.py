#!/usr/bin/env python3
"""Compile MCU sketches without uploading. --resolve fetches pinned profile dependencies."""
import argparse
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[1]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('apps', nargs='*', type=Path, help='Directories containing sketch/; default: base controller')
    parser.add_argument('--build-dir', type=Path, help='Keep build artifacts here (one sketch only)')
    parser.add_argument('--library', action='append', default=[], type=Path,
                        help='Additional already-installed Arduino library root')
    parser.add_argument('--resolve', action='store_true',
                        help='Allow Arduino CLI to fetch pinned profile libraries/tools into its cache')
    args = parser.parse_args()
    if args.resolve and args.library:
        parser.error('--resolve uses profile dependencies; omit --library')
    binary = shutil.which('arduino-cli')
    if not binary:
        parser.error('arduino-cli is required on the UNO Q')
    apps = args.apps or [ROOT / 'firmware/uno-q/controller']
    if args.build_dir and len(apps) != 1:
        parser.error('--build-dir requires exactly one sketch')
    failed = False
    for app in apps:
        source = app / 'sketch'
        if not (source / 'sketch.ino').is_file():
            print('Missing sketch/sketch.ino: ' + str(app), file=sys.stderr)
            failed = True
            continue
        with tempfile.TemporaryDirectory(prefix='unoq-compile-') as temp:
            stage = Path(temp) / 'sketch'
            ignored = ['.cache', '.venv', '__pycache__'] + ([] if args.resolve else ['sketch.yaml'])
            shutil.copytree(source, stage, ignore=shutil.ignore_patterns(*ignored))
            target_flags = ['--profile', 'default'] if args.resolve else ['--fqbn', 'arduino:zephyr:unoq']
            build = args.build_dir.resolve() if args.build_dir else Path(temp) / 'build'
            build.mkdir(parents=True, exist_ok=True)
            command = [binary, 'compile', *target_flags, '--jobs', '2',
                       '--build-path', str(build)]
            for library in args.library:
                command.extend(['--library', str(library.resolve())])
            command.append(str(stage))
            print('Compiling (no upload): ' + app.name, flush=True)
            try:
                result = subprocess.run(command, timeout=900 if args.resolve else 300)
                failed = failed or result.returncode != 0
            except subprocess.TimeoutExpired:
                print('Compilation timed out.', file=sys.stderr)
                failed = True
    return 1 if failed else 0


if __name__ == '__main__':
    sys.exit(main())
