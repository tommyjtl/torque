"""Grayscale codecs, real firmware state transitions, ownership and offline authoring."""
import base64
import copy
import importlib.util
import json
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch
import xml.etree.ElementTree as ET

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / 'packages/device/src'), str(ROOT / 'packages/session/src')]
from unoq_control import Board, ControllerError, FirmwareError, Frame
from unoq_control.telemetry import decode_snapshot, decode_event, decode_health
from torque.device import Device
from test_controller import FakeBridge

spec = importlib.util.spec_from_file_location('dot_matrix', ROOT / 'examples/06-dot-matrix-animations/main.py')
helix = importlib.util.module_from_spec(spec)
spec.loader.exec_module(helix)

RAMP = '053977' * 13


class GrayBridge(FakeBridge):
    def __init__(self):
        super().__init__()
        self.grayscale = True
        self.fail_gray = False

    def call(self, method, *args, timeout):
        if method.endswith('system.capability') and args == ('matrix-grayscale',):
            self.calls.append((method, args))
            return json.dumps(dict(rows=8, columns=13, max_frames=32, bits=3, max_value=7,
                                   min_duration_ms=20, max_duration_ms=60000,
                                   encoding='gray3-hex-msb') if self.grayscale else None)
        if method.endswith(('matrix.draw_gray', 'matrix.begin_gray', 'matrix.write_gray')):
            self.calls.append((method, args))
            if args[0] != self.boot:
                return -3
            if method.endswith('matrix.begin_gray'):
                return 10
            if method.endswith('matrix.write_gray') and self.fail_gray:
                return -1
            return 0
        return super().call(method, *args, timeout=timeout)


class GrayscaleTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.bridge = GrayBridge()
        self.board = Board(transport=self.bridge, lock_dir=Path(self.temp.name) / 'locks')
        self.board.connect()
        self.addCleanup(self.board.close)
        self.ramp = Frame(tuple(i % 8 for i in range(104)), bits=3)

    def test_explicit_format_packed_bits_and_rows(self):
        self.assertEqual(self.ramp.to_hex(), RAMP)
        self.assertEqual(Frame.from_hex(RAMP, bits=3), self.ramp)
        rows = [''.join(str(p) for p in self.ramp.pixels[i * 13:(i + 1) * 13]) for i in range(8)]
        self.assertEqual(Frame.from_rows(rows, bits=3), self.ramp)
        self.assertEqual(Frame.from_rows(['.' * 13] * 8, bits=3), Frame((0,) * 104, bits=3))
        self.assertEqual(Frame((1,) * 104).to_hex(), 'f' * 26)
        self.assertNotEqual(Frame((1,) * 104, bits=3).to_hex(), 'f' * 78)
        for value in range(8):
            frame = Frame((value,) * 104, bits=3)
            self.assertEqual(Frame.from_hex(frame.to_hex(), bits=3), frame)

    def test_invalid_pixels_formats_rows_and_packed_data_fail_before_io(self):
        for bad in (True, 2, 0, 4, 3.0, '3'):
            with self.subTest(bits=bad), self.assertRaises(ValueError):
                Frame((0,) * 104, bits=bad)
        for bad in ([0] * 103, [0] * 105, [0] * 103 + [8], [0] * 103 + [-1],
                    [0] * 103 + [True], [0] * 103 + [1.0]):
            with self.assertRaises(ValueError):
                Frame(bad, bits=3)
        for bad in ('', 'f' * 26, 'g' * 78, '0' * 77, '0' * 79):
            with self.assertRaises(ValueError):
                Frame.from_hex(bad, bits=3)
        for bad in (['8' * 13] * 8, ['#' * 13] * 8, ['0' * 12] * 8):
            with self.assertRaises(ValueError):
                Frame.from_rows(bad, bits=3)
        self.bridge.calls.clear()
        with self.assertRaises(ValueError):
            self.board.matrix.load([Frame((0,) * 104), self.ramp])
        self.assertEqual(self.bridge.calls, [])

    def test_optional_capability_rejects_old_controller_without_ownership_or_mutation(self):
        self.bridge.grayscale = False
        self.bridge.calls.clear()
        with self.assertRaisesRegex(FirmwareError, 'grayscale requires'):
            self.board.matrix.load([self.ramp])
        self.assertIsNone(self.board._lock_file)
        self.assertEqual(len(self.bridge.calls), 1)
        self.assertTrue(self.bridge.calls[0][0].endswith('system.capability'))
        self.board.matrix.draw(Frame((1,) * 104))
        self.assertTrue(self.bridge.calls[-1][0].endswith('matrix.draw'))

    def test_gray_upload_is_atomic_separate_from_play_and_aborts_failed_staging(self):
        self.board.matrix.draw(self.ramp)
        self.board.matrix.load([self.ramp] * 32, 20)
        methods = [m.removeprefix('unoq.control.v1.') for m, _ in self.bridge.calls]
        self.assertEqual(methods.count('matrix.write_gray'), 32)
        self.assertNotIn('matrix.play', methods)
        writes = [a for m, a in self.bridge.calls if m.endswith('matrix.write_gray')]
        self.assertEqual(writes[-1], (7, 10, 31, RAMP, 20))
        self.bridge.fail_gray = True
        self.bridge.calls.clear()
        with self.assertRaises(ControllerError) as caught:
            self.board.matrix.load([self.ramp])
        self.assertEqual(caught.exception.upload_id, 10)
        self.assertEqual([m.rsplit('.', 1)[-1] for m, _ in self.bridge.calls],
                         ['begin_gray', 'write_gray', 'abort'])

    def test_reset_rejects_gray_mutation_without_replaying_it(self):
        self.bridge.boot = 8
        with self.assertRaises(ControllerError):
            self.board.matrix.draw(self.ramp)
        self.assertEqual(sum(m.endswith('matrix.draw_gray') for m, _ in self.bridge.calls), 1)

    def test_exact_schema2_readback_rejects_bad_payloads(self):
        data = dict(v=2, b=7, s=1, r=1, t=0, c=1, rgb=[[0, 7], [0, 7]],
                    m=[base64.b64encode(bytes.fromhex(RAMP)).decode(), False, 0, 1, 1, 0])
        state = decode_snapshot(data)
        self.assertEqual(state['matrix']['bits'], 3)
        self.assertEqual(state['matrix']['frame_hex'], RAMP)
        self.assertEqual(state['matrix']['rows'][0], '.1234567.1234')
        with patch.object(self.board, 'snapshot', return_value=state):
            self.assertEqual(self.board.matrix.frame(), self.ramp)
        for bad in ([], ['A' * 52], ['!' * 52, False, 0, 1, 1, 0],
                    ['A' * 51, False, 0, 1, 1, 0], [data['m'][0], 0, 0, 1, 1, 0],
                    [data['m'][0], False, 1, 1, 1, 0], [data['m'][0], False, 0, 33, 1, 0]):
            invalid = copy.deepcopy(data); invalid['m'] = bad
            with self.assertRaises(FirmwareError):
                decode_snapshot(invalid)

    def test_daemon_gates_each_gray_mutation_with_existing_ownership(self):
        writes = []
        device = Device(ROOT / 'assets/status.json', lambda value: None)
        device.board = SimpleNamespace(_writer=lambda: writes.append('lock'),
                                       _call=lambda *args: writes.append(args) or 0)
        device.error = None
        for method in ('matrix.draw_gray', 'matrix.begin_gray', 'matrix.write_gray'):
            with self.assertRaisesRegex(RuntimeError, 'ownership'):
                device.request('program', 'rpc', dict(method=method, args=[]))
        self.assertEqual(writes, [])
        device.request('program', 'acquire', {})
        for method in ('matrix.draw_gray', 'matrix.begin_gray', 'matrix.write_gray'):
            device.request('program', 'rpc', dict(method=method, args=[7]))
        self.assertEqual(writes, ['lock', ('matrix.draw_gray', 7), 'lock',
                                  ('matrix.begin_gray', 7), 'lock', ('matrix.write_gray', 7)])

    def test_cpp_controller_and_telemetry_match_python_at_maximum_width(self):
        compiler = shutil.which('c++')
        if not compiler:
            self.skipTest('C++ compiler required')
        source = ROOT / 'firmware/uno-q/controller/sketch/src'
        target = str(Path(self.temp.name) / 'gray-state')
        result = subprocess.run([compiler, '-std=c++17', '-Wall', '-Wextra', '-Werror',
                                 '-I', str(source), str(ROOT / 'tests/grayscale_state_test.cpp'),
                                 str(source / 'controller.cpp'), str(source / 'telemetry_state.cpp'),
                                 '-o', target], capture_output=True, text=True, timeout=60)
        self.assertEqual(result.returncode, 0, result.stderr)
        result = subprocess.run([target], capture_output=True, text=True, timeout=10)
        self.assertEqual(result.returncode, 0, result.stderr)
        lines = result.stdout.splitlines()
        self.assertEqual(len(lines), 4)
        self.assertLessEqual(len(lines[0]) + 10, 256)
        snapshot = decode_snapshot(json.loads(lines[0]))
        event = decode_event(lines[1])
        self.assertEqual(snapshot['matrix'], event['state'])
        self.assertEqual(snapshot['matrix']['frame_hex'], RAMP)
        for line in lines[1:]:
            self.assertLessEqual(len(line) + 41, 256)
        self.assertEqual(decode_event(lines[2])['state']['frame_hex'], 'f' * 78)
        self.assertEqual(decode_event(lines[3])['operation'], 'matrix.write_gray')
        health = dict(v=1, b=7, up=0, r=0, s=0, c=0, e=-1, op=12, active=False,
                      q=0, d=0, sent=0)
        self.assertEqual(decode_health(health)['last_operation'], 'matrix.write_gray')


class HalfHelixTests(unittest.TestCase):
    def test_quantized_clip_is_bounded_and_contains_different_brightness_levels(self):
        frames = helix.render_frames(4)
        self.assertEqual(len(frames), 24)
        self.assertGreater(len(set(frames)), 16)
        self.assertEqual(set(p for f in frames for p in f.pixels), set(range(5)))
        for frame in frames:
            self.assertEqual(frame.bits, 3)
            self.assertTrue(all(not p or (4 <= i % 13 < 9 and 1 <= i // 13 < 6)
                                for i, p in enumerate(frame.pixels)))
        # The wrap step is another ordinary sampled phase, not a pause or jump.
        changes = [sum(abs(a-b) for a,b in zip(frames[i].pixels, frames[(i+1)%24].pixels))
                   for i in range(24)]
        self.assertLessEqual(changes[-1], max(changes[:-1]))

    def test_default_preview_never_constructs_a_board_and_has_discrete_frames(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / 'preview.svg'
            with patch.object(helix, 'Board', side_effect=AssertionError('Hardware contacted')):
                self.assertEqual(helix.main(['--animation', 'half-helix', '--preview', str(path)]), 0)
            root = ET.fromstring(path.read_text())
            animations = root.findall('.//{http://www.w3.org/2000/svg}animate')
            self.assertEqual(len(animations), 104)
            for animation in animations:
                self.assertEqual(animation.attrib['calcMode'], 'discrete')
                self.assertEqual(animation.attrib['dur'], '0.600s')
                self.assertEqual(len(animation.attrib['values'].split(';')), 25)

    def test_playback_is_finite_clears_on_interrupt_and_does_not_clear_unsupported_firmware(self):
        calls = []
        matrix = SimpleNamespace(load=lambda *a, **k: calls.append('load'),
                                 play=lambda **k: calls.append(('play', k['repeat'])),
                                 status=lambda: (_ for _ in ()).throw(KeyboardInterrupt()),
                                 clear=lambda: calls.append('clear'))
        board = SimpleNamespace(matrix=matrix)
        with patch.object(helix, 'Board') as factory, patch.object(helix.signal, 'signal'):
            factory.return_value.__enter__.return_value = board
            with self.assertRaises(KeyboardInterrupt):
                helix.play(helix.render_frames(), 80, 3)
            self.assertEqual(calls, ['load', ('play', 3), 'clear'])
            calls.clear()
            matrix.load = lambda *a, **k: (_ for _ in ()).throw(FirmwareError('Unsupported'))
            with self.assertRaises(FirmwareError):
                helix.play(helix.render_frames(), 80, 3)
            self.assertEqual(calls, [])


if __name__ == '__main__':
    unittest.main()
