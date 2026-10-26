#!/usr/bin/env python3
"""Prepare/apply a Linux-only Torque update; never stop or start an Arduino app."""
import argparse
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import pwd
import shutil
import subprocess
import sys

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
from torque_bundle import application_version, bundle_identity

CURRENT = Path('/opt/torque/current')
RELEASES = Path('/opt/torque/releases')
STATE = Path('/var/lib/torque')
SERVICE_UNIT = Path('/etc/systemd/system/torque.service')
LAUNCHER = '/usr/local/bin/torque'


def support():
    spec = importlib.util.spec_from_file_location('runtime_update_support', HERE/'update-controller.py')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def manifest_files(root):
    files, links = {}, {}
    for path in sorted(root.rglob('*')):
        relative = path.relative_to(root)
        if str(relative) == 'release.json' or any(p in ('__pycache__','.cache') for p in relative.parts):
            continue
        if path.is_symlink(): links[str(relative)] = os.readlink(path)
        elif path.is_file(): files[str(relative)] = digest(path)
    return files, links


def prepare(source, stage):
    if Path('/etc/torque-runtime-updates.json').exists():
        raise RuntimeError('Unattended runtime ownership is enabled; use torque update prepare')
    os.umask(0o022)
    source, stage = source.resolve(), stage.resolve()
    current = CURRENT.resolve()
    previous = json.loads((current/'release.json').read_text())
    if any(previous.get(k) != v for k,v in bundle_identity().items()):
        raise RuntimeError('A Linux-only update requires the currently selected firmware bundle')
    size = sum(p.stat().st_size for p in current.rglob('*') if p.is_file() and not p.is_symlink())
    stage.parent.mkdir(parents=True, exist_ok=True)
    if shutil.disk_usage(stage.parent).free < size * 2 + 64*1024*1024:
        raise RuntimeError('Insufficient space for a separate release and rollback')
    stage.mkdir(mode=0o700)
    release = stage/'release'
    shutil.copytree(current, release, symlinks=True, ignore=shutil.ignore_patterns('__pycache__','.cache'))
    for relative in ('packages/session','examples','install','docs','engines','agent','config'):
        shutil.rmtree(release/relative)
        shutil.copytree(source/relative, release/relative,
                        ignore=shutil.ignore_patterns('__pycache__','.cache','.venv'))
    for name in ('pyproject.toml','setup.py','README.md','ARCHITECTURE.md'):
        shutil.copyfile(source/name, release/name)
    # These are generated application artifacts, not runtime dependencies.
    for name in ('build', 'dist'):
        path = release/name
        if path.is_symlink(): path.unlink()
        elif path.exists(): shutil.rmtree(path)
    python = release/'runtime/python/bin/python'
    with (stage/'packages.log').open('w') as log:
        subprocess.run([str(python),'-m','pip','--isolated','--disable-pip-version-check','install',
                        '--no-deps','--no-cache-dir','--force-reinstall',str(release)],
                       env={'PATH':'/usr/local/bin:/usr/bin:/bin','HOME':str(Path.home()),'LANG':'C.UTF-8'},
                       stdout=log,stderr=subprocess.STDOUT,check=True,timeout=300)
    smoke = ('import importlib.metadata as m;from pathlib import Path;from torque import examples;'
             'from torque.installation import verify_python_sources;'
             'verify_python_sources(Path(__import__("sys").argv[2]));'
             f'assert m.version("torque-uno-q")=={application_version(source)!r};'
             'assert examples.default_root()==Path(examples.__file__).parent/"_examples";'
             'assert len(examples.discover())>=6;'
             'assert examples.run("dot-matrix-animations",mode="preview",workspace=Path(__import__("sys").argv[1]))==0')
    subprocess.run([str(python),'-I','-c',smoke,str(stage/'preview-check'),str(release)],check=True,timeout=60)
    files, links = manifest_files(release)
    identity = application_version(source)+'-'+hashlib.sha256(json.dumps(files,sort_keys=True).encode()).hexdigest()[:12]
    manifest = {**previous,'release':identity,'files':files,'links':links}
    (release/'release.json').write_text(json.dumps(manifest,indent=2)+'\n')
    plan = dict(kind='runtime-only',previous_release=str(current),release=identity,
                application_version=application_version(source),**bundle_identity())
    (stage/'plan.json').write_text(json.dumps(plan,indent=2)+'\n')
    print(json.dumps({'stage':str(stage),**plan,'package_and_preview_checks':True,'firmware_upload':False},indent=2))
    return 0


def probe(system, python, user):
    code = 'import json;from unoq_control import Board\nwith Board(timeout=2) as b:print(json.dumps(b.info()))'
    return json.loads(system.run([str(python),'-c',code],user=user,timeout=15).stdout)


def default_app(system, user):
    raw = system.run(['arduino-app-cli','properties','get','default','--format','json'],user=user,timeout=20)
    return json.loads(raw.stdout)['app']['FullPath']


def verify_package(system, release, user):
    code = ('from torque.installation import verify_python_sources;'
            'verify_python_sources(__import__("sys").argv[1])')
    system.run([str(release/'runtime/python/bin/python'),'-I','-c',code,str(release)],user=user,timeout=20)


def apply(stage, user, execute=False):
    if Path('/etc/torque-runtime-updates.json').exists():
        raise RuntimeError('Unattended runtime ownership is enabled; use torque update, never sudo this Python helper')
    stage = stage.resolve()
    plan = json.loads((stage/'plan.json').read_text())
    if plan.get('kind') != 'runtime-only': raise RuntimeError('Not a Linux-only update plan')
    helper = support()
    system = helper.load_system(stage/'release')
    manifest = system.verify_stage(stage/'release')
    if (manifest['release'],manifest['firmware'],manifest['protocol']) != (plan['release'],plan['firmware'],plan['protocol']):
        raise RuntimeError('Runtime plan/bundle identity mismatch')
    target = RELEASES/plan['release']
    if CURRENT.resolve() == target.resolve() and (stage/'applied.json').exists():
        verify_package(system, CURRENT, user)
        helper.wait_for_ready(system,user)
        identity = probe(system,CURRENT/'runtime/python/bin/python',user)
        if (identity.get('version'),identity.get('protocol'),identity.get('ready')) != (plan['firmware'],plan['protocol'],True):
            raise RuntimeError('Completed runtime update has a different live controller; no changes performed')
        print(json.dumps({'already_applied':True,'release':plan['release'],'no_restart_or_flash_repeated':True}))
        return 0
    if str(CURRENT.resolve()) != plan['previous_release']:
        raise RuntimeError('Active release changed; prepare this update again')
    verify_package(system, stage/'release', user)
    status = json.loads(system.run([LAUNCHER,'status','--json'],user=user,timeout=15).stdout)
    if status.get('active') or status.get('pending') or status['device'].get('owner'):
        raise RuntimeError('Finish the active turn or device program before a runtime update')
    if not status['device'].get('ready'): raise RuntimeError('Current Torque device is not ready')
    before = probe(system,CURRENT/'runtime/python/bin/python',user)
    if (before['version'],before['protocol'],before['ready']) != (plan['firmware'],plan['protocol'],True):
        raise RuntimeError('Live controller differs; no firmware repair is part of this update')
    default, unit_hash = default_app(system,user), digest(SERVICE_UNIT)
    report = dict(release=plan['release'],previous_release=plan['previous_release'],before_firmware=before,
                  boot_default=default,service_sha256=unit_hash,firmware_upload=False)
    if not execute:
        print(json.dumps({**report,'preflight_passed':True,'no_changes_performed':True},indent=2))
        return 0
    if os.geteuid() != 0: raise RuntimeError('Runtime activation requires sudo; no changes performed')
    account = pwd.getpwnam(user)
    if account.pw_uid == 0: raise RuntimeError('Torque service user must be a normal account')
    os.umask(0o022)
    if target.exists():
        if json.loads((target/'release.json').read_text()) != manifest: raise RuntimeError('Release identifier collision')
    else: system.copy_release(stage/'release',target,manifest)
    system.run(['systemctl','stop','torque.service'])
    try:
        link = CURRENT.with_name('.runtime-'+plan['release'])
        if link.exists() or link.is_symlink(): raise RuntimeError('Temporary activation path already exists')
        link.symlink_to(target);os.replace(link,CURRENT)
        system.run(['systemctl','start','torque.service'])
        helper.wait_for_ready(system,user)
        after = probe(system,target/'runtime/python/bin/python',user)
        if after != before: raise RuntimeError('MCU identity changed during Linux-only update')
        if default_app(system,user) != default or digest(SERVICE_UNIT) != unit_hash:
            raise RuntimeError('Boot default or service unit changed')
    except BaseException:
        system.run(['systemctl','stop','torque.service'],check=False)
        rollback = CURRENT.with_name('.runtime-rollback-'+plan['release'])
        if rollback.exists() or rollback.is_symlink(): raise RuntimeError('Rollback activation path already exists')
        rollback.symlink_to(plan['previous_release']);os.replace(rollback,CURRENT)
        system.run(['systemctl','start','torque.service'],check=False)
        raise
    record_path = STATE/'installed.json'
    record = json.loads(record_path.read_text())
    record.update(release=plan['release'],previous_release=plan['previous_release'],identity=after)
    record_path.write_text(json.dumps(record,indent=2)+'\n');os.chown(record_path,account.pw_uid,account.pw_gid)
    report.update(after_firmware=after,ready=True,firmware_boot_unchanged=True,
                  boot_default_preserved=True,service_configuration_preserved=True)
    (stage/'applied.json').write_text(json.dumps(report,indent=2)+'\n')
    print(json.dumps(report,indent=2))
    return 0


def main(argv=None):
    parser=argparse.ArgumentParser(description=__doc__)
    sub=parser.add_subparsers(dest='command',required=True)
    p=sub.add_parser('prepare');p.add_argument('--source',type=Path,default=HERE.parent);p.add_argument('--output',type=Path,required=True)
    p=sub.add_parser('apply');p.add_argument('--stage',type=Path,required=True);p.add_argument('--user',default='arduino');p.add_argument('--apply',action='store_true')
    args=parser.parse_args(argv)
    if args.command=='prepare':return prepare(args.source,args.output)
    return apply(args.stage,args.user,args.apply)


if __name__=='__main__':
    try:raise SystemExit(main())
    except (OSError,ValueError,KeyError,RuntimeError,subprocess.SubprocessError) as error:
        print('Torque runtime update: '+str(error),file=sys.stderr);raise SystemExit(1)
