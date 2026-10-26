"""Authorization, isolation, event recovery and deployment integrity contracts."""
import asyncio
import contextlib
import getpass
import hashlib
import importlib.util
import io
import json
import os
from pathlib import Path
import sys
import subprocess
import tempfile
import unittest
from unittest.mock import AsyncMock, patch

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / 'packages/device/src'), str(ROOT / 'packages/session/src')]
from torque.daemon import Daemon, private_dir
from torque.device import Device
from torque.protocol import encode, LIMIT


def script(name):
    spec = importlib.util.spec_from_file_location(name, ROOT / 'install' / (name + '.py'))
    value = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(value)
    return value


stage, system = script('stage'), script('system')


class NoDevice:
    def __init__(self, *args):
        self.states = []
    def status(self):
        return {'ready': False, 'error': 'unavailable', 'snapshot': None}
    def set_state(self, value):
        self.states.append(value)


class RuntimeTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.workspace = self.root / 'workspace'
        stage.seed_workspace(self.workspace)
        key = self.root / 'credential'
        key.write_text('PRIVATE-FIXTURE-TORQUE')
        key.chmod(0o600)
        self.config = {'release_root': str(ROOT), 'workspace': str(self.workspace),
                       'state_dir': str(self.root / 'state'), 'key_file': str(key),
                       'python': sys.executable, 'socket': str(self.root / 'socket'), 'model': 'fixture', 'permission_mode': 'ask'}
        self.daemon = Daemon(self.config, device_factory=NoDevice)
        self.daemon.engine_send = AsyncMock()
        self.daemon.worker = type('Worker', (), {'returncode': None})()

    async def test_denial_is_effective_and_approval_is_bound_to_session(self):
        event = {'request_id': 'call-a', 'session_id': 'session-a', 'tool': 'shell',
                 'arguments': {'command': 'touch should-not-exist'}}
        self.daemon.execute = AsyncMock()
        task = asyncio.create_task(self.daemon.tool(event))
        await asyncio.sleep(0)
        with self.assertRaisesRegex(ValueError, 'does not match'):
            await self.daemon.request('client', {'v': 1, 'op': 'approve', 'request_id': 'call-a',
                                               'session_id': 'wrong-session', 'allow': True})
        await self.daemon.request('client', {'v': 1, 'op': 'approve', 'request_id': 'call-a',
                                           'session_id': 'session-a', 'allow': False})
        await task
        self.daemon.execute.assert_not_awaited()
        self.assertEqual(self.daemon.engine_send.call_args.args[0]['result']['outcome'], 'denied')
        with self.assertRaises(ValueError):
            await self.daemon.request('client', {'v': 1, 'op': 'approve', 'request_id': 'call-a',
                                               'session_id': 'session-a', 'allow': True})

    async def test_approval_executes_once_and_disconnect_does_not_answer_it(self):
        self.daemon.execute = AsyncMock(return_value='done')
        event = {'request_id': 'call-b', 'session_id': 'session-b', 'tool': 'write_file',
                 'arguments': {'path': 'projects/demo.py', 'content': 'print(1)'}}
        task = asyncio.create_task(self.daemon.tool(event))
        await asyncio.sleep(0)
        self.assertFalse(task.done())
        self.assertEqual(self.daemon.snapshot()['pending'][0]['request_id'], 'call-b')
        await self.daemon.request('new-client', {'v': 1, 'op': 'approve', 'request_id': 'call-b',
                                               'session_id': 'session-b', 'allow': True})
        await task
        self.daemon.execute.assert_awaited_once()

    async def test_file_tools_reject_symlink_escape_and_extra_arguments(self):
        (self.workspace / 'projects/escape').symlink_to(self.root, target_is_directory=True)
        with self.assertRaises(ValueError):
            await self.daemon.execute('write_file', {'path': 'projects/escape/outside', 'content': 'bad'})
        with self.assertRaises(ValueError):
            await self.daemon.execute('write_file', {'path': 'AGENTS.md', 'content': 'bad'})
        with self.assertRaises(ValueError):
            await self.daemon.execute('shell', {'command': 'uname -m', 'extra': True})
        await self.daemon.execute('write_file', {'path': 'projects/new/demo.py', 'content': 'print(1)'})
        self.assertEqual((self.workspace / 'projects/new/demo.py').read_text(), 'print(1)')

    async def test_approved_shell_has_real_home_and_no_inference_credential(self):
        os.environ['MODULAR_API_KEY'] = 'PRIVATE-FIXTURE-TORQUE'
        self.addCleanup(os.environ.pop, 'MODULAR_API_KEY', None)
        value = await self.daemon.execute('shell', {'command': 'printf "%s\\n%s" "$HOME" "${MODULAR_API_KEY-unset}"'})
        self.assertEqual(value['exit_code'], 0)
        self.assertEqual(value['output'], str(Path.home()) + '\nunset')
        self.assertFalse((self.root / 'state/session.json').exists())

    async def test_output_redaction_precedes_engine_storage(self):
        path = self.workspace / 'fixture.txt'
        path.write_text('PRIVATE-FIXTURE-TORQUE')
        self.assertEqual(await self.daemon.execute('read_file', {'path': str(path)}), '[REDACTED]')
        self.daemon.publish({'type': 'test', 'text': 'PRIVATE-FIXTURE-TORQUE'})
        self.assertNotIn('PRIVATE-FIXTURE-TORQUE', json.dumps(self.daemon.snapshot()))
        self.assertEqual(self.daemon.events[-1]['text'], '[REDACTED]')

    async def test_bounded_events_expose_gaps_and_do_not_skip_unread_batches(self):
        for i in range(600):
            self.daemon.publish({'type': 'test', 'data': 'x' * 1000})
        first = await self.daemon.request('client', {'v': 1, 'op': 'events', 'after': 0})
        self.assertTrue(first['gap'])
        self.assertLess(len(encode(first)), LIMIT)
        second = await self.daemon.request('client', {'v': 1, 'op': 'events', 'after': first['cursor']})
        self.assertEqual(second['events'][0]['cursor'], first['cursor'] + 1)

    async def test_interrupted_registry_never_claims_work_is_still_running(self):
        self.daemon.session_id = 'fixture-session'
        self.daemon.turn_active = True
        self.daemon.persist()
        new = Daemon(self.config, device_factory=NoDevice)
        self.assertFalse(new.turn_active)
        self.assertEqual(new.outcome, 'interrupted')
        self.assertEqual(new.session_id, 'fixture-session')

    async def test_missing_key_keeps_diagnostics_available_without_model_work(self):
        Path(self.config['key_file']).unlink()
        new = Daemon(self.config, device_factory=NoDevice)
        state = new.snapshot()
        self.assertFalse(state['credential_ready'])
        self.assertIsNone(new.worker)
        with self.assertRaisesRegex(RuntimeError, 'Credential file unavailable'):
            await new.start_engine()

    async def test_oversized_shell_output_is_stopped_before_storage(self):
        with self.assertRaisesRegex(ValueError, 'exceeded'):
            await self.daemon.execute('shell', {'command': 'printf "%070000d" 1'})


class InstallTests(unittest.TestCase):
    def test_readiness_retries_missing_socket_not_ready_and_invalid_json(self):
        responses = [subprocess.CompletedProcess([], 1, stdout=''),
                     subprocess.CompletedProcess([], 1, stdout='starting'),
                     subprocess.CompletedProcess([], 1, stdout=json.dumps({'device': {'ready': False, 'error': 'waiting for MCU'}})),
                     subprocess.CompletedProcess([], 0, stdout=json.dumps({'device': {'ready': True}, 'credential_ready': True}))]
        with patch.object(system, 'run', side_effect=responses) as run, patch.object(system.time, 'sleep'):
            status = system.wait_for_ready('/torque', 'fixture')
        self.assertTrue(status['device']['ready'])
        self.assertEqual(run.call_count, 4)
        self.assertTrue(all(call.kwargs['check'] is False for call in run.call_args_list))

    def test_readiness_timeout_preserves_final_device_diagnostic(self):
        clock = [0.0]
        def sleep(seconds):clock[0] += seconds
        response = subprocess.CompletedProcess([], 1, stdout=json.dumps({'device': {'ready': False, 'error': 'router unavailable'}}))
        with patch.object(system, 'run', return_value=response), patch.object(system.time, 'monotonic', side_effect=lambda: clock[0]), \
             patch.object(system.time, 'sleep', side_effect=sleep):
            with self.assertRaisesRegex(RuntimeError, 'router unavailable'):
                system.wait_for_ready('/torque', 'fixture', timeout=1, interval=.2)

    def test_readiness_retries_transient_command_timeout(self):
        ready = {'device': {'ready': True}, 'credential_ready': True}
        with patch.object(system, 'run', side_effect=[subprocess.TimeoutExpired('torque', 1),
                 subprocess.CompletedProcess([], 0, stdout=json.dumps(ready))]), patch.object(system.time, 'sleep'):
            self.assertEqual(system.wait_for_ready('/torque', 'fixture'), ready)

    def test_admin_tool_resolution_does_not_depend_on_inherited_path(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            binary, admin = root / 'bin', root / 'sbin'
            binary.mkdir()
            admin.mkdir()
            runuser = admin / 'runuser'
            runuser.write_text('#!' + sys.executable + '\nimport os,sys\n'
                               'assert sys.argv[1] == "-u" and sys.argv[3] == "--"\n'
                               'os.execvpe(sys.argv[4],sys.argv[4:],os.environ)\n')
            runuser.chmod(0o755)
            probe = binary / 'probe'
            probe.write_text('#!' + sys.executable + '\nimport json,os,sys\n'
                             'print(json.dumps({"home":os.environ["HOME"],"user":os.environ["USER"],'
                             '"path":os.environ["PATH"],"args":sys.argv[1:]}))\n')
            probe.chmod(0o755)
            search = str(binary) + os.pathsep + str(admin)
            with patch.object(system, 'SYSTEM_PATH', search), patch.dict(os.environ, {'PATH': '/usr/bin:/bin'}), \
                 patch.object(system.os, 'geteuid', return_value=0):
                result = system.run(['probe', 'an argument with spaces'], user=getpass.getuser())
            value = json.loads(result.stdout)
            self.assertEqual(value['home'], str(Path.home()))
            self.assertEqual(value['user'], getpass.getuser())
            self.assertEqual(value['path'], search)
            self.assertEqual(value['args'], ['an argument with spaces'])

    def test_existing_user_context_does_not_require_runuser(self):
        # A normal-user deployment check runs in its own account, without sudo.
        with patch.object(system, 'system_tool', side_effect=lambda name: '/does-not-exist' if name == 'runuser' else name):
            value = system.run([sys.executable, '-c', 'print("normal-user-ok")'], user=getpass.getuser())
        self.assertEqual(value.stdout.strip(), 'normal-user-ok')

    def test_controller_deployment_accepts_null_empty_app_list(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            target, state = root / 'release', root / 'state'
            source = target / 'firmware/uno-q/controller'
            source.mkdir(parents=True)
            state.mkdir()
            (source / 'app.yaml').write_text('name: fixture')
            def app(command, user, timeout=120):
                return json.dumps({'apps': None}) if command[:2] == ['app', 'ps'] else '{}'
            replies = [type('Result', (), {'returncode': 1, 'stdout': ''})(),
                       type('Result', (), {'returncode': 0, 'stdout': json.dumps({
                           'version': system.FIRMWARE_VERSION, 'protocol': list(system.FIRMWARE_PROTOCOL), 'ready': True, 'boot_id': 123})})()]
            with patch.object(system, 'app', side_effect=app) as calls, \
                 patch.object(system, 'run', side_effect=replies), patch.object(system.os, 'chown'):
                record = system.controller(target, state, getpass.getuser(), Path('/python'))
            self.assertEqual(record['identity']['boot_id'], 123)
            self.assertEqual(len([call for call in calls.call_args_list if call.args[0][:2] == ['app', 'start']]), 1)

    def test_prepared_controller_requires_source_default_and_live_identity(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            target, state = root / 'release', root / 'state'
            source = target / 'firmware/uno-q/controller'
            stable = state / 'device/uno-q/controller'
            source.mkdir(parents=True)
            stable.mkdir(parents=True)
            (source / 'app.yaml').write_text('name: fixture')
            (stable / 'app.yaml').write_text('name: fixture')
            identifier = system.base64.urlsafe_b64encode(str(stable).encode()).decode().rstrip('=')
            identity = {'version': system.FIRMWARE_VERSION, 'protocol': list(system.FIRMWARE_PROTOCOL), 'ready': True, 'boot_id': 123}
            probe = type('Result', (), {'returncode': 0, 'stdout': json.dumps(identity)})()
            status = json.dumps({'apps': [{'id': identifier, 'default': False, 'status': 'running'}]})
            default = {'app': {'FullPath': str(stable)}}
            def app_result(command, user):
                return json.dumps(default) if command[:2] == ['properties', 'get'] else status
            with patch.object(system, 'app', side_effect=app_result), \
                 patch.object(system, 'run', return_value=probe):
                self.assertEqual(system.prepared_controller(target, state, 'fixture', Path('/python'))['identity'], identity)
                (stable / 'app.yaml').write_text('name: changed')
                self.assertIsNone(system.prepared_controller(target, state, 'fixture', Path('/python')))
                (stable / 'app.yaml').write_text('name: fixture')
                default['app']['FullPath'] = str(root / 'other-app')
                self.assertIsNone(system.prepared_controller(target, state, 'fixture', Path('/python')))
                default['app']['FullPath'] = str(stable)
                identity['version'] = '0.0.0'
                probe.stdout = json.dumps(identity)
                self.assertIsNone(system.prepared_controller(target, state, 'fixture', Path('/python')))

    def test_missing_admin_binary_fails_before_installation_changes(self):
        with tempfile.TemporaryDirectory() as temp:
            with patch.object(system, 'SYSTEM_PATH', temp), patch.object(system.os, 'geteuid', return_value=0), \
                 patch.object(system.os, 'umask'), patch.object(system, 'copy_release') as copy, \
                 patch.object(system, 'run') as run, contextlib.redirect_stderr(io.StringIO()) as error:
                result = system.main(['--stage', temp, '--user', getpass.getuser(), '--install-controller'])
            self.assertEqual(result, 1)
            self.assertIn('Required system tool is unavailable: runuser', error.getvalue())
            copy.assert_not_called()
            run.assert_not_called()

    def test_release_identity_changes_with_docs_and_config_but_not_user_data(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            (root / 'README.md').write_text('first')
            first = stage.source_fingerprint(root)
            (root / 'projects').mkdir()
            (root / 'projects/demo.py').write_text('my program')
            self.assertEqual(first, stage.source_fingerprint(root))
            (root / 'README.md').write_text('second')
            self.assertNotEqual(first, stage.source_fingerprint(root))
            second = stage.source_fingerprint(root)
            (root / 'config').mkdir()
            (root / 'config/models.json').write_text('{}')
            self.assertNotEqual(second, stage.source_fingerprint(root))

    def test_manifest_and_relocation_work_under_a_cache_parent(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            source = root / '.cache/stage'
            (source / 'runtime/bin').mkdir(parents=True)
            (source / 'runtime/bin/python').write_bytes(b'interpreter fixture')
            (source / 'runtime/bin/alias').symlink_to('python')
            (source / '.cache').mkdir()
            (source / '.cache/ignored').write_text('build cache')
            manifest = {'release': '0.1.0-a123', **stage.bundle_identity(), **stage.file_manifest(source)}
            self.assertIn('runtime/bin/python', manifest['files'])
            self.assertNotIn('.cache/ignored', manifest['files'])
            (source / 'release.json').write_text(json.dumps(manifest))
            system.verify_stage(source)
            target = root / 'relocated'
            system.copy_release(source, target, manifest)
            self.assertEqual((target / 'runtime/bin/python').read_bytes(), b'interpreter fixture')
            self.assertEqual((target / 'runtime/bin/alias').read_bytes(), b'interpreter fixture')

    def test_empty_release_manifest_is_rejected(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            (root / 'release.json').write_text(json.dumps({'release': '0.1.0-a123', 'files': {}}))
            with self.assertRaisesRegex(RuntimeError, 'no files'):
                system.verify_stage(root)

    def test_seed_workspace_preserves_custom_skills_and_programs(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp) / 'workspace'
            stage.seed_workspace(root)
            for path, text in [('AGENTS.md', 'my instructions'), ('projects/demo.py', 'print(1)'), ('skills/custom.md', 'my skill')]:
                (root / path).write_text(text)
            stage.seed_workspace(root)
            self.assertEqual((root / 'AGENTS.md').read_text(), 'my instructions')
            self.assertEqual((root / 'projects/demo.py').read_text(), 'print(1)')
            self.assertEqual((root / 'skills/custom.md').read_text(), 'my skill')

    def test_release_tampering_fails_before_installation(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            source = root / 'file'
            source.write_bytes(b'original')
            manifest = {'release': '0.1.0-a123', **stage.bundle_identity(),
                        'files': {'file': hashlib.sha256(b'original').hexdigest()}}
            (root / 'release.json').write_text(json.dumps(manifest))
            self.assertEqual(system.verify_stage(root), manifest)
            source.write_bytes(b'tampered')
            with self.assertRaisesRegex(RuntimeError, 'hash mismatch'):
                system.verify_stage(root)

    def test_private_state_rejects_shared_permissions_and_symlinks(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            (root / 'unsafe').mkdir(mode=0o755)
            with self.assertRaises(RuntimeError):
                private_dir(root / 'unsafe')
            (root / 'link').symlink_to(root / 'unsafe')
            with self.assertRaises(RuntimeError):
                private_dir(root / 'link')

    def test_device_ownership_is_exclusive_and_status_yields_until_release(self):
        device = Device(ROOT / 'assets/status.json', lambda event: None)
        class Board:
            def __init__(self):
                self.frames=[]
                self.clips={}
                self.matrix=type('Matrix', (), {
                    'draw':lambda _,frame:self.frames.append(frame),
                    'load':lambda _,frames,durations:setattr(self,'loaded',frames),
                    'cache':lambda _,slot:self.clips.update({slot:self.loaded}),
                    'play_cached':lambda _,slot,repeat:self.frames.append(self.clips[slot][0])})()
            def _writer(self):
                pass
            def _call(self, *args):
                return 0
        device.board = Board()
        device.error = None
        device.render()
        self.assertEqual(len(device.board.frames), 1)
        device.request('a', 'acquire', {})
        device.set_state('working')
        device.render()
        self.assertEqual(len(device.board.frames), 1)
        with self.assertRaisesRegex(RuntimeError, 'Another program'):
            device.request('b', 'acquire', {})
        with self.assertRaisesRegex(RuntimeError, 'ownership'):
            device.request('b', 'rpc', {'method': 'matrix.clear', 'args': [1]})
        device.release('a')
        device.render()
        self.assertEqual(len(device.board.frames), 2)
