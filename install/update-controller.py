"""Apply the staged matched update, preserving the service unit and boot app path."""
import argparse
import base64
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import pwd
import shutil
import subprocess
import sys
import time

CURRENT = Path('/opt/torque/current')
RELEASES = Path('/opt/torque/releases')
STATE = Path('/var/lib/torque')
LAUNCHER = '/usr/local/bin/torque'
SERVICE_UNIT = Path('/etc/systemd/system/torque.service')


def load_system(source):
    """Older staged installers need only their original four helper functions."""
    spec = importlib.util.spec_from_file_location('staged_torque_system', source / 'install/system.py')
    system = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(system)
    missing = [name for name in ('run', 'app', 'verify_stage', 'copy_release')
               if not callable(getattr(system, name, None))]
    if missing:
        raise RuntimeError('Staged installer is missing required helpers: ' + ', '.join(missing))
    return system


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


def example_project(reference, home, release):
    """Keep edited/older user programs; choose a fresh versioned example folder."""
    def matches(path):
        return (path.is_dir() and not path.is_symlink() and
                all((path/name).is_file() and not (path/name).is_symlink() and
                    (path/name).read_bytes() == (reference/name).read_bytes()
                    for name in ('main.py', 'README.md')))
    for name in ('main.py','README.md'):
        if not (reference/name).is_file():
            raise RuntimeError('Staged animation example is incomplete')
    project = home/'torque/projects/dot-matrix-animations'
    if (project.exists() or project.is_symlink()) and not matches(project):
        project = project.with_name(project.name + '-' + release)
    if (project.exists() or project.is_symlink()) and not matches(project):
        raise RuntimeError('Versioned animation project already differs; no user file was overwritten')
    return project


def wait_for_ready(system, user, timeout=60):
    """Do not assume a readiness helper exists in an older installed release."""
    deadline = time.monotonic() + timeout
    last = 'control socket or device not ready'
    while time.monotonic() < deadline:
        try:
            response = system.run([LAUNCHER, 'status', '--json'],
                                  user=user, check=False,
                                  timeout=min(10, max(0.1, deadline - time.monotonic())))
            state = json.loads(response.stdout)
            if not isinstance(state, dict) or not isinstance(state.get('device'), dict):
                raise ValueError('Unexpected readiness response')
            if response.returncode == 0 and state['device'].get('ready') is True:
                return state
            last = state['device'].get('error') or last
        except (OSError, ValueError, subprocess.TimeoutExpired):
            pass
        remaining = deadline - time.monotonic()
        if remaining > 0:
            time.sleep(min(0.5, remaining))
    raise RuntimeError('Torque did not become ready after the update: ' + str(last))


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--apply', action='store_true')
    parser.add_argument('--user', default='arduino')
    parser.add_argument('--stage', type=Path, required=True, help='Prepared update containing plan.json and release/')
    args = parser.parse_args(argv)
    stage = args.stage.resolve()
    plan = json.loads((stage / 'plan.json').read_text())
    source = stage / 'release'
    current = CURRENT
    system = load_system(source)
    if current.resolve() == (RELEASES / plan['release']).resolve() and (stage / 'applied.json').exists():
        receipt = json.loads((stage / 'applied.json').read_text())
        if receipt.get('release') != plan['release']:
            raise RuntimeError('Update receipt belongs to a different release; no changes performed')
        # Run as the service user even when this command is invoked through sudo.
        state = wait_for_ready(system, args.user)
        code = 'import json;from unoq_control import Board\nwith Board(timeout=2) as b:print(json.dumps(b.info()))'
        response = system.run([str(current / 'runtime/python/bin/python'), '-c', code],
                              user=args.user, timeout=15)
        identity = json.loads(response.stdout)
        if (identity.get('version'), identity.get('protocol'), identity.get('ready')) != (
                plan['firmware'], plan['protocol'], True):
            raise RuntimeError('Update receipt does not match the live firmware; no reflash attempted')
        print(json.dumps({'already_applied': True, 'release': plan['release'],
                          'ready': True, 'no_flash_or_restart_repeated': True}, indent=2))
        return 0
    if str(current.resolve()) != plan['previous_release']:
        raise RuntimeError('Active release changed since staging; prepare this update again')
    manifest = system.verify_stage(source)
    if (manifest['release'], manifest['firmware'], manifest['protocol']) != (
            plan['release'], plan['firmware'], plan['protocol']):
        raise RuntimeError('Staged bundle identity mismatch')
    if firmware_hash(source / 'firmware/uno-q/controller') != plan['source_sha256']:
        raise RuntimeError('Firmware source differs from the preflight build')
    if not plan['compiled_artifacts'] or any(digest(p) != expected for p, expected in plan['compiled_artifacts'].items()):
        raise RuntimeError('Preflight binary artifact changed')
    account = pwd.getpwnam(args.user)
    if account.pw_uid == 0:
        raise RuntimeError('The service account must be a normal user')
    project = example_project(source/'examples/06-dot-matrix-animations', Path(account.pw_dir), manifest['release'])
    run = lambda command, **kw: system.run(command, user=args.user, **kw)
    app = lambda command, **kw: json.loads(system.app(command, args.user, **kw))
    state = json.loads(run([LAUNCHER, 'status', '--json']).stdout)
    if state.get('active') or state.get('pending') or state['device'].get('owner'):
        raise RuntimeError('A turn, approval, or device program is active; finish it before updating')
    if not state['device'].get('ready'):
        raise RuntimeError('Current controller is not healthy; inspect it before updating')
    stable = Path(plan['stable_app'])
    default_before = app(['properties', 'get', 'default'])['app']['FullPath']
    if Path(default_before).resolve() != stable.resolve():
        raise RuntimeError('The boot default is a different app; no boot setting was changed')
    apps = app(['app', 'ps', '--all']).get('apps') or []
    stable_id = base64.urlsafe_b64encode(str(stable).encode()).decode().rstrip('=')
    active = ('running', 'starting', 'stopping')
    if any(a.get('status') in active and a.get('id') != stable_id for a in apps):
        raise RuntimeError('Another Arduino app is active; no app was stopped')
    native_python = current / 'runtime/python/bin/python'
    info_code = 'import json;from unoq_control import Board\nwith Board(timeout=2) as b:print(json.dumps(b.info()))'
    before_info = json.loads(run([str(native_python), '-c', info_code]).stdout)
    if (before_info.get('version'), tuple(before_info.get('protocol', []))) not in (
            ('0.2.0', (1, 1)), ('0.3.0', (1, 2)), (plan['firmware'], tuple(plan['protocol']))):
        raise RuntimeError('Unexpected MCU firmware; no upload attempted')
    config_hash = digest(SERVICE_UNIT)
    report = dict(previous_release=plan['previous_release'], release=plan['release'],
                  previous_firmware=before_info, previous_boot_default=default_before,
                  preserved_service_sha256=config_hash, staged_checks_passed=True)
    if not args.apply:
        print(json.dumps({**report, 'administrator_required': True,
                          'actions': ['stop Torque service', 'activate matched runtime',
                                      'replace and start the existing stable controller app',
                                      'verify firmware ' + plan['firmware'], 'start and verify Torque service'],
                          'no_changes_performed': True}, indent=2))
        return 0
    if os.geteuid() != 0:
        raise RuntimeError('This explicit update requires sudo; no changes performed')
    os.umask(0o022)
    target = RELEASES / manifest['release']
    if target.exists():
        if json.loads((target / 'release.json').read_text()) != manifest:
            raise RuntimeError('Release identifier already exists with different content')
    else:
        system.copy_release(source, target, manifest)
    run([str(target / 'runtime/python/bin/python'), '-c',
         'from torque import Frame;assert Frame((7,)*104,bits=3).to_hex()=="f"*78'])
    # All non-mutating checks and the immutable new release are ready before
    # stopping the current service. No service unit or startup property is edited.
    system.run(['systemctl', 'stop', 'torque.service'])
    restarted = False
    backup = STATE / ('controller.before-' + manifest['release'])
    try:
        link = current.with_name('.current-' + manifest['release'])
        if link.exists() or link.is_symlink():
            raise RuntimeError('Temporary activation path already exists')
        link.symlink_to(target)
        os.replace(link, current)
        # The new runtime supports the known earlier controller bundles, so it can
        # diagnose either state if app upload fails. Never automatically reflash.
        app(['app', 'stop', str(stable)], timeout=120)
        deadline = time.monotonic() + 90
        while any(a.get('id') == stable_id and a.get('status') in active
                  for a in app(['app', 'ps', '--all']).get('apps') or []):
            if time.monotonic() >= deadline:
                raise RuntimeError('Controller app did not stop; no upload attempted')
            time.sleep(1)
        if backup.exists():
            raise RuntimeError('Controller backup already exists; inspect the previous attempt')
        shutil.copytree(stable, backup, ignore=shutil.ignore_patterns('.cache', '__pycache__'))
        report['previous_controller_source'] = str(backup)
        # Replace only known controller sources, leaving app path and boot
        # selection stable. Move the old tree intact as a rollback reference.
        retired = stable.with_name('controller.before-' + manifest['release'])
        if retired.exists():
            raise RuntimeError('Retired controller path already exists')
        stable.rename(retired)
        shutil.copytree(target / 'firmware/uno-q/controller', stable,
                        ignore=shutil.ignore_patterns('.cache', '__pycache__'))
        for path in [stable, *stable.rglob('*')]:
            os.chown(path, account.pw_uid, account.pw_gid)
        print(f'Starting the stable controller app: this compiles/uploads firmware {plan["firmware"]}.', flush=True)
        output = system.app(['app', 'start', str(stable)], args.user, timeout=1200)
        (stage / 'app-start.json').write_text(output)
        python = target / 'runtime/python/bin/python'
        deadline = time.monotonic() + 60
        while True:
            probe = run([str(python), '-c', info_code], check=False, timeout=12)
            try:
                identity = json.loads(probe.stdout) if probe.returncode == 0 else {}
            except ValueError:
                identity = {}
            if (identity.get('version') == plan['firmware'] and identity.get('protocol') == plan['protocol']
                    and identity.get('ready') is True and identity.get('boot_id') != before_info['boot_id']):
                break
            if time.monotonic() > deadline:
                raise RuntimeError('Fresh matching firmware was not verified; no automatic reflash')
            time.sleep(1)
        if app(['properties', 'get', 'default'])['app']['FullPath'] != default_before:
            raise RuntimeError('Boot default unexpectedly changed; inspect it before continuing')
        if digest(SERVICE_UNIT) != config_hash:
            raise RuntimeError('Service configuration unexpectedly changed')
        system.run(['systemctl', 'start', 'torque.service'])
        restarted = True
        ready = wait_for_ready(system, args.user, timeout=60)
        project.mkdir(parents=True, exist_ok=True)
        for name in ('main.py', 'README.md'):
            output = project / name
            reference = target / 'examples/06-dot-matrix-animations' / name
            if output.exists() and output.read_bytes() != reference.read_bytes():
                raise RuntimeError('An existing Dot Matrix Animations project differs; it was not overwritten')
            shutil.copyfile(reference, output)
            os.chown(output, account.pw_uid, account.pw_gid)
        os.chown(project, account.pw_uid, account.pw_gid)
        installed_path = STATE / 'installed.json'
        installed = json.loads(installed_path.read_text())
        installed.update(release=manifest['release'], previous_release=plan['previous_release'],
                         identity=identity, default=default_before)
        installed_path.write_text(json.dumps(installed, indent=2) + '\n')
        os.chown(installed_path, account.pw_uid, account.pw_gid)
        report.update(firmware=identity, ready=ready['device']['ready'],
                      boot_default_preserved=True, service_configuration_preserved=True,
                      animation_project=str(project / 'main.py'), flashed=True,
                      physical_led_observed=False)
        (stage / 'applied.json').write_text(json.dumps(report, indent=2) + '\n')
        print(json.dumps(report, indent=2))
        print('Update verified. Dot Matrix Animations is ready for torque run.', flush=True)
        return 0
    finally:
        if not restarted:
            # Start the matching runtime for diagnosis; do not change the MCU
            # again, restore boot settings, or fabricate a successful update.
            system.run(['systemctl', 'start', 'torque.service'], check=False)


if __name__ == '__main__':
    try:
        raise SystemExit(main())
    except (OSError, ValueError, KeyError, RuntimeError, subprocess.SubprocessError) as error:
        print('Grayscale update stopped: ' + str(error), file=sys.stderr)
        raise SystemExit(1)
