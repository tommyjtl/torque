import copy
import json
from pathlib import Path
import queue
import shutil
import subprocess
import sys
import tempfile
import time
import unittest
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'packages/device/src'))
from unoq_control import Board, ControllerError, FirmwareError, Frame
from unoq_control.telemetry import decode_snapshot, decode_event, decode_health, rgb_state, newer
from telemetry_fakes import Device


class TelemetryCodecTests(unittest.TestCase):
    def test_requested_rgb_and_independent_active_low_readback(self):
        for requested in range(8):
            for pins in range(8):
                result = rgb_state(3, requested, pins)
                self.assertTrue(result['readback_valid'])
                for i, name in enumerate(('red', 'green', 'blue')):
                    self.assertEqual(result['requested'][name], bool(requested & (1 << i)))
                    self.assertEqual(result['readback'][name], not bool(pins & (1 << i)))
        missing = rgb_state(3, 7, -1)
        self.assertFalse(missing['readback_valid'])
        self.assertIsNone(missing['readback'])
        self.assertIsNone(missing['raw_gpio'])

    def test_snapshot_reports_known_frame_and_rejects_malformed_data(self):
        data = Device().data
        data['f'] = '80040000000000000000000001'
        snapshot = decode_snapshot(data)
        self.assertEqual(snapshot['matrix']['rows'][0], '#............')
        self.assertEqual(snapshot['matrix']['rows'][1], '#............')
        self.assertEqual(snapshot['matrix']['rows'][7], '............#')
        self.assertEqual(snapshot['matrix']['source'], 'firmware_framebuffer')
        self.assertEqual(Frame.from_hex(data['f']).to_hex(), data['f'])
        for key, value in (('v', True), ('r', -1), ('f', 'x' * 26), ('p', 0), ('i', 1), ('rgb', [[0, 8], [0, 7]])):
            bad = copy.deepcopy(data);bad[key] = value
            with self.subTest(key=key), self.assertRaises(FirmwareError):
                decode_snapshot(bad)

    def test_sequence_wrap_and_replay_order(self):
        self.assertTrue(newer(0, 0xffffffff))
        self.assertFalse(newer(0xffffffff, 0))
        self.assertFalse(newer(7, 7))

    def test_health_validates_sources_and_counters(self):
        data = dict(v=1, b=7, up=1 << 40, r=2, s=3, c=4, e=-1, op=2, active=True, q=8, d=9, sent=10)
        health = decode_health(data)
        self.assertEqual(health['last_operation'], 'matrix.draw')
        self.assertEqual(health['uptime_ms'], 1 << 40)
        data['q'] = 9
        with self.assertRaises(FirmwareError):decode_health(data)

    def test_real_cpp_codec_maximum_payloads_and_round_trip(self):
        compiler = shutil.which('c++')
        if not compiler:self.skipTest('C++ compiler needed for real firmware codec test')
        source = ROOT / 'firmware/uno-q/controller/sketch/src'
        with tempfile.TemporaryDirectory() as temp:
            executable = str(Path(temp) / 'codec')
            result = subprocess.run([compiler, '-std=c++17', '-Wall', '-Wextra', '-Werror',
                                     '-I', str(source), str(ROOT / 'tests/telemetry_codec_test.cpp'),
                                     str(source / 'telemetry_state.cpp'), '-o', executable],
                                    capture_output=True, text=True, timeout=60)
            self.assertEqual(result.returncode, 0, result.stderr)
            result = subprocess.run([executable], capture_output=True, text=True, timeout=10)
            self.assertEqual(result.returncode, 0, result.stderr)
            lines = result.stdout.splitlines()
        self.assertEqual(len(lines), 5)
        snapshot = decode_snapshot(json.loads(lines[0]))
        self.assertEqual(snapshot['matrix']['frame_hex'], 'f' * 26)
        self.assertLessEqual(len(lines[0]) + 10, 256) # includes maximum-width MessagePack request id
        for line in lines[1:]:
            event = decode_event(line)
            self.assertIn(event['kind'], ('rgb', 'matrix', 'error'))
            self.assertLessEqual(len(line) + 41, 256) # complete notification with 34-char endpoint


class ObserverTests(unittest.TestCase):
    def setUp(self):
        self.device = Device()
        self.parent = Board(timeout=0.5, transport=SimpleNamespace(disconnect=lambda: None))
        self.addCleanup(self.parent.close)

    def observe(self, **options):
        watcher = self.parent.watch(board_factory=self.device.factory, **options)
        watcher.start()
        self.addCleanup(watcher.close)
        return watcher

    def event(self, watcher, kind, timeout=3, predicate=lambda event: True):
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            try:event = watcher.get(timeout=0.1)
            except queue.Empty:continue
            if event['kind'] == kind and predicate(event):return event
        self.fail('Did not receive ' + kind)

    def test_observer_is_passive_and_does_not_take_the_writer_lock(self):
        watcher = self.observe()
        initial = self.event(watcher, 'snapshot')
        self.assertFalse(initial['state']['stale'])
        self.assertIsNone(self.parent._lock_file)
        self.assertEqual(self.device.mutations, 0)
        watcher.close()
        self.assertIsNone(self.device.owner)
        self.assertEqual(self.device.routes, {})

    def test_async_callback_delivers_readback_without_nested_calls(self):
        watcher = self.observe()
        self.event(watcher, 'snapshot')
        self.device.rgb(1, 7) # requested red; physical readback remains off
        event = self.event(watcher, 'rgb')
        self.assertTrue(event['state']['requested']['red'])
        self.assertFalse(event['state']['readback']['red'])
        event['state']['requested']['red'] = False
        self.assertTrue(watcher.latest['rgb']['3']['requested']['red']) # consumer cannot mutate cache

    def test_sequence_gap_resynchronizes_from_snapshot(self):
        watcher = self.observe();self.event(watcher, 'snapshot')
        self.device.data['s'] += 2
        self.device.rgb(4, 3)
        self.event(watcher, 'gap', predicate=lambda e:e.get('reason')=='sequence_gap')
        event = self.event(watcher, 'snapshot', predicate=lambda e:e.get('reason')=='sequence_gap')
        self.assertTrue(event['state']['rgb']['3']['readback']['blue'])

    def test_heartbeat_does_not_discard_an_already_queued_error(self):
        watcher = self.observe();self.event(watcher, 'snapshot')
        self.device.data.update(s=1, r=1, c=1)
        self.event(watcher, 'snapshot', predicate=lambda e:e.get('reason')=='heartbeat')
        self.device.send(s=1, k='e', e=-1, z=2)
        event = self.event(watcher, 'error')
        self.assertEqual(event['operation'], 'matrix.draw')
        self.assertEqual(watcher.latest['last_error']['code'], -1)

    def test_stale_boot_and_token_events_do_not_rewind_cache(self):
        watcher = self.observe();self.event(watcher, 'snapshot')
        self.device.send(b=99, q=7)
        self.device.send(h=999, q=7)
        time.sleep(0.15)
        self.assertFalse(watcher.latest['rgb']['3']['requested']['red'])
        self.device.rgb(1, 6)
        self.event(watcher, 'snapshot', predicate=lambda e:e.get('reason')=='sequence_gap')
        self.assertTrue(watcher.latest['rgb']['3']['requested']['red'])

    def test_local_overflow_recovers_latest_state(self):
        watcher = self.observe(queue_size=4)
        for index in range(100):self.device.rgb(index % 8, 7 - index % 8)
        expected = self.device.data['rgb'][0][0]
        deadline = time.monotonic() + 2
        while time.monotonic() < deadline:
            if watcher.local_drops and watcher.latest['command_id'] == self.device.data['c']:break
            time.sleep(0.02)
        self.assertGreater(watcher.local_drops, 0)
        self.assertEqual(watcher.latest['command_id'], self.device.data['c'])
        self.assertEqual(watcher.latest['rgb']['3'], rgb_state(3, expected, 7 - expected))

    def test_connection_recovery_preserves_observer_token(self):
        watcher = self.observe();self.event(watcher, 'snapshot')
        token = self.device.owner[1]
        self.device.fail_renew = True
        self.event(watcher, 'disconnected')
        self.event(watcher, 'reconnected')
        self.assertEqual(self.device.owner[1], token)
        self.assertFalse(watcher.latest['stale'])

    def test_mcu_boot_change_replaces_cached_state(self):
        watcher = self.observe();self.event(watcher, 'snapshot')
        self.device.reset()
        event = self.event(watcher, 'reconnected')
        self.assertEqual(event['previous_boot_id'], 7)
        self.assertEqual(event['boot_id'], 8)
        self.assertEqual(watcher.latest['boot_id'], 8)
        self.assertFalse(watcher.latest['stale'])

    def test_second_observer_is_rejected_without_touching_outputs(self):
        first = self.observe()
        second = self.parent.watch(board_factory=self.device.factory)
        with self.assertRaises(ControllerError):second.start()
        self.assertIsNotNone(self.device.owner)
        self.assertFalse(first._done.is_set())
        self.assertEqual(self.device.mutations, 0)

    def test_parent_close_stops_watch_and_releases_subscription(self):
        watcher = self.observe()
        self.parent.close()
        self.assertTrue(watcher._done.is_set())
        self.assertIsNone(self.device.owner)
        while not watcher._output.empty():watcher.get(timeout=0)
        with self.assertRaises(StopIteration):watcher.get()


if __name__ == '__main__':
    unittest.main()
