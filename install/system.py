#!/usr/bin/env python3
"""Install a verified staged Torque bundle. Run only this final step as root."""
import argparse
import base64
import grp
import hashlib
import json
import os
from pathlib import Path
import pwd
import re
import shutil
import subprocess
import sys
import time

sys.path.insert(0, str(Path(__file__).resolve().parent))
from torque_bundle import FIRMWARE_VERSION, FIRMWARE_PROTOCOL, bundle_identity, supported_controller

SYSTEM_PATH = '/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin'


def system_tool(name):
    path = shutil.which(name, path=SYSTEM_PATH)
    if path is None:
        raise RuntimeError('Required system tool is unavailable: ' + name)
    return path


def preflight_tools():
    return {name: system_tool(name) for name in
            ('runuser', 'usermod', 'systemctl', 'arduino-app-cli', 'id')}


def run(command, *, user=None, timeout=120, check=True):
    env = {'PATH': SYSTEM_PATH, 'LANG': 'C.UTF-8'}
    command = [system_tool(command[0]) if '/' not in command[0] else command[0], *command[1:]]
    if user:
        account = pwd.getpwnam(user)
        env.update(HOME=account.pw_dir, USER=user, LOGNAME=user)
        if os.geteuid() != account.pw_uid:
            command = [system_tool('runuser'), '-u', user, '--', *command]
    return subprocess.run(command, env=env, capture_output=True, text=True, check=check, timeout=timeout)


def app(command, user, timeout=120):
    return run(['arduino-app-cli', *command, '--format', 'json'], user=user, timeout=timeout).stdout


def wait_for_ready(launcher, user, timeout=45, interval=0.5):
    """Startup/restart status may fail or report not-ready before the socket exists."""
    deadline = time.monotonic() + timeout
    last = 'control socket or device not ready'
    while time.monotonic() < deadline:
        try:
            response = run([str(launcher), 'status', '--json'], user=user, check=False,
                           timeout=min(10, max(0.1, deadline - time.monotonic())))
            status = json.loads(response.stdout)
            if not isinstance(status, dict):
                raise ValueError('Unexpected status response')
            if response.returncode == 0 and status.get('device', {}).get('ready') and status.get('credential_ready'):
                return status
            last = status.get('device', {}).get('error') or status.get('credential_error') or last
        except (OSError, ValueError, subprocess.TimeoutExpired):
            pass
        remaining = deadline - time.monotonic()
        if remaining > 0:
            time.sleep(min(interval, remaining))
    raise RuntimeError('Torque did not become ready before the deadline: ' + str(last))


def verify_stage(stage):
    manifest = json.loads((stage / 'release.json').read_text())
    if not isinstance(manifest.get('files'), dict) or not manifest['files']:
        raise RuntimeError('Release manifest contains no files')
    if any(manifest.get(key) != value for key, value in bundle_identity().items()):
        raise RuntimeError('Staged firmware/protocol does not match this installer bundle')
    release = manifest['release']
    if not isinstance(release, str) or not re.fullmatch(r'\d+\.\d+\.\d+-[a-zA-Z0-9]+', release):
        raise RuntimeError('Invalid release identifier')
    for relative, expected in manifest['files'].items():
        path = stage / relative
        if not path.resolve().is_relative_to(stage.resolve()) or path.is_symlink():
            raise RuntimeError('Unsafe staged release path')
        if hashlib.sha256(path.read_bytes()).hexdigest() != expected:
            raise RuntimeError('Staged release hash mismatch: ' + relative)
    return manifest


def copy_release(stage, target, manifest):
    target.mkdir(parents=True, exist_ok=False)
    try:
        for relative in manifest['files']:
            source, output = stage / relative, target / relative
            output.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(source, output)
            output.chmod(0o755 if source.stat().st_mode & 0o111 else 0o644)
        for relative, link in manifest.get('links', {}).items():
            output = target / relative
            if not output.resolve().is_relative_to(target.resolve()):
                raise RuntimeError('Unsafe release link path')
            # Only venv interpreter links may refer outside the release.
            if Path(link).is_absolute() and link not in ('/usr/bin/python3', '/usr/bin/python3.13'):
                raise RuntimeError('Unexpected external release link')
            if not Path(link).is_absolute() and not (output.parent / link).resolve().is_relative_to(target.resolve()):
                raise RuntimeError('Relative release link escapes the release')
            output.parent.mkdir(parents=True, exist_ok=True)
            output.symlink_to(link)
        shutil.copyfile(stage / 'release.json', target / 'release.json')
    except BaseException:
        shutil.rmtree(target)
        raise


def controller(target, state, user, python):
    stable = state / 'device/uno-q/controller'
    record = {'previous_default': json.loads(app(['properties', 'get', 'default'], user)),
              'previous_apps': json.loads(app(['app', 'ps', '--all'], user))}
    (state / 'before-controller-install.json').write_text(json.dumps(record, indent=2))
    info_code = 'import json;from unoq_control import Board\nwith Board(timeout=2) as b:print(json.dumps(b.info()))'
    probe = lambda: run([str(python), '-c', info_code], user=user, timeout=12, check=False)
    previous = probe()
    identity = json.loads(previous.stdout) if previous.returncode == 0 else {}
    if identity and not supported_controller(identity):
        raise RuntimeError('Unexpected running firmware; inspect it before replacement')
    running = [a for a in (record['previous_apps'].get('apps') or []) if a.get('status') in ('running', 'starting', 'stopping')]
    for entry in running:
        if entry.get('name') != 'UNO Q Base Controller' and entry.get('path') != str(stable):
            raise RuntimeError('Another Arduino app is active; resolve it before this installation')
    for entry in running:
        path = entry.get('path')
        if not path:
            # App IDs are the URL-safe base64 encoding of the canonical path.
            value = entry['id']
            path = base64.urlsafe_b64decode(value + '=' * (-len(value) % 4)).decode()
        app(['app', 'stop', path], user)
    for _ in range(60):
        if not any(a.get('status') in ('running', 'starting', 'stopping')
                   for a in (json.loads(app(['app', 'ps'], user)).get('apps') or [])):
            break
        time.sleep(1)
    else:
        raise RuntimeError('Arduino app did not stop; no upload attempted')
    if stable.exists():
        backup = state / 'controller.previous'
        if backup.exists():
            shutil.rmtree(backup)
        shutil.copytree(stable, backup, ignore=shutil.ignore_patterns('.cache', '__pycache__'))
        shutil.rmtree(stable)
    shutil.copytree(target / 'firmware/uno-q/controller', stable)
    account = pwd.getpwnam(user)
    for directory in [stable, *stable.rglob('*')]:
        os.chown(directory, account.pw_uid, account.pw_gid)
    print(f'Starting the stable Torque controller app; Arduino may compile/upload firmware {FIRMWARE_VERSION}.', flush=True)
    output = app(['app', 'start', str(stable)], user, timeout=1200)
    (state / 'controller-install.json').write_text(output)
    for _ in range(20):
        result = probe()
        current = json.loads(result.stdout) if result.returncode == 0 else {}
        if (current.get('version') == FIRMWARE_VERSION and current.get('protocol') == list(FIRMWARE_PROTOCOL)
                and current.get('ready') is True and current.get('boot_id') != identity.get('boot_id')):
            record['identity'] = current
            break
        time.sleep(1)
    else:
        raise RuntimeError('Expected fresh controller identity was not verified; no automatic reflash')
    app(['properties', 'set', 'default', str(stable)], user)
    record['default'] = str(stable)
    return record


def prepared_controller(target, state, user, python):
    """Recognize a completed controller step after an interrupted installation."""
    stable = state / 'device/uno-q/controller'
    source = target / 'firmware/uno-q/controller'
    if not stable.is_dir():
        return None
    for path in source.rglob('*'):
        relative = path.relative_to(source)
        if any(part.startswith('.') or part in ('build', '__pycache__') for part in relative.parts):
            continue
        if path.is_file() and path.suffix in ('.ino', '.h', '.hpp', '.c', '.cc', '.cpp', '.yaml', '.py', '.txt'):
            deployed = stable / relative
            if not deployed.is_file() or hashlib.sha256(path.read_bytes()).digest() != hashlib.sha256(deployed.read_bytes()).digest():
                return None
    stable_id = base64.urlsafe_b64encode(str(stable).encode()).decode().rstrip('=')
    running = any(a.get('id') == stable_id and a.get('status') == 'running'
                  for a in (json.loads(app(['app', 'ps', '--all'], user)).get('apps') or []))
    # App CLI's ps output can report default=false for an external app even
    # when the authoritative startup property points at it.
    default = json.loads(app(['properties', 'get', 'default'], user)).get('app') or {}
    selected_path = default.get('FullPath')
    if not running or not isinstance(selected_path, str) or Path(selected_path).resolve() != stable.resolve():
        return None
    code = 'import json;from unoq_control import Board\nwith Board(timeout=2) as b:print(json.dumps(b.info()))'
    result = run([str(python), '-c', code], user=user, timeout=12, check=False)
    identity = json.loads(result.stdout) if result.returncode == 0 else {}
    if identity.get('version') != FIRMWARE_VERSION or identity.get('protocol') != list(FIRMWARE_PROTOCOL) or identity.get('ready') is not True:
        return None
    previous = state / 'before-controller-install.json'
    record = json.loads(previous.read_text()) if previous.exists() else {}
    return {**record, 'identity': identity, 'default': str(stable)}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--stage', type=Path, required=True)
    parser.add_argument('--user', required=True)
    parser.add_argument('--install-controller', action='store_true', required=True)
    parser.add_argument('--reboot', action='store_true')
    parser.add_argument('--enable-unattended-updates', action='store_true',
                        help='Run the explicit administrator bootstrap after installation')
    args = parser.parse_args(argv)
    try:
        if os.geteuid() != 0:
            raise RuntimeError('This system installation step requires sudo')
        os.umask(0o022)
        preflight_tools()  # Resolve administrator binaries before any installation changes.
        account = pwd.getpwnam(args.user)
        if account.pw_uid == 0:
            raise RuntimeError('Torque must run as a normal user')
        identity = run(['id', '-u'], user=args.user)
        if identity.stdout.strip() != str(account.pw_uid):
            raise RuntimeError('Could not verify the normal-user execution context')
        stage = args.stage.resolve()
        manifest = verify_stage(stage)
        required = {'install/system.py', 'install/torque_bundle.py', 'runtime/python/bin/python', 'runtime/node/bin/node',
                    'engines/fx/worker.mjs', 'assets/status.json', 'agent/AGENTS.md',
                    'firmware/uno-q/controller/app.yaml'}
        if not required <= set(manifest['files']) | set(manifest.get('links', {})):
            raise RuntimeError('Release manifest omits required runtime components')
        launcher = Path('/usr/local/bin/torque')
        if launcher.exists() and 'opt/torque/current' not in launcher.read_text():
            raise RuntimeError('An unrelated torque executable occupies /usr/local/bin/torque')
        unit = Path('/etc/systemd/system/torque.service')
        if unit.exists() and 'Torque resident agent' not in unit.read_text():
            raise RuntimeError('An unrelated torque.service already exists')
        target = Path('/opt/torque/releases') / manifest['release']
        state = Path('/var/lib/torque')
        state.mkdir(mode=0o700, parents=True, exist_ok=True)
        os.chown(state, account.pw_uid, account.pw_gid)
        if (state / 'session.json').exists() and json.loads((state / 'session.json').read_text()).get('active'):
            raise RuntimeError('A Torque turn is active; finish or cancel it before maintenance')
        # A stopped service releases its router subscription and writer lock.
        run(['systemctl', 'stop', 'torque.service'], check=False)
        if not target.exists():
            copy_release(stage, target, manifest)
        elif json.loads((target / 'release.json').read_text()) != manifest:
            raise RuntimeError('Installed release identifier collision')
        run([str(target / 'runtime/python/bin/python'), '-c', 'import torque,unoq_control'], user=args.user)
        backend = 'const m=await import(' + json.dumps(str(target / 'node_modules/libfx/node.js')) + ');const b=await m.getBackendInfo({surface:"agent",backend:"native"});if(b.backend!=="native")process.exit(1)'
        run([str(target / 'runtime/node/bin/node'), '--input-type=module', '-e', backend], user=args.user)
        group = grp.getgrnam('arduino-router')
        if args.user not in group.gr_mem and account.pw_gid != group.gr_gid:
            run(['usermod', '-aG', 'arduino-router', args.user])
        current = Path('/opt/torque/current')
        previous = str(current.resolve()) if current.is_symlink() else None
        installed_file = state / 'installed.json'
        installed = json.loads(installed_file.read_text()) if installed_file.exists() else {}
        prepared = prepared_controller(target, state, args.user, target / 'runtime/python/bin/python')
        if prepared:
            record = {**installed, **prepared}
            print('Matching controller source and identity are already running and selected at boot; no upload repeated.', flush=True)
        else:
            record = controller(target, state, args.user, target / 'runtime/python/bin/python')
        if current.exists() and not current.is_symlink():
            raise RuntimeError('Torque current path is not a managed symlink')
        temporary = current.with_name('.current-new')
        temporary.unlink(missing_ok=True)
        temporary.symlink_to(target)
        os.replace(temporary, current)
        launcher.write_text('#!/bin/sh\nexec /opt/torque/current/runtime/python/bin/python -m torque.cli "$@"\n')
        launcher.chmod(0o755)
        service = (target / 'install/torque.service').read_text().replace('@USER@', args.user).replace('@HOME@', account.pw_dir)
        unit.write_text(service)
        unit.chmod(0o644)
        record.update(release=manifest['release'], previous_release=previous,
                      managed_paths=[str(target), str(current), str(launcher), str(unit), str(state)])
        (state / 'installed.json').write_text(json.dumps(record, indent=2) + '\n')
        os.chown(state / 'installed.json', account.pw_uid, account.pw_gid)
        run(['systemctl', 'daemon-reload'])
        run(['systemctl', 'enable', '--now', 'torque.service'])
        wait_for_ready(launcher, args.user, timeout=60)
        if args.enable_unattended_updates:
            run([sys.executable,'-I',str(target/'install/bootstrap-runtime-updates.py'),
                 '--stage',str(stage),'--user',args.user,'--apply'],timeout=900)
        print('Torque installed. User projects, credentials, global fx and the prototype source were preserved.\n'
              f'Start with: cd {account.pw_dir}/torque && torque', flush=True)
        if args.reboot:
            run(['systemctl', 'reboot'])
        return 0
    except (OSError, ValueError, RuntimeError, subprocess.SubprocessError) as error:
        print('Torque system install stopped: ' + str(error) + '\n'
              'No automatic recovery flash was attempted. Inspect the stable app and previous installation record.', file=sys.stderr)
        return 1


if __name__ == '__main__':
    sys.exit(main())
