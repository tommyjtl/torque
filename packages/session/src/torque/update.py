"""Unprivileged, serialized Linux runtime updates from outside torque.service."""
import argparse
import ast
from contextlib import ExitStack, contextmanager
import hashlib
import importlib.metadata
import json
import os
from pathlib import Path
import re
import select
import shutil
import signal
import stat
import subprocess
import sys
import time
import tomllib
import uuid
from .protocol import Connection
from .runtime import Store, Lock, RELEASE_ID, read_json, write_json, sync_dir

BASE = Path('/opt/torque')
ENABLED = Path('/etc/torque-runtime-updates.json')
UNIT = Path('/etc/systemd/system/torque.service')
RESTART = ['sudo', '-n', '/usr/bin/systemctl', 'restart', 'torque.service']
APPLICATION = ('packages/session', 'examples', 'engines', 'agent', 'config', 'assets', 'install',
               'docs', 'pyproject.toml', 'setup.py', 'README.md', 'ARCHITECTURE.md')
SKIP = {'__pycache__', '.cache', '.venv', 'build', 'dist', 'node_modules'}
BUILD_TOOL = 'setuptools-84.2.0-py3-none-any.whl'
BUILD_TOOL_SHA256 = '8cc107ac7a403105dc8d6477664171f36135fab26adf8b5e0edaebc313f39b21'


def digest(path):
    value = hashlib.sha256()
    fd=os.open(path,os.O_RDONLY|os.O_NOFOLLOW|os.O_NONBLOCK)
    with os.fdopen(fd,'rb') as stream:
        if not stat.S_ISREG(os.fstat(stream.fileno()).st_mode):
            raise RuntimeError('Expected a regular file for runtime hashing')
        for block in iter(lambda: stream.read(1024*1024), b''):
            value.update(block)
    return value.hexdigest()


def tree(root, *, source=False):
    """Hash without traversing symlink directories or accepting special files."""
    root = Path(root)
    result = {}
    def visit(directory):
        for path in sorted(directory.iterdir()):
            relative = path.relative_to(root)
            if path.name == '__pycache__' or (source and (path.name.startswith('.') or
                    path.name in SKIP or path.name.endswith('.egg-info'))):
                continue
            info = path.lstat()
            if stat.S_ISLNK(info.st_mode):
                if source and not path.resolve().is_relative_to(root.resolve()):
                    raise RuntimeError('Source link escapes its tree: ' + str(relative))
                result[str(relative)] = {'link': os.readlink(path)}
            elif stat.S_ISDIR(info.st_mode):
                visit(path)
            elif stat.S_ISREG(info.st_mode):
                if info.st_nlink != 1:
                    raise RuntimeError('Hardlinked update input is unsupported: ' + str(relative))
                result[str(relative)] = {'sha256': digest(path), 'executable': bool(info.st_mode & 0o111)}
            else:
                raise RuntimeError('Special file in runtime inputs: ' + str(relative))
    visit(root)
    return result


def content_id(value):
    return hashlib.sha256(json.dumps(value,sort_keys=True,separators=(',',':')).encode()).hexdigest()


def safe_unit_source(text):
    commands=[]
    for line in text.splitlines():
        line=line.strip()
        if line.startswith('.include'):
            return False
        if '=' in line and not line.startswith(('#',';')):
            key,value=line.split('=',1)
            if key.strip().startswith('Exec'):
                commands.append((key.strip(),value.strip()))
    return commands==[('ExecStart','/opt/torque/current/runtime/python/bin/python -m torque.daemon')]


def copy_inputs(source, target, names):
    for name in names:
        original, destination = source/name, target/name
        if not original.exists() or original.is_symlink():
            raise RuntimeError('Missing or linked source component: ' + name)
        if destination.is_symlink():
            destination.unlink()
        elif destination.is_dir():
            shutil.rmtree(destination)
        elif destination.exists():
            destination.unlink()
        destination.parent.mkdir(parents=True,exist_ok=True)
        if original.is_dir():
            shutil.copytree(original,destination,symlinks=True,
                            ignore=lambda _,children:[n for n in children if n.startswith('.') or n in SKIP or n.endswith('.egg-info')])
        else:
            shutil.copyfile(original,destination)


def input_files(source, names):
    result = {}
    for name in names:
        path = source/name
        if path.is_symlink() or not path.exists():
            raise RuntimeError('Missing or linked source component: ' + name)
        if path.is_dir():
            result.update({name+'/'+p:value for p,value in tree(path,source=True).items()})
        else:
            result[name] = {'sha256':digest(path),'executable':bool(path.stat().st_mode & 0o111)}
    return result


def dependencies(release):
    """Identify the actual frozen dependency bundle independently of app outputs."""
    metadata = json.loads((release/'release.json').read_text())
    runtime = {}
    for path in sorted((release/'runtime').iterdir()):
        if path.name != 'python':
            runtime[path.name] = tree(path) if path.is_dir() else {'sha256':digest(path)}
    runtime['node_modules'] = tree(release/'node_modules')
    python = release/'runtime/python'
    site = next((python/'lib').glob('python*/site-packages'))
    installed = {}
    for distribution in importlib.metadata.distributions(path=[str(site)]):
        name = distribution.metadata['Name']
        if name.lower().replace('_','-') != 'torque-uno-q':
            installed[name] = distribution.version
    packages = {}
    for path in site.iterdir():
        if path.name=='torque' or path.name.startswith(('torque_uno_q-','__pycache__')):
            continue
        value = tree(path) if path.is_dir() else {'sha256':digest(path)}
        if path.name.endswith('.dist-info'):
            value = {p:v for p,v in value.items() if p not in ('direct_url.json','RECORD','INSTALLER','REQUESTED')}
        packages[path.name] = value
    return {'firmware':metadata['firmware'],'protocol':metadata['protocol'],
            'python':(python/'pyvenv.cfg').read_text().split('version = ',1)[-1].splitlines()[0],
            'distributions':installed,'packages':content_id(packages),'runtime':content_id(runtime),
            'engine':metadata['engine'],'node':metadata['node'],
            'libfx_sha512':metadata['libfx_sha512'],'node_sha256':metadata['node_sha256']}


def declared_controller(release):
    values = {}
    for node in ast.parse((release/'install/torque_bundle.py').read_text()).body:
        if isinstance(node,ast.Assign) and len(node.targets)==1 and isinstance(node.targets[0],ast.Name):
            if node.targets[0].id in ('FIRMWARE_VERSION','FIRMWARE_PROTOCOL'):
                values[node.targets[0].id] = ast.literal_eval(node.value)
    return values['FIRMWARE_VERSION'], list(values['FIRMWARE_PROTOCOL'])


def owned_tree(release):
    release = Path(release)
    if release.is_symlink() or not RELEASE_ID.fullmatch(release.name):
        raise RuntimeError('Not a managed release')
    for directory,dirs,files in os.walk(release,followlinks=False):
        for path in [Path(directory),*[Path(directory)/p for p in dirs+files]]:
            info = path.lstat()
            if (info.st_uid!=os.getuid() and not (stat.S_ISLNK(info.st_mode) and info.st_uid==0)) or not (stat.S_ISDIR(info.st_mode) or
                    stat.S_ISREG(info.st_mode) or stat.S_ISLNK(info.st_mode)):
                raise RuntimeError('Managed release contains an unowned or special entry')
            if stat.S_ISREG(info.st_mode) and info.st_nlink!=1:
                raise RuntimeError('Managed release contains shared hardlinked files')


def incomplete_identity(release):
    fd=os.open(release/'.incomplete',os.O_RDONLY|os.O_NOFOLLOW|os.O_NONBLOCK)
    with os.fdopen(fd) as stream:
        info=os.fstat(stream.fileno())
        if not stat.S_ISREG(info.st_mode) or info.st_uid!=os.getuid() or info.st_nlink!=1:
            raise RuntimeError('Unsafe incomplete-build marker')
        identity=stream.read(100)
    if not re.fullmatch(r'[0-9a-f]{64}',identity) or not release.name.endswith('-'+identity[:12]):
        raise RuntimeError('Incomplete build is not identified by its canonical input marker')
    owned_tree(release)
    return identity


def verify_managed_tree(release):
    release=Path(release)
    owned_tree(release)
    value = json.loads((release/'release.json').read_text())
    if value.get('format')==2:
        return verify_release(release)
    if value.get('release')!=release.name:
        raise RuntimeError('Legacy release identity mismatch')
    for name,expected in value['files'].items():
        path = release/name
        if not path.resolve().is_relative_to(release) or not path.is_file() or path.is_symlink() or digest(path)!=expected:
            raise RuntimeError('Legacy release file mismatch')
    for name,target in value.get('links',{}).items():
        path = release/name
        if not path.is_symlink() or os.readlink(path)!=target:
            raise RuntimeError('Legacy release link mismatch')
    return value


def fresh_python(release):
    """Create the venv at its final prefix; copy only frozen dependency packages."""
    python = release/'runtime/python'
    old = release/'runtime/.python-update-seed'
    if old.exists():
        raise RuntimeError('An interrupted Python build needs cleanup before rebuilding')
    python.rename(old)
    old_site = next((old/'lib').glob('python*/site-packages'))
    configuration = (old/'pyvenv.cfg').read_text()
    executable = next(line.split(' = ',1)[1] for line in configuration.splitlines() if line.startswith('executable = '))
    subprocess.run([executable,'-m','venv','--copies','--without-pip',str(python)],check=True,capture_output=True)
    site = next((python/'lib').glob('python*/site-packages'))
    for path in old_site.iterdir():
        if path.name == 'torque' or path.name.startswith(('torque_uno_q-','__pycache__')):
            continue
        destination = site/path.name
        if path.is_symlink():
            raise RuntimeError('Linked Python dependency is unsupported')
        if path.is_dir():
            shutil.copytree(path,destination,ignore=shutil.ignore_patterns('__pycache__','.cache'))
        else:
            shutil.copyfile(path,destination)
    executable = python/'bin/python'
    env = {'HOME':str(Path.home()),'PATH':'/usr/local/bin:/usr/bin:/bin','LANG':'C.UTF-8',
           'PIP_NO_INDEX':'1','PIP_DISABLE_PIP_VERSION_CHECK':'1'}
    wheels = sorted((release/'runtime/build-wheels').glob('*.whl'))
    if not (site/'setuptools').is_dir():
        if not wheels:
            raise RuntimeError('The bootstrap build-tool wheels are missing')
        subprocess.run([str(executable),'-I','-m','pip','--isolated','install','--no-index','--no-deps',*[str(p) for p in wheels]],
                       env=env,check=True,capture_output=True)
    result = subprocess.run([str(executable),'-I','-m','pip','--isolated','install','--no-index','--no-deps','--no-build-isolation',
                             '--no-cache-dir','--force-reinstall',str(release)],env=env,capture_output=True,text=True)
    if result.returncode:
        raise RuntimeError('Offline application build failed: '+result.stderr[-2000:])
    # Recreate every dependency console script, including scripts not used by the
    # current shell wrapper. None may retain an old staging-prefix shebang.
    for distribution in importlib.metadata.distributions(path=[str(site)]):
        for entry in distribution.entry_points:
            if entry.group != 'console_scripts':
                continue
            if not re.fullmatch(r'[A-Za-z0-9_.-]+',entry.name) or '[' in entry.value:
                raise RuntimeError('Unsupported console entrypoint')
            module, function = entry.value.split(':',1)
            text = (f'#!{executable}\nimport sys\nfrom importlib import import_module\n'
                    f'f=import_module({module!r})\n'
                    f'for name in {function.split(".")!r}: f=getattr(f,name)\n'
                    'sys.exit(f())\n')
            script = python/'bin'/entry.name
            script.write_text(text);script.chmod(0o755)
    shutil.rmtree(old)
    for name in ('build','dist'):
        if (release/name).is_dir():
            shutil.rmtree(release/name)


def manifest(release, metadata):
    files = tree(release)
    files.pop('release.json',None)
    files.pop('.incomplete',None)
    value = {**metadata,'release':release.name,'format':2,'artifacts':files}
    (release/'release.json').write_text(json.dumps(value,sort_keys=True,indent=2)+'\n')
    return value


def verify_release(release):
    release = Path(release)
    if not RELEASE_ID.fullmatch(release.name) or release.is_symlink() or (release/'.incomplete').exists():
        raise RuntimeError('Release is incomplete or has an invalid path')
    value = json.loads((release/'release.json').read_text())
    if value.get('format') != 2 or value.get('release') != release.name:
        raise RuntimeError('Release manifest is not an unattended-update artifact')
    actual = tree(release);actual.pop('release.json',None)
    if actual != value['artifacts']:
        raise RuntimeError('Release files changed after validation')
    return value


def smoke(release, config, scratch):
    python = release/'runtime/python/bin/python'
    scratch.mkdir(mode=0o700,parents=True,exist_ok=True)
    env={'HOME':str(Path.home()),'PATH':'/usr/local/bin:/usr/bin:/bin','LANG':'C.UTF-8',
         'TORQUE_SOCKET':str(scratch/'offline-no-device.sock')}
    code = ('from torque.installation import verify_python_sources;'
            'from torque import examples;from pathlib import Path;import sys,tomllib,importlib.metadata as m;'
            'verify_python_sources(sys.argv[1]);'
            'assert m.version("torque-uno-q")==tomllib.loads((Path(sys.argv[1])/"pyproject.toml").read_text())["project"]["version"];'
            'assert examples.default_root()==Path(examples.__file__).parent/"_examples";'
            'assert examples.run("dot-matrix-animations",mode="preview",workspace=Path(sys.argv[2]))==0')
    subprocess.run([str(python),'-I','-c',code,str(release),str(scratch/'preview')],
                   env=env,check=True,capture_output=True,timeout=60)
    selected = Path(config['release_root'])
    candidate_config = {**config,'release_root':str(release)}
    for name in ('python','node','libfx_path'):
        if Path(config[name]).is_relative_to(selected):
            candidate_config[name] = str(release/Path(config[name]).relative_to(selected))
    path = scratch/'check-config.json';write_json(path,candidate_config)
    subprocess.run([str(python),'-I','-m','torque.daemon','--check-config','--config',str(path)],
                   env=env,check=True,capture_output=True,timeout=20)
    for name,args in (('torque',['example']),('torqued',['--help']),('unoq-control',['--help']),('pip',['--version'])):
        script = release/'runtime/python/bin'/name
        if not script.read_text().startswith('#!'+str(python)+'\n'):
            raise RuntimeError('Console script is not pinned to its permanent venv')
        subprocess.run([str(script),*args],env=env,check=True,capture_output=True,timeout=20)
    node = release/'runtime/node/bin/node'
    metadata = json.loads((release/'release.json').read_text())
    version = subprocess.run([str(node),'--version'],check=True,capture_output=True,text=True).stdout.strip()
    if version!='v'+metadata['node']:
        raise RuntimeError('Node runtime does not match its declared dependency bundle')
    package=json.loads((release/'node_modules/libfx/package.json').read_text())
    if metadata['engine']!='libfx@'+package['version']:
        raise RuntimeError('libfx version differs from the declared frozen bundle')
    backend = ('import {getBackendInfo} from "libfx";'
               'const b=await getBackendInfo({surface:"agent",backend:"native"});'
               'if(b.backend!=="native")process.exit(1);')
    subprocess.run([str(node),'--input-type=module','-e',backend],cwd=release,
                   env={'HOME':str(Path.home()),'PATH':'/usr/bin:/bin'},check=True,capture_output=True,timeout=30)


class Host:
    def __init__(self, updater):
        self.updater = updater

    def run(self, command, *, timeout=30):
        result = subprocess.run(command,capture_output=True,text=True,timeout=timeout)
        if result.returncode:
            raise RuntimeError('Runtime operation failed: '+' '.join(command[:2]))
        return result.stdout

    def status(self):
        with Connection(self.updater.config['socket']) as connection:
            value=connection.request('status')
        if not isinstance(value,dict) or not isinstance(value.get('device'),dict) or not isinstance(value.get('epoch'),str):
            raise RuntimeError('Malformed daemon status; update did not accept its readiness')
        return value

    def control(self, action, record, **arguments):
        with Connection(self.updater.config['socket']) as connection:
            return connection.request('update',action=action,update_id=record['id'],**arguments)

    def unit(self):
        names = ('User','Group','SupplementaryGroups','AmbientCapabilities','RootDirectory','RootImage',
                 'NoNewPrivileges','KillMode','Restart','MainPID','InvocationID',
                 'ActiveState','SubState','DropInPaths','ExecStart','ExecStartPre','ExecStartPost','ExecStop','ExecStopPost')
        raw = self.run(['/usr/bin/systemctl','show','torque.service','--property='+','.join(names)])
        return dict(line.split('=',1) for line in raw.splitlines() if '=' in line)

    def check_unit(self, *, active=True):
        import pwd
        info = UNIT.lstat()
        if not stat.S_ISREG(info.st_mode) or info.st_uid!=0 or info.st_mode & 0o022:
            raise RuntimeError('Torque system unit must remain a root-owned regular file')
        if not safe_unit_source(UNIT.read_text()):
            raise RuntimeError('Unexpected service execution hooks or privilege prefixes')
        unit = self.unit()
        if (unit['User']!=pwd.getpwuid(os.getuid()).pw_name or unit['NoNewPrivileges']!='yes' or
                unit['KillMode']!='control-group' or unit['Restart']!='on-failure' or unit['DropInPaths'] or
                any(unit.get(key) for key in ('ExecStartPre','ExecStartPost','ExecStop','ExecStopPost')) or
                any(unit.get(key) for key in ('Group','SupplementaryGroups','AmbientCapabilities','RootDirectory','RootImage')) or
                'argv[]=/opt/torque/current/runtime/python/bin/python -m torque.daemon ;' not in unit['ExecStart']):
            raise RuntimeError('Effective Torque service configuration differs from the reviewed baseline')
        if active and (unit['ActiveState']!='active' or unit['SubState']!='running' or int(unit['MainPID'])<=1):
            raise RuntimeError('Torque service is inactive; update did not start or repair it')
        return unit

    def check_delegation(self):
        own = Path('/proc/self/status').read_text()
        if re.search(r'^NoNewPrivs:\s+1$',own,re.M):
            raise RuntimeError('Run the updater over SSH outside torque.service (NoNewPrivileges is enabled)')
        policy = self.run(['sudo','-n','-l'])
        exact = '(root) NOPASSWD: /usr/bin/systemctl restart torque.service'
        if exact not in [line.strip() for line in policy.splitlines()]:
            raise RuntimeError('The exact password-free Torque restart grant is missing; run administrator bootstrap')

    def firmware(self):
        from . import Board
        with Board(socket_path=self.updater.config['socket']) as board:
            return board.info()

    def default_app(self):
        raw = self.run(['arduino-app-cli','properties','get','default','--format','json'])
        return json.loads(raw)['app']['FullPath']

    def baseline(self, *, bootstrap=False):
        unit = self.check_unit()
        if not bootstrap:
            self.check_delegation()
        state = self.status()
        device = state['device']
        if not bootstrap and (state.get('update_protocol')!=1 or state['release_root']!=str(self.updater.current.resolve()) or
                int(unit['MainPID'])!=state.get('pid')):
            raise RuntimeError('The running daemon does not match the selected update-capable release')
        if (not device['ready'] or device.get('reset_fault') or state['active'] or state['pending'] or
                state.get('maintenance') or device.get('owner')):
            raise RuntimeError('Torque is busy or outputs are uncertain; update refused without cancellation')
        return {'unit':unit,'unit_sha256':digest(UNIT),'settings_sha256':digest(self.updater.config_path),
                'default':self.default_app(),'firmware':self.firmware(),
                'epoch':state['epoch'],'session_id':state['session_id'],'model':state['model'],
                'permission_mode':state['default_permission_mode'],'credential_ready':state['credential_ready'],
                'retained':device.get('retained_matrix')}

    def stop(self, expected):
        unit = self.check_unit(active=False)
        if unit['ActiveState'] in ('inactive','failed') and unit['MainPID']=='0':
            return
        if (unit['MainPID']!=expected['MainPID'] or unit['InvocationID']!=expected['InvocationID']):
            raise RuntimeError('Service process changed before shutdown; no signal was sent')
        pid = int(unit['MainPID'])
        if pid<=1 or not hasattr(os,'pidfd_open') or not hasattr(signal,'pidfd_send_signal'):
            raise RuntimeError('Verified Linux pidfd signaling is required')
        descriptor = os.pidfd_open(pid)
        try:
            process = Path('/proc')/str(pid)
            uid = int(re.search(r'^Uid:\s+(\d+)',(process/'status').read_text(),re.M).group(1))
            if uid!=os.getuid() or '/torque.service' not in (process/'cgroup').read_text():
                raise RuntimeError('Service process identity did not match the runtime user/control group')
            current = self.unit()
            if current['MainPID']!=unit['MainPID'] or current['InvocationID']!=unit['InvocationID']:
                raise RuntimeError('Service invocation changed during pidfd validation')
            signal.pidfd_send_signal(descriptor,signal.SIGTERM)
            if not select.select([descriptor],[],[],30)[0]:
                raise RuntimeError('Graceful service shutdown timed out; no link changed')
        finally:
            os.close(descriptor)
        deadline = time.monotonic()+5
        while time.monotonic()<deadline:
            current = self.unit()
            if current['ActiveState']=='inactive' and current['MainPID']=='0':
                return
            if current['MainPID'] not in ('0',unit['MainPID']):
                raise RuntimeError('Service restarted unexpectedly before activation')
            time.sleep(.1)
        raise RuntimeError('Service did not become inactive after clean shutdown')

    def restart(self):
        try:
            self.run(RESTART,timeout=45)
        except RuntimeError:
            raw=self.run(['/usr/bin/systemctl','show','torque.service','--property=Result,StartLimitIntervalUSec'])
            values=dict(line.split('=',1) for line in raw.splitlines() if '=' in line)
            interval=re.fullmatch(r'(\d+(?:\.\d+)?)s',values.get('StartLimitIntervalUSec',''))
            if values.get('Result')!='start-limit-hit' or not interval or float(interval[1])>55:
                raise
            time.sleep(float(interval[1])+1)
            self.run(RESTART,timeout=45)

    def ready(self, target, *, old_epoch=None):
        expected_version=tomllib.loads((target/'pyproject.toml').read_text())['project']['version']
        deadline = time.monotonic()+60
        while time.monotonic()<deadline:
            try:
                state = self.status()
                if (state.get('release_root')==str(target) and state.get('release_id')==target.name and
                        state.get('application_version')==expected_version and state.get('update_protocol')==1 and
                        type(state.get('pid')) is int and state['pid']>1 and
                        state['device']['ready'] and state['epoch']!=old_epoch):
                    return state
            except (RuntimeError,OSError,ValueError):
                pass
            time.sleep(.25)
        raise RuntimeError('Intended runtime did not become ready; inspect update recovery status')

    def verify(self, record, target, *, new_invocation=True):
        before = record['baseline']
        state = self.ready(target,old_epoch=before['epoch'] if new_invocation else None)
        unit = self.check_unit()
        if (int(unit['MainPID'])!=state['pid'] or (new_invocation and
                unit['InvocationID']==before['unit']['InvocationID'])):
            raise RuntimeError('Readiness came from the wrong systemd invocation')
        if (digest(UNIT)!=before['unit_sha256'] or digest(self.updater.config_path)!=before['settings_sha256'] or
                self.default_app()!=before['default'] or self.firmware()!=before['firmware']):
            raise RuntimeError('Firmware, boot default, settings or service configuration changed during update')
        if (state['session_id']!=before['session_id'] or state['model']!=before['model'] or
                state['default_permission_mode']!=before['permission_mode'] or
                (before['credential_ready'] and not state['credential_ready'])):
            raise RuntimeError('Session, model, permissions or credential readiness changed')
        if before['retained']:
            device = state['device']
            if (device.get('retained_matrix')!=before['retained'] or
                    device['snapshot']['matrix']['frame_hex']!=before['retained']['frame_hex'] or
                    device['snapshot']['matrix']['playing']):
                raise RuntimeError('Retained output was not adopted unchanged; no replay was requested')
        return state


class Updater:
    def __init__(self, config=None, *, base=BASE, enabled=ENABLED, host=None):
        self.config_path = Path.home()/'.config/torque/settings.json'
        self.config = config or json.loads(self.config_path.read_text())
        if Path(base).is_symlink():
            raise RuntimeError('Runtime installation parent must not be a symlink')
        self.base, self.enabled = Path(base).resolve(), Path(enabled)
        self.releases, self.current = self.base/'releases', self.base/'current'
        self.store = Store(self.config['state_dir'])
        self.host = host or Host(self)

    def normal_user(self):
        if os.geteuid()==0:
            raise RuntimeError('Routine runtime updates must run as the normal account, never sudo')
        status=Path('/proc/self/status')
        if status.exists() and re.search(r'^NoNewPrivs:\s+1$',status.read_text(),re.M):
            raise RuntimeError('Mutating updates must run over SSH outside torque.service')
        os.umask(0o022)

    def configured(self):
        self.normal_user()
        expected={'release_root':str(self.current),'python':str(self.current/'runtime/python/bin/python'),
                  'node':str(self.current/'runtime/node/bin/node'),'libfx_path':str(self.current/'node_modules/libfx')}
        if any(self.config.get(key)!=value for key,value in expected.items()):
            raise RuntimeError('Runtime paths differ from the declared managed dependency bundle')
        if not self.enabled.exists() and not self.enabled.is_symlink():
            raise RuntimeError('Unattended updates need the administrator bootstrap first; see install/README.md')
        info = self.enabled.lstat()
        if (not stat.S_ISREG(info.st_mode) or info.st_uid!=0 or info.st_mode & 0o022):
            raise RuntimeError('Administrator bootstrap record is unsafe')
        value = json.loads(self.enabled.read_text())
        if value['uid']!=os.getuid() or value['base']!=str(self.base) or not value.get('complete'):
            raise RuntimeError('Bootstrap belongs to a different runtime account or path')
        for path in (self.base,self.releases):
            info = path.lstat()
            if not stat.S_ISDIR(info.st_mode) or info.st_uid!=os.getuid() or info.st_mode & 0o022:
                raise RuntimeError('Runtime ownership does not match the administrator bootstrap')
        if not self.current.is_symlink() or self.current.lstat().st_uid!=os.getuid():
            raise RuntimeError('Runtime selection must be an owned symbolic link')

    def record(self, update_id):
        record = self.store.get(update_id)
        for name in ('base','target'):
            if not isinstance(record.get(name),str):raise RuntimeError('Malformed update release path')
            path = Path(record[name])
            if path.parent!=self.releases or not RELEASE_ID.fullmatch(path.name) or path.is_symlink():
                raise RuntimeError('Update record escapes the managed release directory')
        return record

    def prepare(self, source, *, scope='application'):
        self.configured()
        if scope not in ('application','examples'):raise ValueError('Unknown update scope')
        source = Path(source).resolve()
        names = APPLICATION if scope=='application' else ('examples',)
        with self.store.lock():
            if self.store.pending():
                raise RuntimeError('Recover the pending update before preparing another release')
            previous = self.current.resolve()
            old = verify_release(previous)
            frozen = input_files(source,names)
            with (previous/'pyproject.toml').open('rb') as stream:
                before_project = tomllib.load(stream)
            project=before_project
            if scope=='application':
                with (source/'pyproject.toml').open('rb') as stream:
                    project = tomllib.load(stream)
            if (project['project'].get('dependencies')!=before_project['project'].get('dependencies') or
                    project.get('build-system')!=before_project.get('build-system')):
                raise RuntimeError('Dependency changes require a separate reviewed bundle')
            deps = dependencies(previous)
            # Hash the resulting application, so a repeated examples-only update
            # is also a no-op when another source scope built the current release.
            combined = input_files(previous,APPLICATION)
            for name in names:
                combined = {p:v for p,v in combined.items() if p!=name and not p.startswith(name+'/')}
            combined.update(frozen)
            identity = content_id({'application':combined,'dependencies':deps})
            if old.get('input_id')==identity:
                return {'unchanged':True,'release':previous.name,'no_restart':True}
            version = project['project']['version'] if scope=='application' else before_project['project']['version']
            release_id = version+'-'+identity[:12]
            if not RELEASE_ID.fullmatch(release_id):
                raise RuntimeError('Invalid application release version')
            target = self.releases/release_id
            if target.exists() and (target/'.incomplete').exists():
                with Lock(self.store.leases/(release_id+'.lock')):
                    if incomplete_identity(target)!=identity:
                        raise RuntimeError('Incomplete release belongs to other inputs')
                    shutil.rmtree(target)
            if target.exists():
                value = verify_release(target)
                if value.get('input_id')!=identity:
                    raise RuntimeError('Release identity collision')
            else:
                size = sum(p.stat().st_size for p in previous.rglob('*') if p.is_file() and not p.is_symlink())
                if shutil.disk_usage(self.base).free < size+64*1024*1024:
                    raise RuntimeError('Insufficient disk space while keeping the active rollback release')
                shutil.copytree(previous,target,symlinks=True,ignore=shutil.ignore_patterns('__pycache__','.cache'))
                (target/'.incomplete').write_text(identity)
                copy_inputs(source,target,names)
                if input_files(source,names)!=frozen:
                    raise RuntimeError('Source changed during preparation; candidate remains incomplete')
                if declared_controller(target)!=(old['firmware'],old['protocol']):
                    raise RuntimeError('Candidate declares another controller bundle; no automatic firmware change')
                fresh_python(target)
                smoke(target,self.config,self.store.root/('smoke-'+release_id))
                if input_files(source,names)!=frozen:
                    raise RuntimeError('Source changed while candidate was building; candidate remains incomplete')
                if input_files(target,APPLICATION)!=combined or dependencies(target)!=deps:
                    raise RuntimeError('Prepared source/dependency identity did not match frozen inputs')
                manifest(target,{**{k:v for k,v in old.items() if k not in ('artifacts','files','links')},'input_id':identity})
                (target/'.incomplete').unlink()
            record = {'id':uuid.uuid4().hex,'phase':'prepared','base':str(previous),'target':str(target),
                      'input_id':identity,'scope':scope,'created':time.time()}
            self.store.save(record)
            return record

    def phase(self, record, phase, **fields):
        record.update(phase=phase,updated=time.time(),**fields)
        self.store.save(record)

    def switch(self, record, target):
        current = self.current.resolve()
        if str(current) not in (record['base'],record['target']):
            raise RuntimeError('Current points at another transaction; no link was changed')
        temporary = self.base/('.update-'+record['id'])
        self.clean_temporary(record)
        temporary.symlink_to(target)
        os.replace(temporary,self.current)
        sync_dir(self.base)

    def clean_temporary(self,record):
        temporary=self.base/('.update-'+record['id'])
        if temporary.exists() or temporary.is_symlink():
            if temporary.is_symlink() and str(temporary.resolve()) in (record['base'],record['target']):
                temporary.unlink()
            else:
                raise RuntimeError('Activation temporary path is not owned by this transaction')
            sync_dir(self.base)

    def installed(self, record, target):
        path = Path(self.config['state_dir'])/'installed.json'
        value = json.loads(path.read_text())
        value.update(release=target.name,previous_release=record['base'],identity=record['baseline']['firmware'])
        write_json(path,value)

    def finish(self, record, state):
        self.phase(record,'verified',verified_epoch=state['epoch'])
        self.installed(record,Path(record['target']))
        self.phase(record,'committed',firmware_boot_unchanged=True,boot_default_preserved=True,
                   service_configuration_preserved=True,retained_output_adopted=bool(record['baseline']['retained']),
                   inference_performed=False,firmware_upload=False)
        self.host.control('release',record)
        return record

    def restore(self, record):
        base, target = Path(record['base']), Path(record['target'])
        if self.current.resolve() not in (base,target):
            raise RuntimeError('A different release owns current; recovery did not undo it')
        self.clean_temporary(record)
        try:
            state = self.host.status()
        except (RuntimeError,OSError,ValueError):
            state = None
        if self.current.resolve()==base and state and state.get('release_root')==str(base):
            # A refused admission never cancels work that won the race first.
            self.phase(record,'rolled_back')
            if state.get('update_id')==record['id']:
                self.host.control('release',record)
            else:
                self.store.clear(record['id'])
            return record
        unit = self.host.check_unit(active=False)
        if unit['MainPID']!='0' or unit['ActiveState'] not in ('inactive','failed'):
            self.host.stop(unit)
        self.phase(record,'rolling-back')
        self.switch(record,base)
        self.host.restart()
        state = self.host.verify(record,base)
        self.installed(record,base)
        self.phase(record,'rolled_back',rollback_epoch=state['epoch'])
        self.host.control('release',record)
        return record

    @contextmanager
    def signals(self):
        previous = {}
        def interrupted(number, _frame):
            raise RuntimeError('Update interrupted by signal '+str(number))
        try:
            for number in (signal.SIGINT,signal.SIGTERM,signal.SIGHUP):
                previous[number] = signal.signal(number,interrupted)
            yield
        finally:
            for number,handler in previous.items():
                signal.signal(number,handler)

    def apply(self, update_id):
        self.configured()
        with self.store.lock(),self.store.use(),self.signals():
            record = self.record(update_id)
            if record['phase']=='committed':
                pending=self.store.pending()
                if pending and pending['id']==record['id']:
                    if str(self.current.resolve())!=record['target']:
                        raise RuntimeError('Committed update no longer owns current; inspect recovery')
                    state=self.host.verify(record,Path(record['target']))
                    return self.finish(record,state)
                if str(self.current.resolve())==record['target']:
                    verify_release(Path(record['target']))
                return {**record,'already_committed':True,'no_restart':True}
            if record['phase']!='prepared' or self.store.pending():
                raise RuntimeError('Transaction needs recover, not another apply')
            if str(self.current.resolve())!=record['base']:
                raise RuntimeError('Prepared base is stale; prepare again without changing the active release')
            metadata = verify_release(Path(record['target']))
            verify_release(Path(record['base']))
            if metadata.get('input_id')!=record['input_id']:
                raise RuntimeError('Candidate input identity differs from the prepared plan')
            baseline = self.host.baseline()
            if (baseline['firmware']['version']!=metadata['firmware'] or
                    baseline['firmware']['protocol']!=metadata['protocol']):
                raise RuntimeError('Candidate requires a different controller; no firmware maintenance is automatic')
            record['baseline'] = baseline
            self.phase(record,'fencing')
            self.store.activate(record['id'])
            try:
                fenced = self.host.control('fence',record,expected_release=record['base'])
                if fenced['epoch']!=baseline['epoch'] or fenced['pid']!=int(baseline['unit']['MainPID']):
                    raise RuntimeError('Daemon changed during update admission')
                self.phase(record,'fenced')
                self.host.stop(baseline['unit'])
                self.phase(record,'stopped')
                self.phase(record,'activating')
                self.switch(record,Path(record['target']))
                self.phase(record,'activated')
                self.host.restart()
                self.phase(record,'restarted')
                state = self.host.verify(record,Path(record['target']))
                return self.finish(record,state)
            except BaseException as error:
                if record['phase'] in ('verified','committed'):
                    raise RuntimeError('Runtime was verified; run torque update recover '+record['id']+
                                       ' to finish bookkeeping without another restart') from error
                self.phase(record,record['phase'],error=str(error))
                # Do not allow a second terminal signal to interrupt bounded recovery.
                handlers = {s:signal.signal(s,signal.SIG_IGN) for s in (signal.SIGINT,signal.SIGTERM,signal.SIGHUP)}
                try:
                    self.restore(record)
                except BaseException as recovery_error:
                    self.phase(record,'recovery-needed',recovery_error=str(recovery_error))
                    raise RuntimeError('Update needs recovery: '+record['id']+'; '+str(recovery_error)) from error
                finally:
                    for number,handler in handlers.items():signal.signal(number,handler)
                raise RuntimeError('Update did not complete; previous runtime restored: '+str(error)) from error

    def recover(self, update_id):
        self.configured()
        with self.store.lock(),self.store.use(),self.signals():
            record = self.record(update_id)
            active = self.store.pending()
            if active and active['id']!=update_id:
                raise RuntimeError('Another transaction owns recovery')
            if record['phase'] in ('committed','rolled_back') and not active:
                return {**record,'no_restart':True}
            if not active:
                if record['phase'] in ('prepared','fencing') and str(self.current.resolve())==record['base']:
                    self.phase(record,'rolled_back')
                    return {**record,'no_restart':True}
                raise RuntimeError('This record does not own a pending activation')
            if str(self.current.resolve())==record['target']:
                try:
                    verify_release(Path(record['target']))
                    state = self.host.verify(record,Path(record['target']))
                except (RuntimeError,OSError,ValueError):
                    pass
                else:
                    return self.finish(record,state)
            return self.restore(record)

    def gc(self):
        self.configured()
        with self.store.lock():
            if self.store.pending():
                raise RuntimeError('Recover the pending update before collecting releases')
            current = self.current.resolve()
            records = [read_json(p) for p in self.store.records.glob('*.json')]
            keep = {str(current)}
            commits = [r for r in records if r['phase']=='committed' and r['target']==str(current)]
            if commits:
                keep.add(max(commits,key=lambda r:r['created'])['base'])
            keep.update(r['target'] for r in records if r['phase']=='prepared')
            removed, skipped = [], []
            for release in self.releases.iterdir():
                if str(release) in keep or not RELEASE_ID.fullmatch(release.name) or release.is_symlink():
                    continue
                try:
                    with Lock(self.store.leases/(release.name+'.lock')):
                        if (release/'.incomplete').exists():incomplete_identity(release)
                        else:verify_managed_tree(release)
                        shutil.rmtree(release)
                    removed.append(release.name)
                except (RuntimeError,OSError,ValueError):
                    skipped.append(release.name)
            return {'kept':sorted(Path(p).name for p in keep),'removed':removed,'skipped':skipped}


def add_commands(sub):
    parser = sub.add_parser('update',help='Prepare, activate or recover a Linux runtime update')
    commands = parser.add_subparsers(dest='update_action',required=True)
    prepare = commands.add_parser('prepare')
    prepare.add_argument('--source',type=Path,required=True)
    prepare.add_argument('--scope',choices=('application','examples'),default='application')
    for name in ('apply','status','recover'):
        commands.add_parser(name).add_argument('update_id')
    commands.add_parser('gc')


def dispatch(args):
    updater = Updater()
    if args.update_action=='prepare':
        result = updater.prepare(args.source,scope=args.scope)
    elif args.update_action=='status':
        result = updater.store.get(args.update_id)
    elif args.update_action=='gc':
        result = updater.gc()
    else:
        result = getattr(updater,args.update_action)(args.update_id)
    print(json.dumps(result,indent=2))
    return 0


def bootstrap_build(release):
    """Called only after the administrator allocates an owned permanent prefix."""
    updater = Updater();updater.normal_user()
    release = Path(release)
    if (release.parent!=updater.releases or not RELEASE_ID.fullmatch(release.name) or
            release.is_symlink() or release.stat().st_uid!=os.getuid()):
        raise RuntimeError('Bootstrap build must use its allocated owned release')
    seed = release/'runtime/.python-update-seed'
    if seed.exists():
        if seed.is_symlink() or seed.stat().st_uid!=os.getuid() or not (release/'.incomplete').exists():
            raise RuntimeError('Unsafe interrupted bootstrap seed')
        python = release/'runtime/python'
        if python.exists():shutil.rmtree(python)
        seed.rename(python)
    (release/'.incomplete').write_text('bootstrap')
    old = json.loads((release/'release.json').read_text())
    build_wheels = release/'runtime/build-wheels'
    build_wheels.mkdir(exist_ok=True)
    wheel=build_wheels/BUILD_TOOL
    if not wheel.exists():
        subprocess.run([str(release/'runtime/python/bin/python'),'-I','-m','pip','--isolated','download',
                        '--no-deps','--only-binary=:all:','--dest',str(build_wheels),'setuptools==84.2.0'],
                       env={'HOME':str(Path.home()),'PATH':'/usr/bin:/bin','LANG':'C.UTF-8'},
                       check=True,capture_output=True,timeout=120)
    if digest(wheel)!=BUILD_TOOL_SHA256:
        raise RuntimeError('Bootstrap build-tool wheel hash mismatch')
    fresh_python(release)
    smoke(release,updater.config,updater.store.root/('bootstrap-smoke-'+release.name))
    if declared_controller(release)!=(old['firmware'],old['protocol']):
        raise RuntimeError('Bootstrap candidate changes the controller bundle')
    identity = content_id({'application':input_files(release,APPLICATION),'dependencies':dependencies(release)})
    value = manifest(release,{**{k:v for k,v in old.items() if k not in ('artifacts','files','links')},'input_id':identity})
    (release/'.incomplete').unlink()
    verify_release(release)
    return {'built':True,'release':release.name,'input_id':value['input_id']}


def bootstrap_arm(release):
    updater = Updater();updater.normal_user()
    target = Path(release)
    verify_release(target)
    pending = updater.store.pending()
    if pending:
        if pending.get('kind')=='bootstrap' and pending['target']==str(target):
            return {'update_id':pending['id']}
        raise RuntimeError('Another update owns the pending transaction')
    baseline = updater.host.baseline(bootstrap=True)
    record = {'id':uuid.uuid4().hex,'kind':'bootstrap','phase':'fencing','created':time.time(),
              'base':str(updater.current.resolve()),'target':str(target),'baseline':baseline}
    updater.store.save(record);updater.store.activate(record['id'])
    return {'update_id':record['id']}


def bootstrap_commit(update_id):
    updater = Updater();updater.normal_user()
    record = updater.record(update_id)
    if str(updater.current.resolve())!=record['target']:
        raise RuntimeError('Bootstrap target is not selected')
    if record['phase']=='committed' and updater.store.pending() is None:
        verify_release(Path(record['target']))
        return {**record,'already_committed':True,'no_restart':True}
    state = updater.host.verify(record,Path(record['target']))
    return updater.finish(record,state)


if __name__=='__main__':
    try:
        operation = sys.argv[1]
        if operation=='bootstrap-init':
            updater=Updater();updater.normal_user()
            with updater.store.lock(),updater.store.use():pass
            print(json.dumps({'ready':True}))
        elif operation=='bootstrap-build':
            print(json.dumps(bootstrap_build(Path(sys.argv[2]))))
        elif operation=='bootstrap-arm':
            print(json.dumps(bootstrap_arm(Path(sys.argv[2]))))
        elif operation=='bootstrap-commit':
            print(json.dumps(bootstrap_commit(sys.argv[2])))
        else:
            from .cli import main
            raise SystemExit(main(['update',*sys.argv[1:]]))
    except (OSError,RuntimeError,ValueError,KeyError,subprocess.SubprocessError) as error:
        print('Torque update: '+str(error),file=sys.stderr)
        raise SystemExit(1)
