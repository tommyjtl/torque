"""Model selection, reset ownership and Ctrl-C behavior without cloud/hardware."""
import asyncio
from contextlib import redirect_stdout, redirect_stderr
import copy
import io
import json
import os
import pty
import subprocess
import struct
import threading
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import AsyncMock, Mock, patch

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / 'packages/session/src'), str(ROOT / 'packages/device/src')]
from torque import cli, control_cli
from torque.daemon import Daemon
from torque.device import Device
from torque.models import ModelCatalog, EXPERIMENTAL_BUDGET, NoRedirect, discover, private_json, save_json
from torque.protocol import encode, LIMIT
from unoq_control import Frame


class CatalogTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.key = self.root / 'key'
        self.key.write_text('PRIVATE-MODEL-FIXTURE')
        self.key.chmod(0o600)
        self.config = {'release_root': str(ROOT), 'key_file': str(self.key),
                       'model': 'MiniMaxAI/MiniMax-M3.1-Flash', 'models': {}}
        self.fetch = Mock(return_value=[self.config['model'], 'new/experimental'])
        self.now = 1000
        self.catalog = ModelCatalog(self.config, cache=self.root / 'cache/models.json',
                                    fetch=self.fetch, clock=lambda: self.now)

    def test_discovery_cache_and_unknown_model_profile(self):
        first = self.catalog.listing()
        unknown = next(row for row in first['models'] if row['id'] == 'new/experimental')
        self.assertEqual(unknown['source'], 'experimental')
        self.assertEqual(unknown['tool_support'], 'unverified')
        self.assertFalse(unknown['metadata']['supportsVision'])
        self.assertEqual(unknown['metadata']['contextWindow'], EXPERIMENTAL_BUDGET)
        self.assertEqual(self.catalog.listing()['source'], 'cache')
        self.fetch.assert_called_once()
        self.assertNotIn(self.key.read_text(), self.catalog.path.read_text())
        self.assertEqual(self.catalog.path.stat().st_mode & 0o777, 0o600)

    def test_default_cache_uses_private_child_of_existing_shared_cache(self):
        shared = self.root / '.cache/torque'
        shared.mkdir(parents=True)
        shared.chmod(0o775)
        with patch('torque.models.Path.home', return_value=self.root):
            catalog = ModelCatalog(self.config, fetch=self.fetch, clock=lambda: self.now)
            result = catalog.listing(refresh=True)
        self.assertTrue(result['ok'])
        self.assertEqual(result['source'], 'online')
        self.assertEqual(shared.stat().st_mode & 0o777, 0o775)
        self.assertEqual(catalog.path.parent.stat().st_mode & 0o777, 0o700)
        self.assertEqual(catalog.path.stat().st_mode & 0o777, 0o600)
        self.assertNotIn(self.key.read_text(), catalog.path.read_text())

    def test_stale_cache_refresh_failure_and_missing_selected_model(self):
        self.catalog.listing()
        self.now += 4000
        self.fetch.side_effect = RuntimeError('PRIVATE-MODEL-FIXTURE')
        stale = self.catalog.listing(refresh=True)
        self.assertFalse(stale['ok'])
        self.assertEqual(stale['source'], 'stale')
        self.assertEqual(stale['error'], '[REDACTED]')
        self.assertTrue(self.catalog.selectable('new/experimental')[0]['eligible'])
        self.fetch.side_effect = None
        self.fetch.return_value = ['new/experimental']
        rows = self.catalog.listing(refresh=True)['models']
        current = next(row for row in rows if row['selected'])
        self.assertFalse(current['discovered'])
        self.assertEqual(self.config['model'], current['id'])

    def test_credential_rotation_invalidates_cache_and_probes(self):
        self.catalog.listing()
        self.catalog.record('new/experimental', {'passed': True, 'text': True, 'tool': True})
        self.assertIsNotNone(next(r for r in self.catalog.listing()['models'] if r['id'] == 'new/experimental')['verification'])
        replacement = self.root / 'replacement'
        replacement.write_text('NEW-PRIVATE-FIXTURE')
        replacement.chmod(0o600)
        replacement.replace(self.key)
        self.fetch.side_effect = RuntimeError('offline')
        result = self.catalog.listing()
        self.assertEqual(result['source'], 'configured')
        self.assertFalse(any(row['verification'] for row in result['models']))

    def test_no_cache_offline_never_makes_configured_models_discovered(self):
        self.fetch.side_effect = RuntimeError('offline')
        result = self.catalog.listing()
        self.assertTrue(all(row['discovered'] is None for row in result['models']))
        with self.assertRaises(ValueError):
            self.catalog.selectable(self.config['model'])

    def test_overrides_and_ineligible_models(self):
        self.config['models'] = {self.config['model']: {'contextWindow': 4096, 'supportsToolUse': False}}
        self.assertEqual(self.catalog.profile(self.config['model'])['metadata']['contextWindow'], 4096)
        with self.assertRaisesRegex(ValueError, 'incompatible'):
            self.catalog.selectable(self.config['model'])

    def test_cache_rejects_symlinks_and_changed_profile_invalidates_probe(self):
        self.catalog.listing()
        self.catalog.record('new/experimental', {'passed': True})
        self.config['models']['new/experimental'] = {'supportsVision': True}
        row = next(r for r in self.catalog.listing()['models'] if r['id'] == 'new/experimental')
        self.assertIsNone(row['verification'])
        outside = self.root / 'outside.json'
        outside.write_text('{}')
        link = self.root / 'link.json'
        link.symlink_to(outside)
        with self.assertRaises(ValueError):
            private_json(link)
        with self.assertRaises(ValueError):
            save_json(link, {'changed': True})
        self.assertEqual(outside.read_text(), '{}')

    def test_discovery_is_bounded_and_does_not_echo_server_errors(self):
        response = Mock()
        response.__enter__ = Mock(return_value=response)
        response.__exit__ = Mock()
        opener = Mock()
        opener.open.return_value = response
        for raw in [b'{}', b'{"data":[{}]}', b'{"data":[{"id":"bad\\nname"}]}', b'x' * (2 * 1024 * 1024 + 1)]:
            response.read.return_value = raw
            with patch('torque.models.urllib.request.build_opener', return_value=opener):
                with self.assertRaises(RuntimeError):
                    discover('PRIVATE-MODEL-FIXTURE')
        with self.assertRaisesRegex(RuntimeError, 'not forwarded'):
            NoRedirect().redirect_request(None, None, None, None, None, None)

    def test_large_catalog_fits_ipc_and_can_select_an_omitted_exact_id(self):
        ids = [f'new/{index:04d}-' + 'x' * 40 for index in range(1000)]
        self.fetch.return_value = ids
        result = self.catalog.listing()
        self.assertTrue(result['truncated'])
        self.assertLess(len(encode({'id': 1, 'result': result})), LIMIT)
        self.assertEqual(self.catalog.selectable(ids[-1])[0]['id'], ids[-1])


class ResetBoard:
    def __init__(self):
        self.boot = 7
        self.frame = Frame((1,) * 104)
        self.playing = True
        self.colors = {str(led): {'red': True, 'green': False, 'blue': False} for led in (3, 4)}
        self.writes = []
        self.matrix = Mock(draw=self.draw)
        self.fail_led = None
        self.invalid_readback = None
    def draw(self, frame):
        self.frame, self.playing = frame, False
        self.writes.append('matrix')
    def rgb(self, led):
        def set_color(*values):
            if self.fail_led == led:
                raise RuntimeError('Connection lost; effect unknown')
            self.colors[str(led)] = dict(zip(('red', 'green', 'blue'), values))
            self.writes.append(led)
        return Mock(set=set_color)
    def snapshot(self):
        return {'boot_id': self.boot, 'matrix': {'frame_hex': self.frame.to_hex(), 'bits': 1, 'playing': self.playing},
                'rgb': {led: {'readback_valid': self.invalid_readback != led, 'readback': copy.deepcopy(color)}
                        for led, color in self.colors.items()}}
    def _mutate(self, suffix, *args):
        self.writes.append((suffix, args))


class DeviceResetTests(unittest.TestCase):
    def setUp(self):
        self.device = Device(ROOT / 'assets/status.json', lambda _: None)
        self.device.board = self.board = ResetBoard()
        self.device.error = None
        self.device.set_maintenance(True)

    def test_default_and_blank_reset_verify_and_preserve_boot(self):
        result = self.device.reset()
        self.assertTrue(result['passed'])
        self.assertEqual(result['boot_id'], 7)
        self.assertEqual(self.board.frame, Frame.from_rows(self.device.frames['standby']))
        self.assertIsNone(self.device.intent)
        result = self.device.reset(blank=True)
        self.assertTrue(result['passed'])
        self.assertEqual(self.board.frame.to_hex(), '00' * 13)
        self.assertTrue(self.device.intent['retained'])
        self.device.set_maintenance(False)
        self.device.set_state('working')
        self.device.render()
        self.assertEqual(self.board.frame.to_hex(), '00' * 13)

    def test_external_owner_is_preserved_and_writers_are_gated(self):
        self.device.owner = 'external'
        result = self.device.reset()
        self.assertTrue(result['busy'])
        self.assertFalse(self.board.writes)
        self.assertEqual(self.device.owner, 'external')
        with self.assertRaisesRegex(RuntimeError, 'reset'):
            self.device.request('new', 'acquire', {})
        with self.assertRaisesRegex(RuntimeError, 'reset'):
            self.device.action('matrix_clear', {})

    def test_rpc_failure_stops_later_writes_and_blocks_renderer_recovery(self):
        self.board.fail_led = 3
        result = self.device.reset()
        self.assertFalse(result['passed'])
        self.assertEqual(self.board.writes, ['matrix'])
        self.assertEqual(result['components']['rgb_3']['status'], 'failed')
        self.device.set_maintenance(False)
        self.device.render()
        self.assertEqual(self.board.writes, ['matrix'])

    def test_invalid_readback_and_owned_staging_upload(self):
        self.device.staging_upload = {'client': 'old-managed-client', 'id': 12}
        self.board.invalid_readback = '4'
        result = self.device.reset()
        self.assertFalse(result['passed'])
        self.assertEqual(self.board.writes[0], ('matrix.abort', (12,)))
        self.assertEqual(result['components']['rgb_4']['status'], 'failed')


class DummyDevice:
    def __init__(self, *args):
        self.maintenance = False
        self.state = 'standby'
    def status(self):
        return {'ready': True, 'error': None, 'owner': None}
    def set_state(self, state):
        self.state = state
    def set_maintenance(self, enabled):
        self.maintenance = enabled
    def reset(self, *, blank):
        return {'passed': True, 'target': 'blank' if blank else 'standby', 'components': {}}
    def release(self, client):pass
    def close(self):pass


class ControlTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        key = self.root / 'key'
        key.write_text('PRIVATE-CONTROL-FIXTURE')
        key.chmod(0o600)
        workspace = self.root / 'workspace'
        (workspace / 'projects').mkdir(parents=True)
        self.config = {'release_root': str(ROOT), 'workspace': str(workspace), 'state_dir': str(self.root / 'state'),
                       'key_file': str(key), 'python': sys.executable, 'socket': str(self.root / 'socket'),
                       'model': 'MiniMaxAI/MiniMax-M3.1-Flash', 'models': {}, 'permission_mode': 'auto',
                       'unrelated': {'keep': True}}
        self.path = self.root / 'configuration/settings.json'
        save_json(self.path, self.config)
        self.daemon = Daemon(self.config, device_factory=DummyDevice, config_path=self.path)
        self.daemon.models = ModelCatalog(self.config, cache=self.root / 'cache/models.json',
                                         fetch=lambda _: ['new/model', self.config['model']])

    async def test_select_preserves_settings_history_and_does_not_restart_device(self):
        self.daemon.session_id = 'existing-history'
        result = await self.daemon.select_model('new/model')
        self.assertTrue(result['changed'])
        self.assertEqual(self.daemon.snapshot()['model'], 'new/model')
        saved = private_json(self.path)
        self.assertEqual(saved['unrelated'], {'keep': True})
        self.assertEqual(saved['permission_mode'], 'auto')
        self.assertEqual(self.daemon.session_id, 'existing-history')
        self.assertEqual(saved['model_profiles']['new/model']['source'], 'experimental')
        self.assertEqual(self.daemon.device.state, 'standby')

    async def test_busy_selection_and_failed_persistence_leave_model_unchanged(self):
        before = self.config['model']
        self.daemon.turn_active = True
        with self.assertRaises(RuntimeError):
            await self.daemon.select_model('new/model')
        self.daemon.turn_active = False
        with patch('torque.daemon.save_json', side_effect=OSError):
            with self.assertRaises(OSError):
                await self.daemon.select_model('new/model')
        self.assertEqual(self.config['model'], before)
        self.assertEqual(private_json(self.path)['model'], before)
        self.assertIsNone(self.daemon.maintenance)

    async def test_disconnected_frontend_cleanup_tolerates_a_broken_pipe(self):
        reader = Mock(readline=AsyncMock(return_value=b''))
        peer = Mock(getsockopt=Mock(return_value=struct.pack('3i', 123, os.getuid(), os.getgid())))
        writer = Mock(get_extra_info=Mock(return_value=peer), wait_closed=AsyncMock(side_effect=BrokenPipeError))
        await self.daemon.client(reader, writer)
        self.assertNotIn(writer, self.daemon.clients)
        writer.close.assert_called_once()

    async def test_model_test_is_temporary_and_cancellable(self):
        saved = self.path.read_bytes()
        started = asyncio.Event()
        async def probe(*args):
            started.set()
            await asyncio.Event().wait()
        self.daemon.run_model_test = probe
        task = asyncio.create_task(self.daemon.test_model('new/model'))
        await started.wait()
        await self.daemon.cancel_active()
        result = await task
        self.assertTrue(result['cancelled'])
        self.assertEqual(self.path.read_bytes(), saved)
        self.assertIsNone(self.daemon.maintenance)

    async def test_cancel_terminates_managed_program_without_resetting_outputs(self):
        started, late = self.root / 'started', self.root / 'late'
        script = Path(self.config['workspace']) / 'projects/wait.py'
        script.write_text(f'import pathlib,time\npathlib.Path({str(started)!r}).touch()\ntime.sleep(60)\npathlib.Path({str(late)!r}).touch()\n')
        task = asyncio.create_task(self.daemon.execute('run_program', {'path': str(script), 'arguments': []}))
        self.daemon.tool_tasks.add(task)
        self.daemon.turn_active = True
        for _ in range(300):
            if started.exists():
                break
            await asyncio.sleep(.01)
        self.assertTrue(started.exists())
        result = await self.daemon.cancel_active()
        self.assertTrue(result['cancelled'])
        self.assertTrue(task.done())
        self.assertFalse(late.exists())
        self.assertEqual(self.daemon.outcome, 'cancelled')
        self.assertFalse(self.daemon.device.maintenance)

    async def test_cancel_during_discovery_never_starts_billable_probe(self):
        entered, release = threading.Event(), threading.Event()
        def selection(_):
            entered.set()
            release.wait(3)
            return {'metadata': {}}, {}
        self.daemon.models.selectable = selection
        self.daemon.run_model_test = AsyncMock()
        task = asyncio.create_task(self.daemon.test_model('new/model'))
        try:
            self.assertTrue(await asyncio.to_thread(entered.wait, 2))
            await self.daemon.cancel_active()
            self.assertTrue((await task)['cancelled'])
            self.daemon.run_model_test.assert_not_awaited()
            self.assertIsNone(self.daemon.maintenance)
        finally:
            release.set()

    async def test_reset_gates_new_work_until_cancellation_settles(self):
        entered, release = asyncio.Event(), asyncio.Event()
        async def cancel():
            entered.set()
            await release.wait()
            return {'cancelled': True}
        self.daemon.cancel_active = cancel
        reset = asyncio.create_task(self.daemon.reset_outputs(True))
        await entered.wait()
        with self.assertRaises(RuntimeError):
            await self.daemon.request('client', {'v': 1, 'op': 'prompt', 'prompt': 'hello'})
        with self.assertRaises(RuntimeError):
            await self.daemon.execute('matrix_clear', {})
        release.set()
        self.assertTrue((await reset)['passed'])
        self.assertIsNone(self.daemon.maintenance)
        self.assertFalse(self.daemon.device.maintenance)

    @unittest.skipUnless(hasattr(os, 'login_tty'), 'requires a POSIX terminal')
    async def test_real_terminal_ctrl_c_cancels_managed_process_and_keeps_chat_open(self):
        self.daemon.device = Device(ROOT / 'assets/status.json', lambda _: None)
        self.daemon.device.board = board = ResetBoard()
        self.daemon.device.error = None
        self.daemon.device.close = lambda: None  # This fixture has no watcher thread.
        started = self.root / 'started'
        script = Path(self.config['workspace']) / 'projects/terminal-wait.py'
        script.write_text(f'import pathlib,time\npathlib.Path({str(started)!r}).touch()\ntime.sleep(60)\n')
        task = asyncio.create_task(self.daemon.execute('run_program', {'path': str(script), 'arguments': []}))
        self.daemon.tool_tasks.add(task)
        self.daemon.turn_active = True
        self.daemon.session_id = 'terminal-fixture-history'
        server = await asyncio.start_unix_server(self.daemon.client, self.config['socket'])
        env = {'HOME': str(Path.home()), 'PATH': os.environ.get('PATH', '/usr/bin:/bin'),
               'PYTHONPATH': str(ROOT / 'packages/session/src') + os.pathsep + str(ROOT / 'packages/device/src'),
               'TORQUE_SOCKET': self.config['socket'], 'PYTHONUNBUFFERED': '1', 'LANG': 'C.UTF-8'}
        executable = os.environ.get('TORQUE_TEST_INSTALLED_PYTHON', sys.executable)
        if 'TORQUE_TEST_INSTALLED_PYTHON' in os.environ:
            env.pop('PYTHONPATH')  # Exercise the wheel, never the source overlay.
        master, slave = pty.openpty()
        launcher = 'import os,sys;os.login_tty(int(sys.argv[1]));os.execv(sys.executable,[sys.executable,"-m","torque.cli"])'
        process = subprocess.Popen([executable, '-c', launcher, str(slave)], env=env, pass_fds=(slave,))
        os.close(slave)
        os.set_blocking(master, False)
        transcript = bytearray()
        async def until(fragment):
            deadline = asyncio.get_running_loop().time() + 8
            while asyncio.get_running_loop().time() < deadline:
                try:
                    transcript.extend(os.read(master, 4096))
                except BlockingIOError:
                    pass
                if fragment in transcript:
                    return
                await asyncio.sleep(.02)
            self.fail('Terminal did not reach expected state: ' + repr(bytes(transcript[-1000:])))
        try:
            await until(b'/help for commands')
            self.assertTrue(started.exists())
            transcript.clear()
            os.write(master, b'\x03')
            await until('› '.encode())
            self.assertIn(b'managed outputs reset to standby', transcript)
            self.assertNotIn(b'Traceback', transcript)
            self.assertTrue(task.done())
            self.assertFalse(self.daemon.turn_active)
            self.assertEqual(self.daemon.outcome, 'cancelled')
            self.assertEqual(board.frame, Frame.from_rows(self.daemon.device.frames['standby']))
            self.assertTrue(all(not channel for color in board.colors.values() for channel in color.values()))
            os.write(master, b'/exit\n')
            for _ in range(100):
                if process.poll() is not None:
                    self.assertEqual(process.returncode, 0)
                    break
                await asyncio.sleep(.02)
            self.assertIsNotNone(process.returncode, 'Frontend did not exit after returning to chat')
        finally:
            if process.poll() is None:
                process.kill()
                process.wait()
            os.close(master)
            server.close()
            await server.wait_closed()
            await self.daemon.close()


class FrontendTests(unittest.TestCase):
    class Connection:
        def __init__(self):
            self.active = True
            self.ops = []
            self.reconnected = 0
        def __enter__(self):return self
        def __exit__(self, *_):pass
        def reconnect(self):self.reconnected += 1
        def request(self, op, **args):
            self.ops.append((op, args))
            if op == 'status':
                return {'model': 'fixture', 'workspace': '/workspace', 'device': {'ready': True},
                        'active': self.active, 'epoch': 'one', 'session_id': 'history'}
            if op == 'events':raise KeyboardInterrupt
            if op == 'cancel':self.active = False; return {'cancelled': True}
            if op == 'reset':self.active = False; return {'passed': True, 'target': 'standby', 'components': {}}
            if op == 'model':return {'ok': True}
            raise AssertionError(op)

    def test_ctrl_c_resets_and_returns_to_chat(self):
        connection = self.Connection()
        with patch.object(cli, 'Connection', return_value=connection), \
             patch('builtins.input', return_value='/exit') as prompt, redirect_stdout(io.StringIO()):
            self.assertEqual(cli.main([]), 0)
        self.assertEqual(sum(op == 'reset' for op, _ in connection.ops), 1)
        self.assertFalse(any(op == 'cancel' for op, _ in connection.ops))
        self.assertEqual(connection.reconnected, 1)
        prompt.assert_called_once()

    def test_idle_ctrl_c_clears_input_and_model_slash_is_local(self):
        connection = self.Connection()
        connection.active = False
        with patch.object(cli, 'Connection', return_value=connection), \
             patch('builtins.input', side_effect=[KeyboardInterrupt, '/model list --json', '/exit']), \
             redirect_stdout(io.StringIO()):
            self.assertEqual(cli.main([]), 0)
        self.assertTrue(any(op == 'model' for op, _ in connection.ops))
        self.assertFalse(any(op in ('prompt', 'cancel') for op, _ in connection.ops))

    def test_picker_without_terminal_and_invalid_slash_do_not_select(self):
        connection = self.Connection()
        args = Mock(command='model', model_action=None)
        with patch.object(control_cli.sys.stdin, 'isatty', return_value=False):
            with self.assertRaises(ValueError):
                control_cli.run(connection, args)
        with redirect_stderr(io.StringIO()):
            self.assertEqual(control_cli.slash(connection, '/model use'), 2)
        self.assertFalse(connection.ops)


if __name__ == '__main__':
    unittest.main()
