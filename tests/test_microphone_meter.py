import importlib.util
import itertools
from pathlib import Path
import tempfile
import sys
import struct
import unittest
from unittest.mock import MagicMock, patch

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT/'packages/session/src'),str(ROOT/'packages/device/src')]
from torque.audio import AudioChunk
spec = importlib.util.spec_from_file_location('microphone_meter', ROOT/'examples/07-microphone-level-meter/main.py')
meter = importlib.util.module_from_spec(spec)
spec.loader.exec_module(meter)


class MeterTests(unittest.TestCase):
    def test_silence_floor_and_full_scale_produce_bounded_monotonic_heights(self):
        self.assertEqual(meter.level_height(-float('inf')), 0)
        levels = [meter.level_height(db) for db in (-90,-60,-54,-48,-42,-36,-30,-24,-18,-12,0)]
        self.assertEqual(levels, sorted(levels))
        self.assertEqual((min(levels),max(levels)), (0,8))

    def test_history_is_recent_thirteen_columns_with_native_brightness(self):
        frame = meter.level_frame([8]*20 + [0,1,2])
        self.assertEqual(frame.bits, 3)
        self.assertTrue(all(v in (0,3,7) for v in frame.pixels))
        for x,height in enumerate([8]*10+[0,1,2]):
            self.assertEqual(sum(frame.pixels[y*13+x]>0 for y in range(8)),height)

    def test_preview_and_listing_never_open_mic_or_board(self):
        with tempfile.TemporaryDirectory() as directory, \
             patch.object(meter, 'Microphone', side_effect=AssertionError('capture')), \
             patch.object(meter, 'Board', side_effect=AssertionError('MCU')), \
             patch.object(meter, 'audio_capabilities', return_value={'capture_started':False}):
            self.assertEqual(meter.main(['--output-dir',directory]), 0)
            self.assertIn('Synthetic offline preview', (Path(directory)/'preview.svg').read_text())
            self.assertEqual(meter.main(['--list']), 0)

    def test_invalid_durations_and_levels_fail_before_capture(self):
        for args in (['--seconds','0'],['--seconds','121'],['--fps','30'],['--floor-dbfs','nan']):
            with self.assertRaises(SystemExit), patch.object(meter, 'Microphone') as mic:
                meter.main(args)
            mic.assert_not_called()

    def test_measured_energy_changes_reach_matrix_frames_and_release_resources(self):
        mic, board = MagicMock(), MagicMock()
        mic.__enter__.return_value = mic
        board.__enter__.return_value = board
        mic.read.side_effect = [AudioChunk(b'\0'*16), AudioChunk(struct.pack('<i',2**30)*4), None]
        clock = itertools.count(step=0.25)
        with patch.object(meter, 'Microphone', return_value=mic), patch.object(meter, 'Board', return_value=board), \
             patch.object(meter.time, 'monotonic', side_effect=lambda:next(clock)), patch.object(meter.signal,'signal'):
            self.assertEqual(meter.main(['--live','--seconds','10']), 0)
        frames = [call.args[0] for call in board.matrix.draw.call_args_list]
        self.assertEqual(len(frames), 2)
        self.assertFalse(any(frames[0].pixels))
        self.assertTrue(any(frames[1].pixels))
        mic.read.assert_called_with(frames=1200, latest=True)
        board.matrix.clear.assert_called_once()
        mic.__exit__.assert_called_once()
        board.__exit__.assert_called_once()

    def test_capture_failure_still_clears_matrix_and_exits_microphone_context(self):
        mic, board = MagicMock(), MagicMock()
        mic.__enter__.return_value = mic
        board.__enter__.return_value = board
        mic.read.side_effect = TimeoutError('stalled input')
        with patch.object(meter,'Microphone',return_value=mic), patch.object(meter,'Board',return_value=board), \
             patch.object(meter.signal,'signal'), self.assertRaises(TimeoutError):
            meter.main(['--live'])
        board.matrix.clear.assert_called_once()
        mic.__exit__.assert_called_once()
