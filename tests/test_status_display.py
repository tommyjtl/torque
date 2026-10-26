"""Status playback must yield to user output and never trust foreground caches."""
import json
from pathlib import Path
import sys
import unittest
from unittest.mock import Mock

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT/'packages/device/src'), str(ROOT/'packages/session/src')]
from torque import Frame
from torque.animations import heart_pulse, half_helix
from torque.device import Device
from torque.status_display import StatusDisplay


class Matrix:
    def __init__(self):
        self.calls = []
        self.clips = {}
        self.frame = Frame((0,)*104)
        self.playing = False

    def load(self, frames, durations):
        self.calls.append(('load', len(frames), durations))
        self.loaded = (frames, durations)

    def cache(self, slot):
        self.calls.append(('cache', slot))
        self.clips[slot] = self.loaded

    def play_cached(self, slot, repeat):
        self.calls.append(('play', slot, repeat))
        self.frame = self.clips[slot][0][0]
        self.playing = True

    def draw(self, frame):
        self.calls.append(('draw', frame))
        self.frame, self.playing = frame, False


def board():
    return Mock(matrix=Matrix())


class StatusDisplayTests(unittest.TestCase):
    def setUp(self):
        self.frames = json.loads((ROOT/'assets/status.json').read_text())
        self.board = board()
        self.display = StatusDisplay(self.board, self.frames)

    def test_heart_has_two_beats_a_dim_circular_shell_and_a_quiet_tail(self):
        for peak in (1, 3, 5, 7):
            frames = heart_pulse(peak)
            self.assertEqual(len(frames), 28)
            for frame in frames:
                self.assertEqual(frame.bits, 3)
                lit = {(i%13, i//13) for i,p in enumerate(frame.pixels) if p}
                expected = {(x+4,y+1) for y in range(5) for x in range(5)
                            if (x,y) not in ((0,0),(4,0),(0,4),(4,4))}
                self.assertEqual(lit, expected)
                self.assertTrue(all(0<=p<=peak for p in frame.pixels))
                self.assertGreaterEqual(frame.pixels[45], frame.pixels[2*13+5])
                self.assertGreaterEqual(frame.pixels[2*13+5], frame.pixels[1*13+5])
                for y in range(5):
                    for x in range(5):
                        self.assertEqual(frame.pixels[(y+1)*13+x+4],frame.pixels[(5-y)*13+8-x])
            self.assertTrue(all(frame==frames[0] for frame in frames[21:]))
        # The secondary beat is visible but weaker, with a dip between beats.
        inner = [frame.pixels[2*13+5] for frame in heart_pulse(7)]
        self.assertGreater(inner[5], inner[18])
        self.assertGreater(inner[18], inner[14])
        self.assertEqual(inner[14], inner[0])

    def test_warm_transitions_send_one_command_and_warnings_stop_playback(self):
        self.display.show('standby')
        matrix = self.board.matrix
        self.assertEqual(matrix.calls[:4], [('load',28,50),('cache',1),('load',24,40),('cache',2)])
        self.assertEqual(matrix.clips[1], (heart_pulse(5),50))
        self.assertEqual(matrix.clips[2], (half_helix(5),40))
        self.assertEqual(matrix.calls[-1], ('play',1,0))
        matrix.calls.clear()
        self.display.show('working')
        self.assertEqual(matrix.calls, [('play',2,0)])
        for state in ('waiting', 'error'):
            self.display.show(state)
            self.assertFalse(matrix.playing)
            self.assertEqual(matrix.frame, Frame.from_rows(self.frames[state]))
        matrix.calls.clear()
        self.display.show('standby')
        self.assertEqual(matrix.calls, [('play',1,0)])

    def test_failed_cache_is_not_marked_ready(self):
        self.board.matrix.cache = Mock(side_effect=RuntimeError('Lost connection'))
        with self.assertRaisesRegex(RuntimeError, 'Lost'):
            self.display.show('working')
        self.assertFalse(self.display.cached)
        self.assertFalse(self.board.matrix.playing)


class DeviceStatusTests(unittest.TestCase):
    def setUp(self):
        self.device = Device(ROOT/'assets/status.json', lambda _:None)
        self.device.board = self.board = board()
        self.device.error = None

    def test_program_can_replace_all_slots_and_status_reloads_after_release(self):
        self.device.render()
        self.assertEqual(len(self.board.matrix.calls), 5)
        self.device.render()
        self.assertEqual(len(self.board.matrix.calls), 5)  # No work on repeated telemetry.
        self.device.request('gallery', 'acquire', {})
        self.board.matrix.clips = {i:('foreground',25) for i in range(1,10)}
        self.device.set_state('working')
        self.device.render()
        self.assertEqual(len(self.board.matrix.calls), 5)
        self.device.request('gallery', 'release', {})
        self.assertEqual(self.board.matrix.calls[-1], ('play',2,0))
        self.assertEqual(self.board.matrix.clips[2], (half_helix(5),40))
        self.assertEqual(len([c for c in self.board.matrix.calls if c[0]=='load']), 4)

    def test_retained_scene_maintenance_and_reset_fault_block_every_status_write(self):
        for gate, value in (('intent', {'retained':True}), ('maintenance', True), ('reset_fault', True)):
            with self.subTest(gate=gate):
                setattr(self.device, gate, value)
                self.device.render()
                self.assertFalse(self.board.matrix.calls)
                setattr(self.device, gate, None if gate=='intent' else False)
        self.device.render()
        self.device.set_state('working')
        self.device.render()
        self.assertEqual(self.board.matrix.calls[-1], ('play',2,0))

    def test_reconnect_reloads_even_if_the_previous_connection_cached_clips(self):
        self.device.render()
        replacement = board()
        self.device.board, self.device.rendered = replacement, None
        self.device.render()
        self.assertEqual(replacement.matrix.calls[:2], [('load',28,50),('cache',1)])
        self.assertEqual(replacement.matrix.calls[-1], ('play',1,0))

    def test_reset_standby_remains_stopped_until_normal_status_changes(self):
        self.device.render()
        self.board.matrix.draw(Frame.from_rows(self.device.frames['standby']))
        self.device.state = self.device.rendered = 'standby'  # Successful reset contract.
        self.board.matrix.calls.clear()
        self.device.render()
        self.assertFalse(self.board.matrix.calls)
        self.assertFalse(self.board.matrix.playing)
        self.device.set_state('working')
        self.device.render()
        self.assertEqual(self.board.matrix.calls, [('play',2,0)])


if __name__ == '__main__':
    unittest.main()
