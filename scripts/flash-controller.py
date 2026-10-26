#!/usr/bin/env python3
"""Deliberately deploy the prepared controller through App CLI, then verify identity."""
import argparse
import base64
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import time
from controller_common import CACHE, FIRMWARE, ROOT, clean_env, require_board, source_hash, firmware_version


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--replace-firmware', action='store_true', required=True,
                        help='Explicitly replace the current MCU sketch and running Arduino app')
    parser.add_argument('--venv', type=Path, default=ROOT / 'packages/device/.venv')
    args = parser.parse_args(argv)
    try:
        require_board()
        if not shutil.which('arduino-app-cli'):
            raise RuntimeError('arduino-app-cli is required for this deployment path.')
        manifest = json.loads((CACHE / 'build.json').read_text())
        expected = firmware_version()
        if (manifest.get('source_sha256') != source_hash() or not manifest.get('profile_resolved') or
                manifest.get('firmware_version') != expected):
            raise RuntimeError('Run prepare-controller.py --client --resolve for the current source first.')
        probe = args.venv.resolve() / 'bin/unoq-control'
        if not probe.is_file():
            raise RuntimeError('Native client missing. Run prepare-controller.py --client-only first.')
        if not os.access('/var/run/arduino-router.sock', os.W_OK):
            raise RuntimeError('Router socket access is required before deployment. No upload or permission change was attempted.')
        print('Current Arduino app (an autonomous MCU sketch can also be running):', flush=True)
        previous = subprocess.run(['arduino-app-cli', 'app', 'ps', '--format', 'json'],
                                  capture_output=True, text=True, env=clean_env(), check=True, timeout=30)
        print(previous.stdout, flush=True)
        (CACHE / 'before-deployment.json').write_text(previous.stdout)
        prior = subprocess.run([str(probe), '--timeout', '2', 'info'], capture_output=True,
                               text=True, env=clean_env(), timeout=10)
        prior_identity = json.loads(prior.stdout) if prior.returncode == 0 else {}
        prior_boot = prior_identity.get('boot_id')
        print('Replacing the MCU sketch with base-controller; boot defaults are preserved.', flush=True)
        # App CLI 0.14 restart can race its asynchronous stop. Wait explicitly.
        target_id = base64.urlsafe_b64encode(str(FIRMWARE.resolve()).encode()).decode().rstrip('=')
        active = ('starting', 'running', 'stopping')
        apps = json.loads(previous.stdout).get('apps') or []
        if any(app.get('id') == target_id and app.get('status') in active for app in apps):
            subprocess.run(['arduino-app-cli', 'app', 'stop', str(FIRMWARE)],
                           env=clean_env(), check=True, timeout=120)
            for _ in range(30):
                status = subprocess.run(['arduino-app-cli', 'app', 'ps', '--format', 'json'],
                                        capture_output=True, text=True, env=clean_env(), check=True, timeout=30)
                apps = json.loads(status.stdout).get('apps') or []
                if not any(app.get('id') == target_id and app.get('status') in active for app in apps):
                    break
                time.sleep(1)
            else:
                raise RuntimeError('Existing controller app did not stop; no start or reflash was attempted.')
        # App CLI prepares and uploads from this reviewed source. It may recompile;
        # the compile manifest records the preflight build, not a flashed binary hash.
        subprocess.run(['arduino-app-cli', 'app', 'start', str(FIRMWARE)],
                       env=clean_env(), check=True, timeout=1200)
        for _ in range(15):
            result = subprocess.run([str(probe), '--timeout', '2', 'info'],
                                    capture_output=True, text=True, env=clean_env(), timeout=10)
            identity = json.loads(result.stdout) if result.returncode == 0 else {}
            if (identity.get('name') == 'base-controller' and identity.get('version') == expected and
                    identity.get('ready') is True and (prior_boot is None or identity.get('boot_id') != prior_boot)):
                print(result.stdout, flush=True)
                print('Controller identity verified. Physical LEDs have not been observed by this script.')
                return 0
            time.sleep(1)
        raise RuntimeError('Deployment returned, but the expected controller version was not verified. Inspect app logs; no automatic reflash was attempted.')
    except (RuntimeError, ValueError, OSError, subprocess.SubprocessError) as error:
        print('Flash controller: ' + str(error), file=sys.stderr)
        return 1


if __name__ == '__main__':
    sys.exit(main())
