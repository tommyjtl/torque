"""Normal-user service: private IPC, checked host tools, sessions and MCU state."""
import argparse
import asyncio
from collections import deque
import json
import importlib.metadata
import os
from pathlib import Path
import signal
import socket
import stat
import struct
import sys
import tempfile
import time
import tomllib
import uuid
from .protocol import LIMIT, VERSION, encode
from .device import Device
from . import policy
from .models import ModelCatalog, private_json, save_json
from .runtime import Store


def private_dir(path):
    path = Path(path)
    path.mkdir(mode=0o700, parents=True, exist_ok=True)
    info = path.lstat()
    if not stat.S_ISDIR(info.st_mode) or info.st_uid != os.getuid() or info.st_mode & 0o077:
        raise RuntimeError('Torque state directory must be an owner-only directory: ' + str(path))
    return path


def write_json(path, value):
    path = Path(path)
    temporary = path.with_name('.' + path.name + '-' + uuid.uuid4().hex)
    try:
        with temporary.open('x') as stream:
            os.chmod(temporary, 0o600)
            json.dump(value, stream)
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def workspace_path(root, value):
    if not isinstance(value, str) or not value or len(value) > 4096:
        raise ValueError('Invalid file path')
    return (Path(root) / value).resolve()


class Daemon:
    def __init__(self, config, device_factory=Device, *, config_path=None):
        config = dict(config)
        selected = Path(config['release_root'])
        resolved = selected.resolve()
        for name in ('python', 'node', 'libfx_path'):
            if name in config and Path(config[name]).is_relative_to(selected):
                config[name] = str(resolved/Path(config[name]).relative_to(selected))
        config['release_root'] = str(resolved)
        self.config = config
        self.config_path = Path(config_path) if config_path else Path.home() / '.config/torque/settings.json'
        self.models = ModelCatalog(config)
        self.maintenance = None
        self.probe_task = None
        self.start_lock = asyncio.Lock()
        self.cancelling = False
        self.root = Path(config['release_root']).resolve()
        self.application_version = (importlib.metadata.version('torque-uno-q') if (self.root/'release.json').exists() else
                                    tomllib.loads((self.root/'pyproject.toml').read_text())['project']['version'])
        self.workspace = Path(config['workspace']).resolve()
        self.state = private_dir(config['state_dir'])
        credential = Path(config['key_file'])
        self._secret = ''
        self.credential_error = None
        try:
            info = credential.lstat()
            if not stat.S_ISREG(info.st_mode) or info.st_uid != os.getuid() or stat.S_IMODE(info.st_mode) != 0o600:
                raise RuntimeError('Credential must be an owner-owned regular file with mode 600')
            self._secret = credential.read_text().strip()
            if not self._secret or any(c.isspace() for c in self._secret):
                raise RuntimeError('Invalid credential file')
        except (OSError, RuntimeError) as error:
            self.credential_error = str(error) if isinstance(error, RuntimeError) else 'Credential file unavailable; rerun setup privately'
        self.events = deque(maxlen=512)
        self.cursor = 0
        self.epoch = uuid.uuid4().hex
        self.loop = asyncio.get_running_loop()
        self.device = device_factory(self.root / 'assets/status.json', self.publish_thread, self.state / 'display.json')
        self.worker = None
        self.worker_ready = False
        self.pending = {}
        self.turn_active = False
        self.session_id = None
        self.outcome = 'idle'
        self.default_permissions = policy.mode(config.get('permission_mode', 'auto'))
        self.turn_permissions = self.default_permissions
        self.skills = []
        self.clients = set()
        self.tool_tasks = set()
        self.registry = self.state / 'session.json'
        if self.registry.exists():
            previous = json.loads(self.registry.read_text())
            self.session_id = previous.get('session_id')
            self.outcome = 'interrupted' if previous.get('active') else previous.get('outcome', 'idle')
        self.updates = Store(self.state)
        pending_update = self.updates.pending()
        self.update_id = pending_update['id'] if pending_update else None
        if pending_update:
            self.maintenance = 'runtime-update'
            self.device.set_maintenance(True)

    def publish_thread(self, event):
        self.loop.call_soon_threadsafe(self.publish, event)

    def publish(self, event):
        self.cursor += 1
        self.events.append({'cursor': self.cursor, **self.redact(event)})

    def redact(self, value):
        if isinstance(value, str):
            return value.replace(self._secret, '[REDACTED]') if self._secret else value
        if isinstance(value, dict):
            return {key: self.redact(item) for key, item in value.items()}
        if isinstance(value, list):
            return [self.redact(item) for item in value]
        return value

    def persist(self):
        write_json(self.registry, {'session_id': self.session_id, 'active': self.turn_active,
                                  'outcome': self.outcome})

    def snapshot(self):
        return {'v': VERSION, 'epoch': self.epoch, 'cursor': self.cursor,
                'release_root': str(self.root), 'release_id': self.root.name,
                'application_version': self.application_version,
                'pid': os.getpid(), 'update_protocol': 1, 'update_id': self.update_id,
                'workspace': str(self.workspace), 'model': self.config['model'],
                'engine_ready': self.worker_ready, 'skills': self.skills,
                'credential_ready': self.credential_error is None, 'credential_error': self.credential_error,
                'active': self.turn_active, 'session_id': self.session_id, 'outcome': self.outcome,
                'permission_mode': self.turn_permissions if self.turn_active else self.default_permissions,
                'default_permission_mode': self.default_permissions,
                'maintenance': self.maintenance or ('cancel' if self.cancelling else None),
                'pending': [p['public'] for p in self.pending.values()],
                'device': self.device.status()}

    async def engine_send(self, value):
        if not self.worker or self.worker.returncode is not None:
            raise RuntimeError('Engine worker unavailable')
        self.worker.stdin.write(encode(value))
        await self.worker.stdin.drain()

    async def start_engine(self):
        if self.credential_error:
            raise RuntimeError(self.credential_error)
        if self.worker and self.worker.returncode is None:
            # Recreate an idle worker so user skills/instructions are refreshed.
            # Conversation history lives in libfx's separate durable store.
            self.worker.stdin.close()
            await asyncio.wait_for(self.worker.wait(), 8)
            await self.worker_task
        options = {**self.config, 'agent_dir': str(self.root / 'agent'),
                   'sessions_dir': str(private_dir(self.state / 'sessions')), 'permission_mode': self.turn_permissions}
        options_file = self.state / 'engine.json'
        write_json(options_file, options)  # Contains credential PATH only.
        self.worker = await asyncio.create_subprocess_exec(
            self.config['node'], str(self.root / 'engines/fx/worker.mjs'), str(options_file),
            stdin=asyncio.subprocess.PIPE, stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.DEVNULL, limit=LIMIT, cwd=self.workspace,
            env={'HOME': str(Path.home()), 'PATH': '/usr/bin:/bin', 'LANG': 'C.UTF-8'})
        self.worker_task = asyncio.create_task(self.read_engine(self.worker))

    async def read_engine(self, worker):
        try:
            while raw := await worker.stdout.readline():
                event = json.loads(raw)
                kind = event.get('type')
                if kind == 'worker.ready':
                    self.worker_ready = True
                    self.skills = event['skills']
                elif kind == 'turn.accepted':
                    self.session_id = event['sessionId']
                    self.persist()
                elif kind in ('turn.result', 'worker.error'):
                    self.turn_active = False
                    self.outcome = event.get('result', {}).get('stopReason', 'error')
                    self.device.set_state('error' if self.outcome == 'error' else 'standby')
                    self.persist()
                    asyncio.create_task(self.reap_idle(worker))
                elif kind == 'tool.request':
                    task = asyncio.create_task(self.tool(event))
                    self.tool_tasks.add(task)
                    task.add_done_callback(self.tool_tasks.discard)
                self.publish(event)
        except (ValueError, OSError, asyncio.LimitOverrunError):
            self.publish({'type': 'worker.error', 'error': 'Invalid engine connection'})
        finally:
            self.worker_ready = False
            if self.turn_active:
                self.turn_active = False
                self.outcome = 'interrupted'
                self.device.set_state('error')
                self.persist()
                self.publish({'type': 'worker.error', 'error': 'Engine exited; no tool was retried'})
            for pending in list(self.pending.values()):
                if not pending['future'].done():
                    pending['future'].set_result(False)

    async def reap_idle(self, worker):
        await asyncio.sleep(30)
        if worker is self.worker and worker.returncode is None and not self.turn_active:
            worker.stdin.close()

    async def stop_engine(self):
        worker = self.worker
        if worker and worker.returncode is None:
            worker.stdin.close()
            try:
                await asyncio.wait_for(worker.wait(), 4)
            except asyncio.TimeoutError:
                worker.kill()
                await worker.wait()
        if getattr(self, 'worker_task', None):
            await self.worker_task
        self.worker = None
        self.worker_ready = False

    async def cancel_active(self):
        async with self.start_lock:
            if self.maintenance == 'runtime-update':
                raise RuntimeError('Runtime update is in progress; cancellation refused')
            self.cancelling = True
            try:
                return await self._cancel_work()
            finally:
                self.cancelling = False

    async def _cancel_work(self):
        active = self.turn_active
        if self.probe_task and not self.probe_task.done():
            self.probe_task.cancel()
            await asyncio.gather(self.probe_task, return_exceptions=True)
        for pending in list(self.pending.values()):
            if not pending['future'].done():
                pending['future'].set_result(False)
        tasks = list(self.tool_tasks)
        for task in tasks:
            task.cancel()
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)
        if active and self.worker and self.worker.returncode is None:
            try:
                await self.engine_send({'op': 'cancel'})
                deadline = self.loop.time() + 3
                while self.turn_active and self.loop.time() < deadline:
                    await asyncio.sleep(0.02)
            except (RuntimeError, OSError):
                pass
        await self.stop_engine()
        self.turn_active = False
        if active:
            self.outcome = 'cancelled'
            self.device.set_state('standby')
            self.persist()
        return {'cancelled': active, 'managed_tasks_stopped': len(tasks)}

    def reserve(self, operation):
        if self.maintenance or self.turn_active or self.cancelling:
            raise RuntimeError('Work is active; wait or cancel before changing the model')
        self.maintenance = operation

    async def select_model(self, name):
        self.reserve('model-selection')
        try:
            if name == self.config['model']:
                return {'model': name, 'changed': False, 'source': self.models.profile(name)['source']}
            selected, listing = await asyncio.to_thread(self.models.selectable, name)
            settings = private_json(self.config_path)
            settings['model'] = name
            settings['models'] = {**settings.get('models', {}), name: selected['metadata']}
            settings['model_profiles'] = {**settings.get('model_profiles', {}), name: {'source': selected['source']}}
            await self.stop_engine()
            save_json(self.config_path, settings)
            for key in ('model', 'models', 'model_profiles'):
                self.config[key] = settings[key]
            self.publish({'type': 'model.changed', 'model': name})
            return {'model': name, 'changed': True, 'source': selected['source'],
                    'stale_discovery': listing['stale'], 'tool_support': selected['tool_support']}
        finally:
            self.maintenance = None

    async def run_model_test(self, name, profile):
        with tempfile.TemporaryDirectory(prefix='model-probe-', dir=self.state) as directory:
            options = Path(directory) / 'options.json'
            write_json(options, {'key_file': self.config['key_file'], 'libfx_path': self.config['libfx_path'],
                                 'model': name, 'profile': profile})
            process = await asyncio.create_subprocess_exec(
                self.config['node'], str(self.root / 'engines/fx/model-test.mjs'), str(options),
                stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.DEVNULL,
                start_new_session=True, env={'HOME': str(Path.home()), 'PATH': '/usr/bin:/bin'})
            try:
                raw, _ = await asyncio.wait_for(process.communicate(), 90)
                if process.returncode != 0 or len(raw) > 32768:
                    raise RuntimeError('Model test process failed')
                result = json.loads(raw)
                if not isinstance(result, dict) or any(type(result.get(key)) is not bool for key in ('passed', 'text', 'tool')):
                    raise ValueError('Invalid model test result')
                return self.redact(result)
            finally:
                if process.returncode is None:
                    os.killpg(process.pid, signal.SIGTERM)
                    try:
                        await asyncio.wait_for(process.wait(), 2)
                    except asyncio.TimeoutError:
                        os.killpg(process.pid, signal.SIGKILL)
                        await process.wait()

    async def test_model(self, name):
        self.reserve('model-test')
        self.probe_task = asyncio.create_task(self._test_model_body(name))
        try:
            try:
                return await self.probe_task
            except asyncio.CancelledError:
                return {'model': name, 'passed': False, 'cancelled': True}
        finally:
            self.probe_task = None
            if self.maintenance == 'model-test':
                self.maintenance = None

    async def _test_model_body(self, name):
        selected, _ = await asyncio.to_thread(self.models.selectable, name)
        _, generation = self.models.credential()
        result = {'model': name, **await self.run_model_test(name, selected['metadata'])}
        try:
            await asyncio.to_thread(self.models.record, name, result, generation=generation)
        except (OSError, ValueError, RuntimeError):
            result['cache_error'] = 'Probe result could not be cached'
        return result

    async def reset_outputs(self, blank):
        if type(blank) is not bool:
            raise ValueError('Blank must be boolean')
        if self.maintenance not in (None, 'model-test'):
            raise RuntimeError('Another control operation is in progress')
        self.maintenance = 'reset'
        self.device.set_maintenance(True)
        try:
            cancelled = await self.cancel_active()
            deadline = self.loop.time() + 3
            while self.device.status().get('owner') is not None and self.loop.time() < deadline:
                await asyncio.sleep(0.02)
            result = await asyncio.to_thread(self.device.reset, blank=blank)
            self.publish({'type': 'device.reset', 'passed': result['passed'], 'target': result['target']})
            return {**result, **cancelled}
        finally:
            self.device.set_maintenance(False)
            self.maintenance = None

    def file_path(self, value, *, write=False):
        path = workspace_path(self.workspace, value)
        roots = [self.workspace / 'projects'] if write else [self.workspace, self.root]
        if not any(path.is_relative_to(root) for root in roots):
            raise ValueError('File path is outside the allowed project/resource directories')
        if write and path == self.workspace / 'projects':
            raise ValueError('Expected a project file')
        return path

    async def execute(self, name, args):
        policy.validate(name, args)
        if (getattr(self, 'maintenance', None) or getattr(self, 'cancelling', False)) and name not in policy.READS:
            raise RuntimeError('A control operation is in progress; tool was not executed')
        if name == 'input_capabilities':
            from .input import input_capabilities
            return await asyncio.to_thread(input_capabilities)
        if name in ('device_capabilities', 'matrix_fill', 'matrix_draw', 'matrix_clear', 'matrix_release', 'rgb_set'):
            return await asyncio.to_thread(self.device.action, name, args)
        if name == 'device_snapshot':
            result = await asyncio.to_thread(self.device.request, 'engine-read', 'snapshot', {})
            return {**result, 'display': self.device.status()}
        if name == 'list_directory':
            path = self.file_path(args['path'])
            entries = sorted(path.iterdir(), key=lambda p: p.name)
            return {'path': str(path), 'entries': [{'name': p.name, 'directory': p.is_dir(), 'symlink': p.is_symlink()}
                                                  for p in entries[:200]], 'truncated': len(entries) > 200}
        if name == 'search_files':
            path = self.file_path(args['path'])
            matches, scanned = [], 0
            for file in path.rglob('*'):
                if file.is_symlink() or not file.is_file() or any(p.startswith('.') or p == '__pycache__' for p in file.relative_to(path).parts):
                    continue
                scanned += 1
                if scanned > 500 or len(matches) >= 100:
                    break
                if file.stat().st_size > 65536:
                    continue
                try:
                    lines = file.read_text().splitlines()
                except UnicodeError:
                    continue
                for number, line in enumerate(lines, 1):
                    if args['query'] in line:
                        matches.append({'path': str(file), 'line': number, 'text': self.redact(line[:500])})
                        if len(matches) >= 100:
                            break
            return {'matches': matches, 'bounded': scanned > 500 or len(matches) >= 100}
        if name == 'read_file':
            path = self.file_path(args['path'])
            if path.stat().st_size > 65536:
                raise ValueError('File exceeds the 64 KiB read limit')
            return self.redact(path.read_text())
        if name == 'write_file':
            path = self.file_path(args['path'], write=True)
            data = args['content']
            if not isinstance(data, str) or len(data.encode()) > 65536:
                raise ValueError('File exceeds the 64 KiB write limit')
            path.parent.mkdir(parents=True, exist_ok=True)
            # Recheck after creating parents; follow no final symlink.
            if path.is_symlink() or self.file_path(args['path'], write=True) != path:
                raise ValueError('Project file changed during validation')
            fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC | os.O_NOFOLLOW, 0o644)
            with os.fdopen(fd, 'w') as stream:
                stream.write(data)
            return {'written': str(path), 'bytes': len(data.encode())}
        if name not in ('shell', 'run_program'):
            raise ValueError('Invalid tool arguments')
        env = {'HOME': str(Path.home()), 'USER': os.environ.get('USER', 'arduino'),
               'PATH': str(Path(self.config['python']).parent) + ':/usr/local/bin:/usr/bin:/bin',
               'LANG': 'C.UTF-8', 'TORQUE_SOCKET': self.config['socket']}
        if name == 'run_program':
            path = self.file_path(args['path'], write=True)
            if path.suffix != '.py' or not path.is_file():
                raise ValueError('Choose an existing Python file under projects/')
            command, cwd = [self.config['python'], str(path), *args['arguments']], path.parent
        else:
            command, cwd = ['/bin/bash', '--noprofile', '--norc', '-c', args['command']], self.workspace
        process = await asyncio.create_subprocess_exec(*command, cwd=cwd, env=env, stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.STDOUT, start_new_session=True)
        chunks = bytearray()
        try:
            async with asyncio.timeout(120):
                while block := await process.stdout.read(4096):
                    if len(chunks) + len(block) > 65536:
                        raise ValueError('Tool output exceeded 64 KiB; process stopped')
                    chunks.extend(block)
                await process.wait()
        finally:
            if process.returncode is None:
                try:
                    os.killpg(process.pid, signal.SIGTERM)
                except ProcessLookupError:
                    pass
                try:
                    await asyncio.wait_for(process.wait(), 2)
                except asyncio.TimeoutError:
                    os.killpg(process.pid, signal.SIGKILL)
                    await process.wait()
        return self.redact({'exit_code': process.returncode, 'output': chunks.decode(errors='replace')})

    async def tool(self, event):
        request_id = event['request_id']
        args, name = event['arguments'], event['tool']
        accepted = False
        answer = {'outcome': 'denied'}
        try:
            if self.maintenance or self.cancelling:
                raise RuntimeError('A control operation is in progress; tool was not executed')
            policy.validate(name, args)
            if name in ('read_file', 'list_directory', 'search_files', 'write_file', 'run_program'):
                self.file_path(args['path'], write=name in ('write_file', 'run_program'))
            accepted = not policy.needs_approval(name, self.turn_permissions)
            if not accepted:
                future = self.loop.create_future()
                public = {'request_id': request_id, 'session_id': event['session_id'],
                          'tool': name, 'arguments': args}
                self.pending[request_id] = {'future': future, 'public': public}
                self.device.set_state('waiting')
                self.publish({'type': 'approval.required', **public})
                accepted = await asyncio.wait_for(future, 600)
            if accepted:
                value = await self.execute(name, args)
                answer = {'outcome': 'accepted', 'value': value}
        except asyncio.CancelledError:
            answer = {'outcome': 'cancelled'}
        except Exception as error:
            answer = {'outcome': 'accepted' if accepted else 'denied',
                      'error': str(error) if isinstance(error, (ValueError, RuntimeError)) else type(error).__name__}
        finally:
            self.pending.pop(request_id, None)
            self.device.set_state('waiting' if self.pending else 'working' if self.turn_active else 'standby')
        if self.worker and self.worker.returncode is None:
            await self.engine_send({'op': 'tool.result', 'request_id': request_id, 'result': answer})

    async def update_control(self, request):
        update_id = request.get('update_id')
        pending = self.updates.pending()
        if not pending or pending['id'] != update_id:
            raise RuntimeError('Update fence has no matching transaction')
        async with self.start_lock:
            if request.get('action') == 'release':
                if self.update_id != update_id:
                    raise RuntimeError('Another operation owns the update fence')
                self.updates.clear(update_id)
                self.update_id = None
                self.device.set_maintenance(False)
                self.maintenance = None
                return self.snapshot()
            if request.get('action') != 'fence':
                raise ValueError('Unknown update control operation')
            if request.get('expected_release') != str(self.root):
                raise RuntimeError('Daemon release changed before update fencing')
            if self.update_id == update_id:
                return self.snapshot()
            if (self.maintenance or self.turn_active or self.cancelling or self.pending or
                    (self.probe_task and not self.probe_task.done()) or
                    any(not task.done() for task in self.tool_tasks)):
                raise RuntimeError('Torque work is active; update refused without cancellation')
            self.maintenance = 'runtime-update'
            try:
                await asyncio.to_thread(self.device.fence_update)
            except BaseException:
                self.maintenance = None
                raise
            self.update_id = update_id
            return self.snapshot()

    async def request(self, client, request):
        if request.get('v') != VERSION:
            raise ValueError('Unsupported Torque protocol')
        op = request.get('op')
        if op == 'update':
            return await self.update_control(request)
        if op in ('status', 'doctor'):
            return self.snapshot()
        if op == 'events':
            after = request.get('after', 0)
            if type(after) is not int or after < 0:
                raise ValueError('Invalid event cursor')
            selected = []
            size = 0
            for event in self.events:
                if event['cursor'] <= after:
                    continue
                size += len(encode(event))
                if selected and size > 100000:
                    break
                selected.append(event)
            return {'epoch': self.epoch, 'cursor': selected[-1]['cursor'] if selected else self.cursor,
                    'gap': bool(self.events and after < self.events[0]['cursor'] - 1) or after > self.cursor,
                    'events': selected,
                    'device': self.device.status(), 'session': self.snapshot()}
        if op == 'device':
            return await asyncio.to_thread(self.device.request, client, request['operation'], request.get('arguments', {}))
        if op == 'model':
            action = request.get('action')
            if action == 'list':
                refresh = request.get('refresh', False)
                if type(refresh) is not bool:
                    raise ValueError('Refresh must be boolean')
                return await asyncio.to_thread(self.models.listing, refresh=refresh)
            name = request.get('model_id')
            from .models import model_id
            model_id(name)
            if action == 'use':
                return await self.select_model(name)
            if action == 'test':
                return await self.test_model(name)
            raise ValueError('Unknown model operation')
        if op == 'reset':
            return await self.reset_outputs(request.get('blank', False))
        if op == 'prompt':
            if self.turn_active or self.maintenance or self.cancelling:
                raise RuntimeError('A turn is running; attach or cancel it first')
            prompt = request.get('prompt')
            if not isinstance(prompt, str) or not 0 < len(prompt.encode()) <= 32768:
                raise ValueError('Prompt must contain 1..32768 UTF-8 bytes')
            async with self.start_lock:
                if self.turn_active or self.maintenance or self.cancelling:
                    raise RuntimeError('Work is active; wait or cancel first')
                self.maintenance = 'turn-start'
                try:
                    self.turn_permissions = policy.mode(self.default_permissions if request.get('permissions') is None else request['permissions'])
                    await self.start_engine()
                    self.turn_active = True
                    self.outcome = 'running'
                    self.device.set_state('working')
                    self.persist()
                    await self.engine_send({'op': 'prompt', 'prompt': prompt,
                        'session_id': self.session_id if request.get('resume') else None,
                        'message_id': 'wrun_' + uuid.uuid4().hex})
                    return {'accepted': True, 'cursor': self.cursor}
                finally:
                    self.maintenance = None
        if op == 'approve':
            pending = self.pending.get(request.get('request_id'))
            if not pending or pending['public']['session_id'] != request.get('session_id'):
                raise ValueError('Approval does not match a pending request and session')
            if type(request.get('allow')) is not bool or pending['future'].done():
                raise ValueError('Invalid or already answered approval')
            pending['future'].set_result(request['allow'])
            return True
        if op == 'cancel':
            return await self.cancel_active()
        raise ValueError('Unknown Torque operation')

    async def client(self, reader, writer):
        client = uuid.uuid4().hex
        self.clients.add(writer)
        try:
            peer = writer.get_extra_info('socket')
            if hasattr(socket, 'SO_PEERCRED'):
                _, uid, _ = struct.unpack('3i', peer.getsockopt(socket.SOL_SOCKET, socket.SO_PEERCRED, 12))
                if uid != os.getuid():
                    raise RuntimeError('Client account does not match service account')
            while raw := await reader.readline():
                request = {}
                try:
                    if len(raw) > LIMIT:
                        raise ValueError('Oversized request')
                    request = json.loads(raw)
                    result = await self.request(client, request)
                    reply = {'id': request.get('id'), 'result': result}
                except Exception as error:
                    reply = {'id': request.get('id') if isinstance(request, dict) else None,
                             'error': str(error) if isinstance(error, (RuntimeError, ValueError)) else type(error).__name__}
                writer.write(encode(reply))
                await writer.drain()
        except (ConnectionError, OSError, ValueError):
            pass
        finally:
            self.device.release(client)
            self.clients.discard(writer)
            writer.close()
            try:
                await writer.wait_closed()
            except (ConnectionError, OSError):
                pass  # A Ctrl-C reconnect can close the old stream mid-reply.

    async def close(self):
        if self.probe_task and not self.probe_task.done():
            self.probe_task.cancel()
            await asyncio.gather(self.probe_task, return_exceptions=True)
        for task in list(self.tool_tasks):
            task.cancel()
        if self.tool_tasks:
            await asyncio.gather(*self.tool_tasks, return_exceptions=True)
        if self.worker and self.worker.returncode is None:
            self.worker.stdin.close()
            try:
                await asyncio.wait_for(self.worker.wait(), 8)
            except asyncio.TimeoutError:
                self.worker.kill()
                await self.worker.wait()
        for writer in list(self.clients):
            writer.close()
        await asyncio.to_thread(self.device.close)


async def serve(config, *, config_path=None):
    os.umask(0o077)
    path = Path(config['socket'])
    private_dir(path.parent)
    if path.exists():
        # Refuse an active socket; never unlink an arbitrary filesystem entry.
        if not stat.S_ISSOCK(path.lstat().st_mode):
            raise RuntimeError('Runtime socket path is occupied by a non-socket')
        test = socket.socket(socket.AF_UNIX)
        try:
            test.connect(str(path))
        except ConnectionRefusedError:
            path.unlink()
        else:
            raise RuntimeError('Torque is already running')
        finally:
            test.close()
    daemon = Daemon(config, config_path=config_path)
    daemon.device.start()
    stopped = asyncio.Event()
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(sig, stopped.set)
    try:
        async with await asyncio.start_unix_server(daemon.client, str(path), limit=LIMIT) as server:
            os.chmod(path, 0o600)
            await stopped.wait()
    finally:
        await daemon.close()
        path.unlink(missing_ok=True)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--config', type=Path, default=Path.home() / '.config/torque/settings.json')
    parser.add_argument('--check-config', action='store_true', help='Validate paths without starting workers or hardware')
    args = parser.parse_args(argv)
    try:
        config = json.loads(args.config.read_text())
        if args.check_config:
            root = Path(config['release_root']).resolve()
            for key in ('python', 'node', 'libfx_path'):
                if not Path(config[key]).exists():
                    raise RuntimeError('Configured runtime path is unavailable: ' + key)
            if not (root/'assets/status.json').is_file() or not Path(config['workspace']).is_dir():
                raise RuntimeError('Configured resources or workspace are missing')
            policy.mode(config.get('permission_mode', 'auto'))
            print(json.dumps({'valid': True, 'release_root': str(root)}))
        else:
            asyncio.run(serve(config, config_path=args.config))
    except (OSError, ValueError, RuntimeError) as error:
        print('torqued: ' + str(error), file=sys.stderr)
        return 1
    return 0


if __name__ == '__main__':
    sys.exit(main())
