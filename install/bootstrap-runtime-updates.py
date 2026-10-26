#!/usr/bin/env python3
"""Reviewed administrator bootstrap. Stdlib only; never import candidate code as root.

Preflight is the default. Apply with sudo python3 -I and an explicit --apply.
All application builds, package imports and acceptance run after runuser drops UID.
"""
import argparse
import fcntl
import hashlib
import json
import os
from pathlib import Path
import pwd
import posixpath
import re
import shutil
import stat
import subprocess
import sys
import time
import uuid

BASE = Path('/opt/torque')
STATE = Path('/var/lib/torque')
UNIT = Path('/etc/systemd/system/torque.service')
LAUNCHER = Path('/usr/local/bin/torque')
POLICY = Path('/etc/sudoers.d/torque-runtime-restart')
MARKER = Path('/etc/torque-runtime-updates.json')
JOURNAL = Path('/var/lib/torque-runtime-bootstrap.json')
RELEASE = re.compile(r'\d+\.\d+\.\d+-[0-9a-f]{12}\Z')


def sha(path):
    result=hashlib.sha256()
    with Path(path).open('rb') as stream:
        for block in iter(lambda:stream.read(1024*1024),b''):result.update(block)
    return result.hexdigest()


def atomic(path, value, *, mode=0o600):
    path=Path(path);temporary=path.with_name('.'+path.name+'-'+uuid.uuid4().hex)
    fd=os.open(temporary,os.O_WRONLY|os.O_CREAT|os.O_EXCL|os.O_NOFOLLOW,mode)
    try:
        with os.fdopen(fd,'w') as stream:
            json.dump(value,stream,indent=2);stream.write('\n');stream.flush();os.fsync(stream.fileno())
        os.replace(temporary,path)
        directory=os.open(path.parent,os.O_RDONLY|os.O_DIRECTORY)
        try:os.fsync(directory)
        finally:os.close(directory)
    finally:temporary.unlink(missing_ok=True)


def root_file(path):
    info=path.lstat()
    if not stat.S_ISREG(info.st_mode) or info.st_uid!=0 or info.st_mode & 0o022:
        raise RuntimeError('Expected a root-owned, protected file: '+str(path))


def validate_policy():
    # Explicit -f requests full syntax/include validation without imposing
    # visudo's default 0440 mode on existing vendor fragments (Arduino uses
    # root-owned 0644). Still reject any parsed file writable by another user.
    output=run(['/usr/sbin/visudo','-cf','/etc/sudoers'])
    parsed=[]
    for line in output.splitlines():
        if line.endswith(': parsed OK'):
            path=Path(line[:-len(': parsed OK')])
            if not path.is_absolute():raise RuntimeError('Unexpected sudo policy validation path')
            root_file(path);parsed.append(str(path))
    if '/etc/sudoers' not in parsed:raise RuntimeError('Global sudo policy validation was incomplete')
    return parsed


def run(argv, *, account=None, timeout=60):
    if account and os.geteuid()==0:
        argv=['/usr/sbin/runuser','-u',account.pw_name,'--',*argv]
    env={'PATH':'/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin','LANG':'C.UTF-8'}
    if account:env.update(HOME=account.pw_dir,USER=account.pw_name,LOGNAME=account.pw_name)
    result=subprocess.run(argv,env=env,capture_output=True,text=True,timeout=timeout)
    if result.returncode:
        # No environment, settings contents, credentials or model arguments.
        raise RuntimeError('Bootstrap operation failed: '+' '.join(argv[:2])+'; '+result.stderr[-1200:])
    return result.stdout


def unit(account, *, active=True):
    root_file(UNIT);root_file(LAUNCHER)
    commands=[]
    for line in UNIT.read_text().splitlines():
        line=line.strip()
        if line.startswith('.include'):raise RuntimeError('Included service definitions are unsupported')
        if '=' in line and not line.startswith(('#',';')):
            key,value=line.split('=',1)
            if key.strip().startswith('Exec'):commands.append((key.strip(),value.strip()))
    if commands!=[('ExecStart','/opt/torque/current/runtime/python/bin/python -m torque.daemon')]:
        raise RuntimeError('Unexpected service execution hooks or privilege prefixes')
    names=('User','Group','SupplementaryGroups','AmbientCapabilities','RootDirectory','RootImage',
           'NoNewPrivileges','KillMode','Restart','MainPID','ActiveState','SubState','DropInPaths',
           'ExecStart','ExecStartPre','ExecStartPost','ExecStop','ExecStopPost')
    raw=run(['/usr/bin/systemctl','show','torque.service','--property='+','.join(names)])
    data=dict(line.split('=',1) for line in raw.splitlines() if '=' in line)
    if (data['User']!=account.pw_name or data['NoNewPrivileges']!='yes' or data['KillMode']!='control-group' or
            data['Restart']!='on-failure' or data['DropInPaths'] or
            any(data.get(k) for k in ('ExecStartPre','ExecStartPost','ExecStop','ExecStopPost')) or
            any(data.get(k) for k in ('Group','SupplementaryGroups','AmbientCapabilities','RootDirectory','RootImage')) or
            'argv[]=/opt/torque/current/runtime/python/bin/python -m torque.daemon ;' not in data['ExecStart']):
        raise RuntimeError('Effective service differs from the reviewed unprivileged unit')
    if active and (data['ActiveState']!='active' or data['SubState']!='running'):
        raise RuntimeError('Service is inactive; bootstrap will not enable or repair it')
    if '/opt/torque/current/runtime/python/bin/python -m torque.cli' not in LAUNCHER.read_text():
        raise RuntimeError('Launcher is not the expected Torque wrapper')
    return data


def entries(root):
    """lstat traversal; yield symlinks themselves and never their targets."""
    root=Path(root)
    yield root
    for path in root.iterdir():
        info=path.lstat()
        if stat.S_ISDIR(info.st_mode):
            yield from entries(path)
        else:
            yield path


def validate_tree(root, account, *, staged=False):
    root=Path(root)
    root_fd=os.open(root,os.O_RDONLY|os.O_DIRECTORY|os.O_NOFOLLOW)
    def check(info):
        if info.st_uid not in (0,account.pw_uid):raise RuntimeError('Unknown owner in managed release')
        if stat.S_ISREG(info.st_mode) and info.st_nlink!=1:raise RuntimeError('Hardlinked managed file')
        if not stat.S_ISLNK(info.st_mode) and info.st_mode & 0o022:
            raise RuntimeError('Group/world-writable managed entry')
    actual_files,actual_links={},{}
    try:
        check(os.fstat(root_fd))
        fd=os.open('release.json',os.O_RDONLY|os.O_NOFOLLOW|os.O_NONBLOCK,dir_fd=root_fd)
        with os.fdopen(fd) as stream:
            info=os.fstat(stream.fileno());check(info)
            if not stat.S_ISREG(info.st_mode):raise RuntimeError('Release manifest must be a regular file')
            metadata=json.load(stream)
        if not RELEASE.fullmatch(metadata.get('release','')):raise RuntimeError('Invalid managed release identity')
        if not staged and root.name!=metadata['release']:raise RuntimeError('Managed directory identity mismatch')
        for directory,dirs,files,walk_fd in os.fwalk('.',dir_fd=root_fd,follow_symlinks=False):
            check(os.fstat(walk_fd))
            for name in dirs+files:
                relative=Path(directory)/name
                info=os.stat(name,dir_fd=walk_fd,follow_symlinks=False);check(info)
                if '__pycache__' in relative.parts or '.cache' in relative.parts:continue
                if str(relative)=='release.json':continue
                if stat.S_ISLNK(info.st_mode):
                    link=os.readlink(name,dir_fd=walk_fd)
                    normalized=posixpath.normpath(str(relative.parent/ link))
                    escapes=Path(link).is_absolute() or normalized=='..' or normalized.startswith('../')
                    if escapes and not (str(relative).startswith('runtime/python/bin/python') and
                            re.fullmatch(r'/usr/bin/python3(?:\.\d+)?',link)):
                        raise RuntimeError('Managed symlink escapes the release: '+str(relative))
                    actual_links[str(relative)]=link
                elif stat.S_ISREG(info.st_mode) and str(relative)!='release.json':
                    descriptor=os.open(name,os.O_RDONLY|os.O_NOFOLLOW|os.O_NONBLOCK,dir_fd=walk_fd)
                    with os.fdopen(descriptor,'rb') as stream:
                        opened=os.fstat(stream.fileno());check(opened)
                        if not stat.S_ISREG(opened.st_mode):raise RuntimeError('Managed file type changed')
                        digest=hashlib.sha256()
                        for block in iter(lambda:stream.read(1024*1024),b''):digest.update(block)
                        actual_files[str(relative)]=digest.hexdigest()
                elif not stat.S_ISDIR(info.st_mode):raise RuntimeError('Special file in managed release')
    finally:os.close(root_fd)
    if metadata.get('format')==2:
        declared=metadata['artifacts']
        declared_files={p:v['sha256'] for p,v in declared.items() if 'sha256' in v}
        declared_links={p:v['link'] for p,v in declared.items() if 'link' in v}
    else:
        declared_files,declared_links=metadata['files'],metadata.get('links',{})
    if actual_files!=declared_files or actual_links!=declared_links:
        raise RuntimeError('Managed release hashes/links differ: '+metadata['release'])
    return metadata


def transfer(root, account):
    def visit(directory):
        for name in os.listdir(directory):
            info=os.stat(name,dir_fd=directory,follow_symlinks=False)
            if stat.S_ISLNK(info.st_mode):
                continue  # Link ownership is immaterial; never touch its target.
            flags=os.O_RDONLY|os.O_NOFOLLOW|os.O_NONBLOCK|(os.O_DIRECTORY if stat.S_ISDIR(info.st_mode) else 0)
            fd=os.open(name,flags,dir_fd=directory)
            try:
                opened=os.fstat(fd)
                if opened.st_uid not in (0,account.pw_uid):raise RuntimeError('Entry owner changed during migration')
                if stat.S_ISDIR(opened.st_mode):visit(fd)
                elif not stat.S_ISREG(opened.st_mode) or opened.st_nlink!=1:raise RuntimeError('Entry type/link count changed')
                os.fchown(fd,account.pw_uid,account.pw_gid)
            finally:os.close(fd)
    fd=os.open(root,os.O_RDONLY|os.O_DIRECTORY|os.O_NOFOLLOW)
    try:
        visit(fd);os.fchown(fd,account.pw_uid,account.pw_gid)
    finally:os.close(fd)


def policy_text(account):
    if not re.fullmatch(r'[a-z_][a-z0-9_-]*',account.pw_name):raise RuntimeError('Unsupported account name')
    return account.pw_name+' ALL=(root) NOPASSWD: /usr/bin/systemctl restart torque.service\n'


def live(account):
    data=json.loads(run([str(LAUNCHER),'status','--json'],account=account))
    if data['active'] or data['pending'] or data['device'].get('owner') or not data['device']['ready']:
        raise RuntimeError('Keep Torque idle with no foreground program during bootstrap')
    if data.get('maintenance') not in (None,'runtime-update'):
        raise RuntimeError('Another control operation is active')
    return data


def old_clients(account, current, daemon_pid):
    """Old clients predate leases; require them to exit during this one migration."""
    found=[]
    for process in Path('/proc').iterdir():
        if not process.name.isdigit() or int(process.name)==daemon_pid:continue
        try:
            if process.stat().st_uid!=account.pw_uid:continue
            args=(process/'cmdline').read_bytes().split(b'\0')
            args=[arg.decode(errors='replace') for arg in args if arg]
            if not args:continue
            executable=Path(args[0])
            if not executable.is_absolute():continue
            resolved=executable.resolve()
            if not resolved.is_relative_to(BASE/'releases'):continue
            relative=resolved.relative_to(BASE/'releases')
            if not relative.parts or not RELEASE.fullmatch(relative.parts[0]):continue
            if ('torque.cli' in args or (len(args)>1 and args[1].endswith('.py'))):
                found.append(int(process.name))
        except (OSError,ValueError):pass
    if found:raise RuntimeError('Close old Torque frontends/programs before bootstrap; PIDs: '+','.join(map(str,found)))


def copy_payload(source,target,account):
    if target.exists():
        if not target.is_symlink() and target.is_dir() and target.stat().st_uid==0 and not any(target.iterdir()):
            os.chown(target,account.pw_uid,account.pw_gid)
        if target.is_symlink() or not target.is_dir() or target.stat().st_uid!=account.pw_uid:
            raise RuntimeError('Interrupted copy has an unexpected target owner/type')
        cleanup=('from pathlib import Path;import shutil,sys;'
                 'root=Path(sys.argv[1]);'
                 '[(p.unlink() if p.is_symlink() or p.is_file() else shutil.rmtree(p)) for p in root.iterdir()]')
        run(['/usr/bin/python3','-I','-c',cleanup,str(target)],account=account)
    else:
        target.mkdir(mode=0o755)
        os.chown(target,account.pw_uid,account.pw_gid)
    code=('import shutil,sys;shutil.copytree(sys.argv[1],sys.argv[2],dirs_exist_ok=True,'
          'symlinks=True,ignore=shutil.ignore_patterns("__pycache__",".cache"))')
    run(['/usr/bin/python3','-I','-c',code,str(source),str(target)],account=account,timeout=300)
    validate_tree(target,account,staged=True)


def select_release(target):
    if target.parent!=BASE/'releases' or target.is_symlink() or not RELEASE.fullmatch(target.name):
        raise RuntimeError('Invalid bootstrap activation target')
    temporary=BASE/'.bootstrap-current'
    if temporary.exists() or temporary.is_symlink():
        if (not temporary.is_symlink() or temporary.resolve().parent!=BASE/'releases' or
                not RELEASE.fullmatch(temporary.resolve().name)):
            raise RuntimeError('Unexpected bootstrap temporary selection')
        temporary.unlink()
    temporary.symlink_to(target);os.replace(temporary,BASE/'current')
    directory=os.open(BASE,os.O_RDONLY|os.O_DIRECTORY)
    try:os.fsync(directory)
    finally:os.close(directory)


def clear_pending(account):
    # Remove only the fixed pointer through a no-follow owned-directory fd.
    fd=os.open(STATE/'updates',os.O_RDONLY|os.O_DIRECTORY|os.O_NOFOLLOW)
    try:
        if os.fstat(fd).st_uid!=account.pw_uid:raise RuntimeError('Update state owner changed')
        try:os.unlink('active.json',dir_fd=fd)
        except FileNotFoundError:pass
        os.fsync(fd)
    finally:os.close(fd)


def bootstrap(stage, account, *, apply=False):
    if account.pw_uid==0:raise RuntimeError('Runtime account must be non-root')
    if os.geteuid()==0:validate_policy()
    for path in (BASE.parent,POLICY.parent,STATE.parent):
        info=path.lstat()
        if not stat.S_ISDIR(info.st_mode) or info.st_uid!=0 or info.st_mode & 0o022:
            raise RuntimeError('Administrator parent path is not protected: '+str(path))
    for path in (BASE,BASE/'releases'):
        info=path.lstat()
        if (not stat.S_ISDIR(info.st_mode) or info.st_uid not in (0,account.pw_uid) or info.st_mode & 0o022):
            raise RuntimeError('Unexpected installation directory or permissions')
    probe=('from pathlib import Path;import json;'
           's=json.loads((Path.home()/".config/torque/settings.json").read_text());'
           'print(json.dumps({k:s.get(k) for k in ("release_root","state_dir","socket","python","node","libfx_path")}))')
    configuration=json.loads(run(['/usr/bin/python3','-I','-c',probe],account=account))
    expected_paths={'release_root':str(BASE/'current'),'state_dir':str(STATE),'socket':'/run/torque/control.sock',
                    'python':str(BASE/'current/runtime/python/bin/python'),'node':str(BASE/'current/runtime/node/bin/node'),
                    'libfx_path':str(BASE/'current/node_modules/libfx')}
    if configuration!=expected_paths:raise RuntimeError('Configured paths differ from the reviewed managed runtime')
    if MARKER.exists() or MARKER.is_symlink():
        root_file(MARKER)
        if os.geteuid()==0:root_file(POLICY)
        marker=json.loads(MARKER.read_text())
        if marker['uid']!=account.pw_uid or (os.geteuid()==0 and POLICY.read_text()!=policy_text(account)):
            raise RuntimeError('Existing delegation differs from this account/rule')
        if marker.get('complete'):
            unit(account)
            return {'already_configured':True,'no_changes_performed':True}
    stage=Path(stage).resolve();payload=stage/'release' if (stage/'release').is_dir() else stage
    metadata=validate_tree(payload,account,staged=True)
    # A migration build also works after a fresh installer selected this stage.
    # Never rebuild the running venv in place.
    version=metadata['release'].rsplit('-',1)[0]
    identifier=hashlib.sha256((metadata['release']+':unattended-bootstrap-v1').encode()).hexdigest()[:12]
    target=BASE/'releases'/(version+'-'+identifier)
    current=(BASE/'current').resolve()
    if current.parent!=BASE/'releases':raise RuntimeError('Current escapes the release directory')
    journal=None
    if (JOURNAL.exists() or JOURNAL.is_symlink()) and os.geteuid()==0:
        root_file(JOURNAL);journal=json.loads(JOURNAL.read_text())
        if journal['target']!=str(target) or journal['uid']!=account.pw_uid:
            raise RuntimeError('A different administrator bootstrap journal requires review')
    resuming=journal and journal['phase'] in ('armed','activated','migrated','granted')
    properties=unit(account,active=not resuming)
    if properties['ActiveState']=='active':live(account)
    expected=Path(journal['base']) if journal else current
    if current not in (expected,target):raise RuntimeError('Active release changed since bootstrap preparation')
    for path in BASE.iterdir():
        if path.name not in ('current','releases') and not (journal and path.name=='.bootstrap-current'):
            raise RuntimeError('Unknown entry in activation parent: '+path.name)
    old_clients(account,current,int(properties['MainPID']))
    managed=[]
    for path in sorted((BASE/'releases').iterdir()):
        if path==target and journal:continue
        if not RELEASE.fullmatch(path.name) or path.is_symlink():raise RuntimeError('Unknown entry in managed releases')
        print('Validating managed release '+path.name,flush=True)
        validate_tree(path,account);managed.append(path)
    if os.geteuid()==0 and (POLICY.exists() or POLICY.is_symlink()) and (POLICY.is_symlink() or POLICY.read_text()!=policy_text(account)):
        raise RuntimeError('An unrelated sudo policy occupies the dedicated rule path')
    report={'preflight_passed':True,'target':str(target),'previous_release':str(expected),
            'managed_releases':len(managed),'restart_rule':policy_text(account).strip(),
            'firmware_upload':False,'service_configuration_preserved':True,'no_changes_performed':not apply}
    if not apply:return report
    if os.geteuid()!=0 or not sys.flags.isolated:
        raise RuntimeError('Apply requires sudo python3 -I for the reviewed standalone bootstrap')
    os.umask(0o022)
    if not journal:
        journal={'uid':account.pw_uid,'base':str(expected),'target':str(target),'phase':'validated',
                 'unit_sha256':sha(UNIT),'launcher_sha256':sha(LAUNCHER),'managed':[str(p) for p in managed]}
        atomic(JOURNAL,journal)
    def phase(name,**fields):
        journal.update(phase=name,**fields);atomic(JOURNAL,journal)
    python=payload/'runtime/python/bin/python'
    def application(operation,*arguments):
        return json.loads(run([str(python),'-I','-m','torque.update',operation,*map(str,arguments)],account=account,timeout=300))
    application('bootstrap-init')
    locks=[]
    def lock(name):
        fd=os.open(STATE/'updates'/name,os.O_RDWR|os.O_NOFOLLOW)
        try:
            info=os.fstat(fd)
            if (info.st_uid!=account.pw_uid or not stat.S_ISREG(info.st_mode) or
                    info.st_nlink!=1 or info.st_mode & 0o077):
                raise RuntimeError('Unexpected update lock owner/type/mode')
            fcntl.flock(fd,fcntl.LOCK_EX|fcntl.LOCK_NB)
        except BaseException:
            os.close(fd);raise
        locks.append(fd)
    try:
        lock('deploy.lock')
        if journal['phase'] in ('validated','rolled-back'):
            copy_payload(payload,target,account)
            phase('copied')
        if journal['phase']=='copied':
            print('Building and testing Python at its permanent path as '+account.pw_name,flush=True)
            application('bootstrap-build',target);phase('built')
        lock('programs.lock')
        if journal['phase']=='built':
            properties=unit(account);live(account)
            old_clients(account,(BASE/'current').resolve(),int(properties['MainPID']))
            if (BASE/'current').resolve()!=expected:raise RuntimeError('Active release changed before bootstrap activation')
            armed=application('bootstrap-arm',target);phase('armed',update_id=armed['update_id'])
        if journal['phase']=='armed':
            if sha(UNIT)!=journal['unit_sha256'] or sha(LAUNCHER)!=journal['launcher_sha256']:
                raise RuntimeError('Root-owned launch configuration changed during bootstrap')
            already_running=False
            if (BASE/'current').resolve()==target:
                try:
                    status=live(account)
                    already_running=status.get('release_root')==str(target) and status.get('update_id')==journal['update_id']
                except (RuntimeError,ValueError):pass
            if not already_running:
                print('Restarting only torque.service with the update-capable runtime.',flush=True)
                run(['/usr/bin/systemctl','stop','torque.service'])
                select_release(target);run(['/usr/bin/systemctl','start','torque.service'])
            phase('activated')
        if journal['phase'] in ('activated','migrated','granted'):
            properties=unit(account,active=False)
            if properties['ActiveState'] in ('inactive','failed') and properties['MainPID']=='0':
                print('Resuming the service start owned by this interrupted bootstrap.',flush=True)
                run(['/usr/bin/systemctl','start','torque.service'])
        if journal['phase']=='activated':
            deadline=time.monotonic()+60
            while time.monotonic()<deadline:
                try:
                    status=live(account)
                    if status.get('release_root')==str(target) and status.get('update_id')==journal['update_id']:break
                except (RuntimeError,ValueError):pass
                time.sleep(.25)
            else:raise RuntimeError('New fenced runtime did not become ready')
            validate_tree(target,account)
            print('Transferring only validated application releases; system files stay root-owned.',flush=True)
            for path in managed:transfer(path,account)
            os.chown(BASE/'releases',account.pw_uid,account.pw_gid,follow_symlinks=False)
            os.chown(BASE/'current',account.pw_uid,account.pw_gid,follow_symlinks=False)
            os.chown(BASE,account.pw_uid,account.pw_gid,follow_symlinks=False)
            phase('migrated')
        if journal['phase']=='migrated':
            temporary=POLICY.with_name('.torque-runtime-'+uuid.uuid4().hex)
            try:
                fd=os.open(temporary,os.O_WRONLY|os.O_CREAT|os.O_EXCL|os.O_NOFOLLOW,0o440)
                with os.fdopen(fd,'w') as stream:stream.write(policy_text(account))
                run(['/usr/sbin/visudo','-cf',str(temporary)])
                os.replace(temporary,POLICY)
            finally:temporary.unlink(missing_ok=True)
            root_file(POLICY)
            if stat.S_IMODE(POLICY.lstat().st_mode)!=0o440:
                raise RuntimeError('The dedicated Torque restart rule must have mode 0440')
            validate_policy()
            atomic(MARKER,{'format':1,'uid':account.pw_uid,'user':account.pw_name,'base':str(BASE),
                           'policy_sha256':sha(POLICY),'complete':False},mode=0o644)
            phase('granted')
        if journal['phase']=='granted':
            completed=application('bootstrap-commit',journal['update_id'])
            marker=json.loads(MARKER.read_text());marker['complete']=True;atomic(MARKER,marker,mode=0o644)
            phase('complete')
            return {**report,'applied':True,'release':target.name,'acceptance':completed,
                    'no_changes_performed':False,'unattended_updates_enabled':True}
        raise RuntimeError('Unknown bootstrap phase; inspect the administrator journal')
    except BaseException:
        if journal['phase'] in ('armed','activated'):
            print('Bootstrap did not complete; restoring the previous runtime.',flush=True)
            run(['/usr/bin/systemctl','stop','torque.service'])
            select_release(expected);clear_pending(account)
            run(['/usr/bin/systemctl','start','torque.service'])
            phase('rolled-back')
        raise
    finally:
        for fd in locks:os.close(fd)


def main(argv=None):
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--stage',type=Path,required=True)
    parser.add_argument('--user',default='arduino')
    parser.add_argument('--apply',action='store_true')
    args=parser.parse_args(argv)
    try:
        report=bootstrap(args.stage,pwd.getpwnam(args.user),apply=args.apply)
        print(json.dumps(report,indent=2));return 0
    except (OSError,RuntimeError,ValueError,KeyError,subprocess.SubprocessError) as error:
        print('Torque bootstrap: '+str(error),file=sys.stderr);return 1


if __name__=='__main__':raise SystemExit(main())
