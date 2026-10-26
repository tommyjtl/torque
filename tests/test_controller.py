import json
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'packages/device/src'))
from unoq_control import Board, ControllerError, FirmwareError, Frame, ResetError


class FakeBridge:
    def __init__(self):
        self.calls = []
        self.boot = 7
        self.protocol = [1, 0]
        self.connected = True
        self.disconnected = False
        self.fail_write = False
        self.timeout_draw = False
        self.status = {'boot_id': 7, 'playing': False, 'frame': 0, 'frames': 0,
                       'upload_id': 0, 'committed_id': 0}

    def connect(self, timeout):
        return self.connected

    def disconnect(self):
        self.disconnected = True

    def call(self, method, *args, timeout):
        self.calls.append((method, args))
        method = method.removeprefix('unoq.control.v1.')
        if method == 'system.info':
            return json.dumps({'name': 'base-controller', 'version': '0.1.0',
                               'protocol': self.protocol, 'boot_id': self.boot, 'ready': True})
        if method == 'system.capability':
            return json.dumps({'rows': 8, 'columns': 13, 'encoding': 'bitset-hex-msb',
                               'max_frames': 32, 'min_duration_ms': 20, 'max_duration_ms': 60000}
                              if args[0] == 'matrix' else {'ids': [3, 4], 'binary': True})
        if method == 'matrix.status':
            return json.dumps(self.status)
        if args[0] != self.boot:
            return -3
        if method == 'matrix.begin':
            return 9
        if method == 'matrix.write_frame' and self.fail_write:
            return -1
        if method == 'matrix.draw' and self.timeout_draw:
            raise TimeoutError
        return 0


class ControllerTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.bridge = FakeBridge()
        self.board = Board(transport=self.bridge, lock_dir=Path(self.temp.name) / 'locks')
        self.board.connect()
        self.addCleanup(self.board.close)

    def test_frame_mapping_and_validation(self):
        pixels = [0] * 104
        for index in (0, 13, 103):
            pixels[index] = 1
        self.assertEqual(Frame(pixels).to_hex(), '80040000000000000000000001')
        self.assertEqual(Frame.from_rows(['#............', '#............'] + ['.............'] * 5 + ['............#']), Frame(pixels))
        for bad in ([0] * 103, [0] * 105, [0] * 103 + [2], [0] * 103 + [True], [0] * 103 + [0.0]):
            with self.subTest(bad=bad[-1:]), self.assertRaises(ValueError):
                Frame(bad)
        with self.assertRaises(ValueError):
            Frame.from_rows(['..'] * 8)

    def test_connect_and_info_do_not_take_writer_lock_or_actuate(self):
        self.assertEqual(self.board.info()['boot_id'], 7)
        self.assertFalse((Path(self.temp.name) / 'locks').exists())
        self.assertTrue(all('system.info' in method for method, _ in self.bridge.calls))

    def test_invalid_animation_is_rejected_before_upload(self):
        self.bridge.calls.clear()
        for frames, duration in (([], 20), ([Frame([0] * 104)] * 33, 20), ([Frame([0] * 104)], 19), ([Frame([0] * 104)], True)):
            with self.subTest(duration=duration), self.assertRaises((ValueError, TypeError)):
                self.board.matrix.load(frames, duration)
        self.assertEqual(self.bridge.calls, [])

    def test_animation_is_committed_after_every_frame_and_does_not_autoplay(self):
        self.board.matrix.load([Frame([0] * 104), Frame([1] * 104)], [20, 100])
        calls = [(m.rsplit('.', 1)[-1], a) for m, a in self.bridge.calls if '.matrix.' in m]
        self.assertEqual([m for m, _ in calls], ['begin', 'write_frame', 'write_frame', 'commit'])
        self.assertEqual(calls[1][1], (7, 9, 0, '0' * 26, 20))
        self.assertEqual(calls[2][1], (7, 9, 1, 'f' * 26, 100))

    def test_failed_upload_aborts_staging_without_committing_or_clearing(self):
        self.bridge.fail_write = True
        with self.assertRaises(ControllerError) as caught:
            self.board.matrix.load([Frame([0] * 104)], 20)
        self.assertEqual(caught.exception.upload_id, 9)
        methods = [m.rsplit('.', 1)[-1] for m, _ in self.bridge.calls if '.matrix.' in m]
        self.assertEqual(methods, ['begin', 'write_frame', 'abort'])

    def test_timeout_does_not_retry_a_control_command(self):
        self.bridge.timeout_draw = True
        with self.assertRaisesRegex(ControllerError, 'effect is unknown'):
            self.board.matrix.draw(Frame([0] * 104))
        self.assertEqual(sum(m.endswith('matrix.draw') for m, _ in self.bridge.calls), 1)

    def test_rgb_rejects_numeric_channels(self):
        self.bridge.calls.clear()
        with self.assertRaises(ValueError):
            self.board.rgb(3).set(1, 0, 0)
        self.assertEqual(self.bridge.calls, [])
        self.board.rgb(4).set(True, False, True)
        self.assertEqual(self.bridge.calls[-1][1], (7, 4, True, False, True))

    def test_reset_cannot_replay_old_mutation(self):
        self.bridge.boot = 8
        with self.assertRaises(ResetError):
            self.board.matrix.clear()
        self.assertEqual(sum(m.endswith('matrix.clear') for m, _ in self.bridge.calls), 1)

    def test_read_only_status_rejects_malformed_fields_and_detects_reset(self):
        self.assertFalse(self.board.matrix.status()['playing'])
        self.bridge.status['playing'] = 'false'
        with self.assertRaises(FirmwareError):
            self.board.matrix.status()
        self.bridge.boot = 8
        self.bridge.status['boot_id'] = 8
        with self.assertRaises(ResetError):
            self.board.matrix.status()
        self.assertIsNone(self.board._lock_file)

    def test_second_client_can_read_but_cannot_interleave_writes(self):
        other = Board(transport=FakeBridge(), lock_dir=Path(self.temp.name) / 'locks')
        with other:
            self.board.matrix.clear()
            self.assertEqual(other.info()['boot_id'], 7)
            with self.assertRaisesRegex(ControllerError, 'Another cooperating program'):
                other.matrix.clear()
            self.board.close()
            other.matrix.clear()

    def test_incompatible_firmware_disconnects_without_mutation(self):
        bridge = FakeBridge()
        bridge.protocol = [2, 0]
        board = Board(transport=bridge)
        with self.assertRaises(FirmwareError):
            board.connect()
        self.assertTrue(bridge.disconnected)
        self.assertEqual(len(bridge.calls), 1)

    def test_connection_timeout_stops_background_reconnect(self):
        bridge = FakeBridge()
        bridge.connected = False
        with self.assertRaises(ControllerError):
            Board(transport=bridge).connect()
        self.assertTrue(bridge.disconnected)
        self.assertEqual(bridge.calls, [])

    def test_firmware_state_machine_runs_as_native_cpp(self):
        compiler = shutil.which('c++')
        if not compiler:
            self.skipTest('C++ compiler needed for firmware state-machine test')
        source = ROOT / 'firmware/uno-q/controller/sketch/src'
        executable = Path(self.temp.name) / 'state-test'
        result = subprocess.run([compiler, '-std=c++17', '-Wall', '-Wextra', '-Werror',
                                 '-I', str(source), str(ROOT / 'tests/controller_state_test.cpp'),
                                 str(source / 'controller.cpp'), '-o', str(executable)],
                                capture_output=True, text=True, timeout=60)
        self.assertEqual(result.returncode, 0, result.stderr)
        result = subprocess.run([str(executable)], capture_output=True, text=True, timeout=10)
        self.assertEqual(result.returncode, 0, result.stderr)


if __name__ == '__main__':
    unittest.main()
