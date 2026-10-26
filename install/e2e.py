#!/usr/bin/env python3
"""Opt-in fresh-install test. Preserve user data; replace only Torque-managed paths."""
import argparse
import getpass
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import pwd
import re
import shlex
import shutil
import stat
import subprocess
import sys
import time
import uuid

ROOT = Path(__file__).resolve().parents[1]
RUN_ID = re.compile(r'[0-9]{8}T[0-9]{6}-[a-f0-9]{8}')


def module(name, root=ROOT):
    spec = importlib.util.spec_from_file_location('e2e_' + name, root / 'install' / (name + '.py'))
    value = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(value)
    return value


def digest(path):
    value = hashlib.sha256()
    with Path(path).open('rb') as stream:
        while block := stream.read(1024 * 1024):
            value.update(block)
    return value.hexdigest()


def save(path, data, owner=None):
    path = Path(path)
    temporary = path.with_name('.' + path.name + '-' + uuid.uuid4().hex)
    try:
        with temporary.open('x') as stream:
            os.chmod(temporary, 0o600)
            json.dump(data, stream, indent=2)
        if owner:
            os.chown(temporary, owner.pw_uid, owner.pw_gid)
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def workspace_snapshot(root):
    root = Path(root)
    result = {}
    if root.exists():
        for path in root.rglob('*'):
            relative = str(path.relative_to(root))
            if path.is_symlink():
                result[relative] = {'link': os.readlink(path)}
            elif path.is_file():
                result[relative] = {'sha256': digest(path)}
    return result


def preserved(plan):
    current = workspace_snapshot(plan['workspace'])
    if any(current.get(path) != expected for path, expected in plan['workspace_before'].items()):
        raise RuntimeError('Existing workspace files changed during the test')
    settings = Path(plan['home']) / '.fx/settings.json'
    actual = digest(settings) if settings.exists() else None
    if actual != plan['global_fx_settings_before']:
        raise RuntimeError('Global FX settings changed during the test')


def load_plan(path):
    path = Path(path).resolve()
    plan = json.loads(path.read_text())
    if not RUN_ID.fullmatch(plan.get('run_id', '')):
        raise RuntimeError('Invalid E2E run identifier')
    account = pwd.getpwnam(plan['user'])
    expected = Path(account.pw_dir) / '.cache/torque/e2e' / plan['run_id']
    if account.pw_uid == 0 or path != expected / 'plan.json' or plan['run_dir'] != str(expected):
        raise RuntimeError('E2E plan is outside the normal user test directory')
    if plan['home'] != account.pw_dir or plan['workspace'] != str(Path(account.pw_dir) / 'torque'):
        raise RuntimeError('Unexpected E2E home/workspace')
    stage = Path(plan['stage']).resolve()
    if stage.parent != Path(account.pw_dir) / '.cache/torque/staging':
        raise RuntimeError('Unexpected staged release location')
    return plan, account


def prepare():
    sys.path.insert(0, str(ROOT / 'scripts'))
    from controller_common import require_board
    require_board()
    if os.geteuid() == 0:
        raise RuntimeError('Prepare the test as the board user')
    home = Path.home()
    credential = home / '.config/torque/credentials/modular-api-key'
    info = credential.lstat()
    if not stat.S_ISREG(info.st_mode) or info.st_uid != os.getuid() or stat.S_IMODE(info.st_mode) != 0o600:
        raise RuntimeError('The existing owner-only Torque credential is required')
    run_id = time.strftime('%Y%m%dT%H%M%S', time.gmtime()) + '-' + uuid.uuid4().hex[:8]
    directory = home / '.cache/torque/e2e' / run_id
    directory.mkdir(mode=0o700, parents=True)
    plan = {'run_id': run_id, 'run_dir': str(directory), 'user': getpass.getuser(),
            'home': str(home), 'workspace': str(home / 'torque'),
            'workspace_before': workspace_snapshot(home / 'torque'),
            'global_fx_settings_before': digest(home / '.fx/settings.json') if (home / '.fx/settings.json').exists() else None,
            'before_linux_boot_id': Path('/proc/sys/kernel/random/boot_id').read_text().strip()}
    staging = module('stage')
    staging.copy_source(directory / 'source')
    (directory / 'source/E2E_RUN.json').write_text(json.dumps({'run_id': run_id, 'purpose': 'fresh installation test'}))
    cache = home / '.cache/torque/firmware-preflight'
    if cache.exists():
        shutil.move(str(cache), directory / 'previous-firmware-cache')
    print('Building a fresh private runtime and recompiling the controller: ' + run_id, flush=True)
    with (directory / 'stage.log').open('w') as log:
        os.chmod(directory / 'stage.log', 0o600)
        result = subprocess.run(['bash', str(directory / 'source/setup.sh'), '--stage-only'],
                                stdout=log, stderr=subprocess.STDOUT)
    if result.returncode:
        raise RuntimeError('Fresh staging failed; inspect ' + str(directory / 'stage.log'))
    prefix = 'Staged release: '
    lines = (directory / 'stage.log').read_text().splitlines()
    plan['stage'] = next(line[len(prefix):] for line in reversed(lines) if line.startswith(prefix))
    module('system').verify_stage(Path(plan['stage']))
    preserved(plan)
    save(directory / 'plan.json', plan)
    command = ['sudo', '/usr/bin/python3', str(Path(plan['stage']) / 'install/e2e.py'),
               'install', '--plan', str(directory / 'plan.json'), '--replace-managed']
    helper = home / '.cache/torque/run-e2e.sh'
    helper.write_text('#!/bin/sh\nset -eu\nexec ' + shlex.join(command) + '\n')
    helper.chmod(0o700)
    (home / '.cache/torque/latest-e2e').write_text(str(directory))
    print('Fresh bundle verified. Run: bash ~/.cache/torque/run-e2e.sh', flush=True)


def archive_entries(entries, backup):
    """Move exact managed entries, retaining all contents for recovery."""
    backup = Path(backup)
    backup.mkdir(mode=0o700)
    moved = []
    for name, path in entries:
        path = Path(path)
        if path.exists() or path.is_symlink():
            shutil.move(str(path), backup / name)
            moved.append(str(path))
    return moved


def reset_managed(system, plan):
    stable = Path('/var/lib/torque/device/uno-q/controller')
    unit = Path('/etc/systemd/system/torque.service')
    launcher = Path('/usr/local/bin/torque')
    opt = Path('/opt/torque')
    state = Path('/var/lib/torque')
    for directory in (opt, state):
        if directory.is_symlink():
            raise RuntimeError('Managed directory is a symlink; inspect before resetting: ' + str(directory))
    if unit.exists() and 'Torque resident agent' not in unit.read_text():
        raise RuntimeError('Refusing to replace an unrelated service')
    if launcher.exists() and 'opt/torque/current' not in launcher.read_text():
        raise RuntimeError('Refusing to replace an unrelated torque command')
    if opt.exists():
        if set(p.name for p in opt.iterdir()) - {'releases', 'current', '.current-new'}:
            raise RuntimeError('Unknown files in /opt/torque; inspect before resetting')
        for release in (opt / 'releases').iterdir() if (opt / 'releases').exists() else []:
            if not (release / 'release.json').is_file():
                raise RuntimeError('Unrecognized managed release')
    session = state / 'session.json'
    if session.exists() and json.loads(session.read_text()).get('active'):
        raise RuntimeError('Finish or cancel the active Torque turn before testing a fresh installation')
    status = json.loads(system.app(['app', 'ps', '--all'], plan['user']))
    identifier = system.base64.urlsafe_b64encode(str(stable).encode()).decode().rstrip('=')
    active = [app for app in (status.get('apps') or []) if app.get('status') in ('running', 'starting', 'stopping')]
    if any(app.get('id') != identifier for app in active):
        raise RuntimeError('Another Arduino app is active; no fresh reset was performed')
    default = json.loads(system.app(['properties', 'get', 'default'], plan['user']))
    save(Path(plan['run_dir']) / 'before-reset.json', {'apps': status, 'default': default}, pwd.getpwnam(plan['user']))
    system.run(['systemctl', 'stop', 'torque.service'], check=False)
    if active:
        system.app(['app', 'stop', str(stable)], plan['user'])
        for _ in range(60):
            apps = json.loads(system.app(['app', 'ps', '--all'], plan['user'])).get('apps') or []
            if not any(a.get('id') == identifier and a.get('status') in ('running', 'starting', 'stopping') for a in apps):
                break
            time.sleep(1)
        else:
            raise RuntimeError('Controller app did not stop; managed files were not moved')
    if (default.get('app') or {}).get('FullPath') == str(stable):
        system.app(['properties', 'set', 'default', 'none'], plan['user'])
    system.run(['systemctl', 'disable', 'torque.service'], check=False)
    moved = archive_entries([('runtime', opt), ('state', state), ('launcher', launcher), ('service', unit)],
                            Path(plan['run_dir']) / 'system-backup')
    system.run(['systemctl', 'daemon-reload'])
    return moved


def unit_text(plan):
    unit = 'torque-e2e-' + plan['run_id'] + '.service'
    # Paths are fixed by load_plan; systemd's argument quoting is not shell quoting.
    quote = lambda text: '"' + str(text).replace('\\', '\\\\').replace('"', '\\"').replace('%', '%%') + '"'
    command = ['/usr/sbin/runuser', '-u', plan['user'], '--',
               '/opt/torque/current/runtime/python/bin/python', '/opt/torque/current/install/e2e.py',
               'after-boot', '--plan', str(Path(plan['run_dir']) / 'plan.json')]
    return unit, ('[Unit]\nDescription=Torque one-time E2E boot verification\nAfter=torque.service\nWants=torque.service\n'
                  '[Service]\nType=oneshot\nExecStart=' + ' '.join(map(quote, command)) + '\n'
                  'TimeoutStartSec=600\n'
                  'ExecStopPost=-/usr/bin/systemctl disable ' + unit + '\n'
                  'ExecStopPost=-/usr/bin/rm -f /etc/systemd/system/' + unit + '\n'
                  '[Install]\nWantedBy=multi-user.target\n')


def install(plan, account):
    if os.geteuid() != 0:
        raise RuntimeError('The fresh system installation requires sudo')
    sys.path.insert(0, str(ROOT / 'scripts'))
    from controller_common import require_board
    require_board()
    system = module('system')
    system.preflight_tools()
    system.verify_stage(Path(plan['stage']))
    preserved(plan)
    print('Archiving only Torque runtime/state; workspace, credentials and global FX are preserved.', flush=True)
    moved = reset_managed(system, plan)
    save(Path(plan['run_dir']) / 'reset.json', {'moved': moved}, account)
    arguments = ['--stage', plan['stage'], '--user', plan['user'], '--install-controller']
    if system.main(arguments):
        raise RuntimeError('Fresh installation failed; the previous installation is in system-backup')
    print('Fresh installation ready. Running the normal-user agent/hardware tests.', flush=True)
    python = '/opt/torque/current/runtime/python/bin/python'
    runner = '/opt/torque/current/install/e2e.py'
    result = system.run([python, runner, 'check', '--plan', str(Path(plan['run_dir']) / 'plan.json')],
                        user=plan['user'], timeout=360, check=False)
    if result.returncode:
        raise RuntimeError('Pre-reboot E2E failed; inspect the private pre-boot report')
    before = json.loads(system.run(['/usr/local/bin/torque', 'status', '--json'], user=plan['user']).stdout)
    if system.main(arguments):
        raise RuntimeError('Same-bundle reinstall failed')
    after = json.loads(system.run(['/usr/local/bin/torque', 'status', '--json'], user=plan['user']).stdout)
    if before['device']['snapshot']['boot_id'] != after['device']['snapshot']['boot_id']:
        raise RuntimeError('Same-bundle reinstall unexpectedly reset the MCU')
    preserved(plan)
    save(Path(plan['run_dir']) / 'install.json', {'passed': True, 'fresh_install': True,
         'same_bundle_reinstall': True, 'reinstall_did_not_reflash': True, 'release': Path(plan['stage']).name,
         'controller_boot_id': after['device']['snapshot']['boot_id']}, account)
    plan['pre_reboot_linux_boot_id'] = Path('/proc/sys/kernel/random/boot_id').read_text().strip()
    save(Path(plan['run_dir']) / 'plan.json', plan, account)
    name, content = unit_text(plan)
    path = Path('/etc/systemd/system') / name
    if path.exists():
        raise RuntimeError('E2E verification unit already exists')
    path.write_text(content)
    path.chmod(0o644)
    system.run(['systemctl', 'daemon-reload'])
    system.run(['systemctl', 'enable', name])
    print('Pre-reboot E2E and reinstall passed. Rebooting; post-boot verification will run automatically.', flush=True)
    system.run(['systemctl', 'reboot'])


def check(plan, account, after_boot=False):
    if os.geteuid() != account.pw_uid:
        raise RuntimeError('Agent/device tests must run as the normal board user')
    directory = Path(plan['run_dir'])
    phase = 'post-boot' if after_boot else 'pre-boot'
    report = {'phase': phase, 'passed': False, 'uid': os.geteuid(), 'physical_observation': 'not measured by software'}
    try:
        system = module('system')
        from torque.protocol import Connection
        from torque import Board, Frame
        boot = Path('/proc/sys/kernel/random/boot_id').read_text().strip()
        if after_boot and boot == plan.get('pre_reboot_linux_boot_id', plan['before_linux_boot_id']):
            raise RuntimeError('Linux did not reboot')
        if after_boot:
            for filename in ('install.json', 'pre-boot.json'):
                if json.loads((directory / filename).read_text()).get('passed') is not True:
                    raise RuntimeError('Pre-reboot installation/tests did not pass')
        deadline = time.monotonic() + 240
        while True:
            try:
                with Connection() as client:
                    state = client.request('status')
                if state['device']['ready'] and state['credential_ready']:
                    break
            except (OSError, RuntimeError):
                pass
            if time.monotonic() >= deadline:
                raise RuntimeError('Torque did not become ready after boot')
            time.sleep(1)
        if after_boot and (state['active'] or state['engine_ready']):
            raise RuntimeError('Unexpected model work before the post-boot test prompt')
        service_user = system.run(['systemctl', 'show', 'torque.service', '-p', 'User', '--value']).stdout.strip()
        if service_user != plan['user'] or os.access('/opt/torque/current/engines/fx/worker.mjs', os.W_OK):
            raise RuntimeError('Runtime service/ownership does not match the normal-user installation')
        socket_info = Path('/run/torque/control.sock').stat()
        if socket_info.st_uid != account.pw_uid or stat.S_IMODE(socket_info.st_mode) != 0o600:
            raise RuntimeError('Control socket is not owner-only')
        cli = system.run(['/usr/local/bin/torque', 'ask', 'Reply exactly TORQUE_E2E_OK. Do not use any tools.'],
                         user=plan['user'], timeout=120)
        if 'TORQUE_E2E_OK' not in cli.stdout:
            raise RuntimeError('Normal-user CLI prompt did not return the expected reply')
        key = Path(plan['home']) / '.config/torque/credentials/modular-api-key'
        key_info = key.lstat()
        if not stat.S_ISREG(key_info.st_mode) or key_info.st_uid != account.pw_uid or stat.S_IMODE(key_info.st_mode) != 0o600:
            raise RuntimeError('Credential persistence/permissions failed')
        verify = module('verify')
        code = verify.main(['--exercise-agent', '--exercise-device', '--report', str(directory / (phase + '-agent.json'))])
        if code:
            raise RuntimeError('Model/tool/hardware program verification failed')
        name = 'projects/e2e-denied-' + uuid.uuid4().hex + '.txt'
        denied = verify.turn('For this permission-denial test, call write_file once with path ' + name +
                             ' and content DENIAL_TEST. The host will deny it. Do not retry or use another tool; report the result.',
                             lambda pending: False)
        failures = [effect for effect in denied['effects'] if effect['name'] == 'write_file' and effect['isError']]
        if len(failures) != 1 or (Path(plan['workspace']) / name).exists():
            raise RuntimeError('A denied file write was not verified')
        time.sleep(.5)
        with Board() as board:
            snapshot, health = board.snapshot(), board.health()
        standby = Frame.from_rows(json.loads((ROOT / 'assets/status.json').read_text())['standby']).to_hex()
        if snapshot['matrix']['frame_hex'] != standby or snapshot['matrix']['playing']:
            raise RuntimeError('Idle framebuffer was not restored')
        preserved(plan)
        report.update(passed=True, linux_boot_id=boot, reboot_verified=after_boot,
                      service_user=service_user, credential_persisted=True, permission_denial=True,
                      workspace_preserved=True, global_fx_preserved=True, private_socket=True,
                      cli_without_activation=True, exact_idle_framebuffer=True,
                      controller_boot_id=snapshot['boot_id'], health=health)
    except Exception as error:
        report['error'] = str(error)
        try:
            with Connection() as client:
                if client.request('status')['active']:
                    client.request('cancel')
        except Exception:
            pass
        raise
    finally:
        save(directory / (phase + '.json'), report)
        if after_boot:
            save(directory / 'result.json', report)
    print(json.dumps(report, indent=2), flush=True)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', choices=['prepare', 'install', 'check', 'after-boot'])
    parser.add_argument('--plan', type=Path)
    parser.add_argument('--replace-managed', action='store_true')
    args = parser.parse_args(argv)
    try:
        if args.action == 'prepare':
            prepare()
        else:
            if args.plan is None:
                parser.error('--plan is required')
            plan, account = load_plan(args.plan)
            if args.action == 'install':
                if not args.replace_managed:
                    parser.error('install requires --replace-managed')
                install(plan, account)
            else:
                check(plan, account, after_boot=args.action == 'after-boot')
        return 0
    except (OSError, ValueError, RuntimeError, subprocess.SubprocessError) as error:
        print('Torque E2E: ' + str(error), file=sys.stderr)
        return 1


if __name__ == '__main__':
    sys.exit(main())
