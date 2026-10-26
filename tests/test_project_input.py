"""Project input identity, state loss, leases and game behavior without hardware."""
import asyncio
from contextlib import contextmanager, redirect_stdout
import importlib.util
import io
import itertools
import os
from pathlib import Path
import stat
import struct
import sys
import tempfile
import unittest
from unittest.mock import Mock, patch

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / 'packages/session/src'), str(ROOT / 'packages/device/src')]
from torque import input as inputs, policy
from torque.daemon import Daemon

spec = importlib.util.spec_from_file_location('keypad_paddle', ROOT / 'agent/skills/uno-q-input/assets/paddle.py')
paddle = importlib.util.module_from_spec(spec)
spec.loader.exec_module(paddle)


def event(kind, code, value):
    return inputs.EVENT.pack(1, 2, kind, code, value)


def bitmap(codes):
    value = bytearray(128)
    for code in codes:
        value[code // 8] |= 1 << (code % 8)
    return bytes(value)


class DecoderTests(unittest.TestCase):
    def test_number_row_is_named_and_distinct_from_numpad_digits(self):
        decoder=inputs._Decoder()
        events=decoder.feed(event(1,2,1)+event(1,79,1),lambda:())
        self.assertEqual([(e.key,e.action) for e in events],[('1','press'),('KP1','press')])

    def test_fragmented_records_and_distinct_press_repeat_release(self):
        decoder = inputs._Decoder()
        raw = event(1, 75, 1) + event(1, 75, 2) + event(1, 75, 0)
        self.assertEqual(decoder.feed(raw[:7], lambda: ()), [])
        events = decoder.feed(raw[7:], lambda: ())
        self.assertEqual([(e.key, e.action) for e in events], [('KP4', 'press'), ('KP4', 'repeat'), ('KP4', 'release')])
        self.assertFalse(decoder.held)

    def test_initial_hold_is_suppressed_until_release_and_fresh_press(self):
        decoder = inputs._Decoder([113])
        self.assertEqual(decoder.feed(event(1, 113, 2) + event(1, 113, 1), lambda: ()), [])
        self.assertFalse(decoder.held - decoder.blocked)
        self.assertEqual(decoder.feed(event(1, 113, 0), lambda: ()), [])
        self.assertEqual(decoder.feed(event(1, 113, 1), lambda: ()), [inputs.KeyEvent('KNOB_PRESS', 'press', 113)])

    def test_overrun_discards_pending_actions_and_suppresses_recovered_holds(self):
        decoder = inputs._Decoder()
        raw = event(1, 75, 1) + event(0, 3, 0) + event(1, 77, 1)
        self.assertEqual(decoder.feed(raw, lambda: ()), [])
        self.assertFalse(decoder.held)
        self.assertEqual(decoder.feed(event(0, 0, 0), lambda: [77]), [inputs.KeyEvent(None, 'resync')])
        self.assertFalse(decoder.held - decoder.blocked)
        self.assertEqual(decoder.feed(event(1, 77, 2), lambda: ()), [])

    def test_duplicate_presses_unknown_text_keys_and_invalid_values_are_ignored(self):
        decoder = inputs._Decoder()
        raw = event(1, 30, 1) + event(1, 75, -1) + event(1, 75, 1) + event(1, 75, 1)
        self.assertEqual(decoder.feed(raw, lambda: ()), [inputs.KeyEvent('KP4', 'press', 75)])


class DiscoveryTests(unittest.TestCase):
    def device(self, root, number, *, name=inputs.NAME, address='02:00:00:00:00:01', bus='0005'):
        path = root / f'event{number}' / 'device'
        (path / 'id').mkdir(parents=True)
        for key, value in {'name': name, 'uniq': address, 'id/bustype': bus,
                           'id/vendor': '3434', 'id/product': '0a06'}.items():
            (path / key).write_text(value)

    def test_identity_discovery_excludes_mouse_other_bus_and_other_address(self):
        with tempfile.TemporaryDirectory() as directory, patch.object(inputs.sys, 'platform', 'linux'):
            root = Path(directory)
            self.device(root, 9)
            self.device(root, 2, name='Keychron K0 Max Mouse')
            self.device(root, 3, bus='0003')
            self.device(root, 4, address='02:00:00:00:00:02')
            devices = inputs._discover('02:00:00:00:00:01', root, Path('/fake'))
            self.assertEqual([d['node'] for d in devices], ['/fake/event9'])

    def test_open_rechecks_actual_descriptor_identity_and_closes_mismatch(self):
        info = {'node': '/fake/event9', 'address': '02:00:00:00:00:01'}
        with patch.object(inputs.os, 'open', return_value=123), \
             patch.object(inputs.os, 'fstat', return_value=Mock(st_mode=stat.S_IFCHR)), \
             patch.object(inputs, '_query', return_value=struct.pack('@HHHH', 3, 0x3434, 0x0a06, 1)), \
             patch.object(inputs.os, 'close') as close:
            with self.assertRaisesRegex(OSError, 'identity'):
                inputs._open(info)
            close.assert_called_once_with(123)

    def test_capabilities_never_read_events_held_state_or_claim_a_lease(self):
        info = {'node': '/fake/event9', 'name': inputs.NAME, 'address': '02:00:00:00:00:01'}
        with patch.object(inputs, '_discover', return_value=[info]), \
             patch.object(inputs, '_open', return_value=(123, set(inputs.DIGITS) | {113})), \
             patch.object(inputs.os, 'close') as close, \
             patch.object(inputs.os, 'read', side_effect=AssertionError('Consumed events')), \
             patch.object(inputs, '_query', side_effect=AssertionError('Queried held state')), \
             patch.object(inputs.Keypad, '_claim', side_effect=AssertionError('Claimed input')):
            result = inputs.input_capabilities()
            self.assertTrue(result['available'])
            self.assertIn('KNOB_PRESS', result['devices'][0]['advertised_keys'])
            self.assertFalse(result['records_keystrokes'])
            close.assert_called_once_with(123)

    def test_permission_failure_is_reported_without_changing_access(self):
        info = {'node': '/fake/event9', 'name': inputs.NAME, 'address': '02:00:00:00:00:01'}
        with patch.object(inputs, '_discover', return_value=[info]), \
             patch.object(inputs, '_open', side_effect=PermissionError), \
             patch.object(inputs.os, 'chmod', side_effect=AssertionError('Changed permission')):
            result = inputs.input_capabilities()
            self.assertFalse(result['available'])
            self.assertIn('denied', result['devices'][0]['reason'])


class ReaderTests(unittest.TestCase):
    @contextmanager
    def environment(self):
        read, write = os.pipe()
        info = {'node': '/fake/event9', 'name': inputs.NAME, 'address': '02:00:00:00:00:01'}
        with tempfile.TemporaryDirectory() as directory, \
             patch.object(inputs, '_discover', return_value=[info]), \
             patch.object(inputs, '_open', side_effect=lambda _: (os.dup(read), set(inputs.KEYS))), \
             patch.object(inputs, '_query', return_value=bitmap([])):
            try:
                yield Path(directory) / 'leases', write
            finally:
                os.close(read)
                try:
                    os.close(write)
                except OSError:
                    pass

    def test_project_lease_is_exclusive_and_reusable_after_close(self):
        with self.environment() as (directory, _):
            with inputs.Keypad(lock_dir=directory):
                with self.assertRaises(inputs.KeypadBusy):
                    inputs.Keypad(lock_dir=directory)
                self.assertEqual(stat.S_IMODE(directory.stat().st_mode), 0o700)
                self.assertEqual(stat.S_IMODE(next(directory.iterdir()).stat().st_mode), 0o600)
            with inputs.Keypad(lock_dir=directory):
                pass

    def test_poll_exposes_keys_and_disconnect_clears_state_and_closes_lease(self):
        with self.environment() as (directory, write):
            with inputs.Keypad(lock_dir=directory) as reader:
                os.write(write, event(1, 75, 1))
                self.assertEqual(reader.poll(0.01)[0].key, 'KP4')
                self.assertTrue(reader.is_down('KP4'))
                os.close(write)
                with self.assertRaises(inputs.KeypadDisconnected):
                    reader.poll(0.01)
                self.assertFalse(reader.held)
                self.assertIsNone(reader.lease)
                self.assertIsNone(reader.fd)

    def test_multiple_readable_devices_require_selection_and_close_descriptors(self):
        fds = []
        def opened(info):
            fd = os.open(os.devnull, os.O_RDONLY)
            fds.append(fd)
            return fd, set(inputs.DIGITS)
        with patch.object(inputs, '_discover', return_value=[{'address': 'one'}, {'address': 'two'}]), \
             patch.object(inputs, '_open', side_effect=opened):
            with self.assertRaisesRegex(inputs.KeypadUnavailable, 'Choose'):
                inputs.Keypad()
        for fd in fds:
            with self.assertRaises(OSError):
                os.fstat(fd)

    def test_poll_bounds_and_initial_state_failure_release_resources(self):
        with self.environment() as (directory, _):
            with inputs.Keypad(lock_dir=directory) as reader:
                for value in (-1, 2, True, float('nan')):
                    with self.assertRaises(ValueError):
                        reader.poll(value)
            with patch.object(inputs, '_query', side_effect=OSError):
                with self.assertRaises(inputs.KeypadUnavailable):
                    inputs.Keypad(lock_dir=directory)
            with inputs.Keypad(lock_dir=directory):
                pass


class ToolTests(unittest.TestCase):
    def test_discovery_tool_is_validated_read_only_in_every_policy(self):
        for mode in policy.MODES:
            self.assertFalse(policy.needs_approval('input_capabilities', mode))
        with self.assertRaises(ValueError):
            policy.validate('input_capabilities', {'capture': True})
        with patch.object(inputs, 'input_capabilities', return_value={'available': False}) as discover:
            daemon = object.__new__(Daemon)
            self.assertEqual(asyncio.run(daemon.execute('input_capabilities', {})), {'available': False})
            discover.assert_called_once_with()


class GameTests(unittest.TestCase):
    def test_movement_limits_pause_and_collision(self):
        game = paddle.Game()
        for _ in range(50):
            game.press('KP4')
        self.assertEqual(game.paddle, 1)
        game.x, game.y = 1, 6
        game.step(0.25)
        self.assertEqual(game.score, 1)
        game.x, game.y = 12, 6
        game.step(0.25)
        self.assertEqual(game.missed, 1)
        game.press('KNOB_PRESS')
        before = game.frame()
        game.press('KP6')
        game.step(10)
        self.assertEqual(game.frame(), before)

    def test_offline_preview_never_opens_input_or_board(self):
        with patch.object(paddle, 'Keypad', side_effect=AssertionError('Opened input')), \
             patch.object(paddle, 'Board', side_effect=AssertionError('Opened output')), \
             redirect_stdout(io.StringIO()) as output:
            self.assertEqual(paddle.main([]), 0)
            self.assertEqual(sum(len(line) == 13 for line in output.getvalue().splitlines()), 8)

    def test_manual_missing_input_does_not_open_board(self):
        with patch.object(paddle, 'Keypad', side_effect=inputs.KeypadUnavailable), \
             patch.object(paddle, 'Board', side_effect=AssertionError('Opened output')):
            with self.assertRaises(inputs.KeypadUnavailable):
                paddle.play(1, 'keypad', 7)

    def test_finite_fallback_cleans_up_and_disconnection_is_reported(self):
        board = Mock()
        board.__enter__ = Mock(return_value=board)
        board.__exit__ = Mock()
        with patch.object(paddle, 'Keypad', side_effect=inputs.KeypadUnavailable), \
             patch.object(paddle, 'Board', return_value=board), \
             patch.object(paddle.time, 'monotonic', side_effect=itertools.count(0, 0.02)), \
             patch.object(paddle.time, 'sleep'), redirect_stdout(io.StringIO()):
            self.assertEqual(paddle.play(0.2, 'auto', 7), 0)
            board.matrix.draw.assert_called()
            board.matrix.clear.assert_called_once()
        board.reset_mock()
        keypad = Mock()
        keypad.__enter__ = Mock(return_value=keypad)
        keypad.__exit__ = Mock()
        keypad.poll.side_effect = inputs.KeypadDisconnected
        with patch.object(paddle, 'Keypad', return_value=keypad), \
             patch.object(paddle, 'Board', return_value=board), \
             patch.object(paddle.time, 'monotonic', side_effect=itertools.count(0, 0.02)), \
             redirect_stdout(io.StringIO()) as output:
            self.assertEqual(paddle.play(0.2, 'keypad', 7), 1)
            board.matrix.clear.assert_called_once()
            self.assertIn('disconnected', output.getvalue())


if __name__ == '__main__':
    unittest.main()
