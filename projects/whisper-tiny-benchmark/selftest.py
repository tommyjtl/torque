"""Synthetic DSP checks in the private environment; never opens the microphone."""
import unittest
from unittest.mock import Mock
import numpy as np
from worker import Endpoint


class DSPTests(unittest.TestCase):
    def test_fragmented_resampling_preserves_sample_count_and_rejects_alias(self):
        n = np.arange(48000)
        raw = (np.sin(2 * np.pi * 12000 * n / 48000) * (2**30)).astype('<i4').tobytes()
        endpoint = Endpoint(48000)
        endpoint.vad = Mock(is_speech=Mock(return_value=False))
        for position in range(0, len(raw), 960 * 4):
            endpoint.consume(raw[position:position + 960 * 4])
        output, state = endpoint.finish()
        self.assertEqual(state['input_frames'], 48000)
        self.assertEqual(len(output), 16000)
        self.assertLess(float(np.max(np.abs(output[1000:-1000]))), .01)
        self.assertFalse(state['has_speech'])

    def test_endpoint_waits_for_silence_and_resets_per_trial(self):
        endpoint = Endpoint(16000)
        detector = Mock()
        detector.is_speech.side_effect = [True] * 20 + [False] * 35
        endpoint.vad = detector
        for _ in range(54):
            self.assertFalse(endpoint.consume(bytes(640))['endpoint'])
        state = endpoint.consume(bytes(640))
        self.assertTrue(state['endpoint'])
        self.assertEqual(state['last_speech_sample'], 6400)
        self.assertEqual(state['output_frames'], 17600)
        self.assertFalse(Endpoint(16000).summary()['endpoint'])

    def test_pcm_buffer_is_bounded(self):
        endpoint = Endpoint(16000)
        with self.assertRaisesRegex(ValueError, 'limit'):
            endpoint.consume(bytes(16000 * 17 * 2))

    def test_dc_and_ac_statistics_are_separate(self):
        endpoint = Endpoint(16000)
        endpoint.vad = Mock(is_speech=Mock(return_value=False))
        state = endpoint.consume(np.full(3200, 8192, dtype='<i2').tobytes())
        self.assertAlmostEqual(state['input_mean'], .25)
        self.assertAlmostEqual(state['input_rms'], .25)
        self.assertAlmostEqual(state['input_ac_rms'], 0)

    def test_resampler_burst_stops_at_first_endpoint_not_later_speech(self):
        endpoint = Endpoint(16000)
        detector = Mock()
        detector.is_speech.side_effect = [True] * 20 + [False] * 35 + [True] * 10
        endpoint.vad = detector
        state = endpoint.consume(bytes(65 * 640))
        self.assertTrue(state['endpoint'])
        self.assertEqual(state['last_speech_sample'], 6400)
        self.assertEqual(detector.is_speech.call_count, 55)
        samples, final = endpoint.finish()
        self.assertEqual(len(samples), 55 * 320)
        self.assertEqual(final['last_speech_sample'], 6400)


if __name__ == '__main__':
    unittest.main()
