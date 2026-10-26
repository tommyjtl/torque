#!/usr/bin/env python3
"""Read-only board diagnostics. No network requests or environment dumps."""
import json
import os
from pathlib import Path
import platform
import shutil
import subprocess
from fx_common import SetupError, fx_path, saved_key


def command(args):
    try:
        result = subprocess.run(args, capture_output=True, text=True, timeout=15)
        return {'exit_code': result.returncode, 'output': result.stdout.strip()[:1500]}
    except (OSError, subprocess.TimeoutExpired):
        return {'available': False}


def main():
    home = Path.home()
    report = {'os': platform.system(), 'architecture': platform.machine()}
    device = Path('/sys/firmware/devicetree/base/compatible')
    report['device_compatible'] = device.read_bytes().rstrip(b'\0').decode().split('\0') if device.exists() else []
    binary = fx_path(home)
    report['fx'] = command([binary, '--version']) if binary else {'available': False}
    try:
        report['saved_credential_available'] = bool(saved_key(home))
    except (SetupError, OSError):
        report['saved_credential_available'] = False
        report['credential_issue'] = 'Check owner, mode 600, and a single nonempty line; no symlinks.'
    report['shell_credential_available'] = bool(os.environ.get('MODULAR_API_KEY'))
    for name in ['arduino-app-cli', 'arduino-cli']:
        report[name] = command([name, 'version']) if shutil.which(name) else {'available': False}
    if shutil.which('systemctl'):
        report['services'] = {name: command(['systemctl', 'is-active', name])
                              for name in ['arduino-app-cli', 'arduino-router', 'docker']}
    report['user_led'] = {name: {'present': (Path('/sys/class/leds') / name).exists(),
                                  'writable': os.access(Path('/sys/class/leds') / name / 'brightness', os.W_OK)}
                          for name in ['red:user', 'green:user', 'blue:user']}
    mem = Path('/proc/meminfo')
    if mem.exists():
        report['memory'] = {line.split(':')[0]: line.split(':')[1].strip() for line in mem.read_text().splitlines()
                            if line.startswith(('MemTotal:', 'MemAvailable:'))}
    print(json.dumps(report, indent=2))


if __name__ == '__main__':
    main()
