"""Resident cache selection, storage isolation, SDK validation and packet budgets."""
import json
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
from types import SimpleNamespace
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / 'packages/device/src'), str(ROOT / 'packages/session/src')]
from unoq_control import Board, Frame, FirmwareError, ControllerError
from unoq_control.telemetry import decode_snapshot, decode_event
from torque.device import Device
from test_controller import FakeBridge


class PresetBridge(FakeBridge):
    def __init__(self):
        super().__init__()
        self.presets = True
    def call(self, method, *args, timeout):
        if method.endswith('system.capability') and args == ('matrix-presets',):
            self.calls.append((method, args))
            return json.dumps(dict(max_presets=9, max_frames=32) if self.presets else None)
        return super().call(method, *args, timeout=timeout)


class PresetTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(); self.addCleanup(self.temp.cleanup)
        self.bridge = PresetBridge()
        self.board = Board(transport=self.bridge, lock_dir=Path(self.temp.name)/'lock')
        self.board.connect(); self.addCleanup(self.board.close)

    def test_selection_is_one_mutation_without_any_frame_upload(self):
        self.board.matrix.cache(9)
        self.bridge.calls.clear()
        self.board.matrix.play_cached(9, repeat=0)
        self.assertEqual(self.bridge.calls, [('unoq.control.v1.matrix.play_cached', (7, 9, 0))])

    def test_invalid_and_unsupported_requests_do_not_take_ownership_or_mutate(self):
        self.bridge.calls.clear()
        for slot in (0, 10, -1, True, 1.0):
            with self.assertRaises(ValueError): self.board.matrix.cache(slot)
        for repeat in (-1, 65536, True):
            with self.assertRaises(ValueError): self.board.matrix.play_cached(1, repeat)
        self.assertEqual(self.bridge.calls, [])
        self.assertIsNone(self.board._lock_file)
        self.bridge.presets = False
        with self.assertRaisesRegex(FirmwareError, '0.4.0'):
            self.board.matrix.play_cached(1)
        self.assertEqual(len(self.bridge.calls), 1)
        self.assertIsNone(self.board._lock_file)

    def test_cache_mutations_preserve_daemon_ownership_checks(self):
        calls = []
        device = Device(ROOT/'assets/status.json', lambda event: None)
        device.board = SimpleNamespace(_writer=lambda: calls.append('writer'),
                                       _call=lambda *args: calls.append(args) or 0)
        device.error = None
        for method in ('matrix.cache', 'matrix.play_cached'):
            with self.assertRaisesRegex(RuntimeError, 'ownership'):
                device.request('client', 'rpc', dict(method=method, args=[7, 1]))
        self.assertEqual(calls, [])
        device.request('client', 'acquire', {})
        for method in ('matrix.cache', 'matrix.play_cached'):
            device.request('client', 'rpc', dict(method=method, args=[7, 1]))
        self.assertEqual(calls, ['writer', ('matrix.cache',7,1), 'writer', ('matrix.play_cached',7,1)])

    def test_real_cpp_cache_state_and_maximum_grayscale_packet(self):
        compiler = shutil.which('c++')
        if not compiler:self.skipTest('C++ compiler required')
        source = ROOT/'firmware/uno-q/controller/sketch/src'
        executable = str(Path(self.temp.name)/'presets')
        result = subprocess.run([compiler,'-std=c++17','-Wall','-Wextra','-Werror','-I',str(source),
            str(ROOT/'tests/preset_state_test.cpp'),str(source/'controller.cpp'),str(source/'telemetry_state.cpp'),
            '-o',executable],capture_output=True,text=True,timeout=60)
        self.assertEqual(result.returncode,0,result.stderr)
        result = subprocess.run([executable],capture_output=True,text=True,timeout=10)
        self.assertEqual(result.returncode,0,result.stderr)
        lines=result.stdout.splitlines();self.assertEqual(len(lines),3)
        state=decode_snapshot(json.loads(lines[0]))
        event=decode_event(lines[1])
        self.assertEqual(state['matrix'],event['state'])
        self.assertEqual(event['state']['preset'],9)
        self.assertEqual(event['state']['frame_hex'],'f'*78)
        self.assertLessEqual(len(lines[0])+10,256)
        self.assertLessEqual(len(lines[1])+41,256)
        self.assertEqual(decode_event(lines[2])['operation'],'matrix.play_cached')


if __name__=='__main__':unittest.main()
