"""Natural finalization must not be confused with stop-forced transcription."""
import importlib.util
from pathlib import Path
from types import SimpleNamespace
import unittest

path = Path(__file__).resolve().parents[1] / 'projects/moonshine-tiny-benchmark/metrics.py'
spec = importlib.util.spec_from_file_location('moonshine_benchmark_metrics', path)
metrics = importlib.util.module_from_spec(spec)
spec.loader.exec_module(metrics)


def line(identifier=1, text='hello', start=0):
    return SimpleNamespace(text=text, line_id=identifier, start_time=start,
                           duration=1, last_transcription_latency_ms=123)


class EventTests(unittest.TestCase):
    def test_partial_is_not_final(self):
        events = metrics.Events(clock=lambda: 2)
        events.record('started', line())
        events.record('partial', line())
        state = events.summary()
        self.assertFalse(state['natural_final_proven'])
        self.assertIsNone(state['natural_final_at'])
        self.assertEqual(state['first_partial_at'], 2)

    def test_natural_completion_is_final(self):
        events = metrics.Events(clock=lambda: 3)
        events.record('started', line())
        events.record('completed', line())
        self.assertTrue(events.summary()['natural_final_proven'])
        self.assertEqual(events.summary()['natural_final_at'], 3)

    def test_stop_forced_completion_is_excluded(self):
        events = metrics.Events()
        events.record('started', line())
        events.forcing = True
        events.record('completed', line())
        self.assertFalse(events.summary()['natural_final_proven'])
        self.assertEqual(events.summary()['forced_nonempty_lines'], 1)

    def test_pending_later_line_prevents_whole_utterance_final_claim(self):
        events = metrics.Events()
        events.record('started', line())
        events.record('completed', line())
        events.record('started', line(2, 'world', 2))
        self.assertFalse(events.summary()['natural_final_proven'])
        events.record('completed', line(2, 'world', 2))
        self.assertEqual(events.summary()['text'], 'hello world')
        self.assertTrue(events.summary()['natural_final_proven'])

    def test_duration_limit_is_not_a_natural_endpoint_success(self):
        events = metrics.Events()
        value = line()
        value.duration = 15
        events.record('started', value)
        events.record('completed', value)
        self.assertFalse(events.summary()['natural_final_proven'])

    def test_native_error_invalidates_a_finalization_claim(self):
        events = metrics.Events()
        events.record('started', line())
        events.record('completed', line())
        events.errors.append('native transcription failed')
        self.assertFalse(events.summary()['natural_final_proven'])
