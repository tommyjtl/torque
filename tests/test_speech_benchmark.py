"""The isolated ASR experiment's scoring, inputs and process cleanup."""
import importlib.util
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch
import wave

ROOT = Path(__file__).resolve().parents[1]
PROJECT = ROOT / 'projects/whisper-tiny-benchmark'
sys.path.insert(0, str(PROJECT))
import common as benchmark_common
import runner as benchmark_runner


class BenchmarkTests(unittest.TestCase):
    def test_stripped_transcript_segments_keep_word_boundaries(self):
        text = benchmark_common.join_segments(['the partition', 'of the tent', '', ' thus.', 'His face'])
        self.assertEqual(text, 'the partition of the tent thus. His face')
        self.assertTrue(benchmark_common.score('the partition of the tent thus His face', text)['exact'])

    def test_guidance_fits_the_uno_q_matrix_and_uses_distinct_cues(self):
        cues = []
        for name in benchmark_common.GUIDE:
            rows = benchmark_common.guide_rows(name)
            self.assertEqual(len(rows), 8)
            self.assertTrue(all(len(row) == 13 and set(row) <= set('.#') for row in rows))
            cues.append(tuple(rows))
        self.assertEqual(len(set(cues)), len(cues))

    def test_scoring_reports_substitution_deletion_insertion_and_empty_reference(self):
        score = benchmark_common.score('THE blue light', 'the red light now')
        self.assertEqual((score['substitutions'], score['deletions'], score['insertions']), (1, 0, 1))
        self.assertEqual(score['wer'], 2 / 3)
        self.assertEqual(benchmark_common.score('one two three', 'one three')['deletions'], 1)
        self.assertTrue(benchmark_common.score('Hello, world!', 'hello world')['exact'])
        self.assertIsNone(benchmark_common.score('', 'hallucinated words')['wer'])

    def test_input_validation_refuses_wrong_rate_and_hash(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'sample.wav'
            with wave.open(str(path), 'wb') as stream:
                stream.setparams((1, 2, 48000, 0, 'NONE', 'not compressed'))
                stream.writeframes(bytes(960))
            with self.assertRaisesRegex(ValueError, '16 kHz'):
                benchmark_common.read_wav(path)
            with self.assertRaisesRegex(ValueError, 'hash'):
                benchmark_common.read_wav(path, 'bad')

    def test_worker_cleanup_terminates_only_its_own_process(self):
        worker = benchmark_runner.Worker.__new__(benchmark_runner.Worker)
        worker.process = subprocess.Popen([sys.executable, '-c', 'import time;time.sleep(60)'],
                                          stdin=subprocess.PIPE, stdout=subprocess.PIPE)
        with tempfile.TemporaryFile(mode='w') as log:
            worker.log = log
            worker.close()
            self.assertIsNotNone(worker.process.returncode)

    def test_retention_preserves_incomplete_and_linked_results(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            results = root / 'results'
            results.mkdir()
            for name in ('01', '02', '03', '04'):
                path = results / name
                path.mkdir()
                (path / 'completed.json').write_text('{}')
            (results / '01/.keep').touch()
            current = results / '05'
            current.mkdir()
            incomplete = results / 'unfinished'
            incomplete.mkdir()
            outside = root / 'outside'
            outside.mkdir()
            (results / 'linked').symlink_to(outside, target_is_directory=True)
            with patch.object(benchmark_runner, 'ROOT', root):
                benchmark_runner.retained_results(current)
            self.assertTrue(incomplete.exists())
            self.assertTrue(outside.exists())
            self.assertTrue((results / 'linked').is_symlink())
            self.assertTrue((results / '01').exists())
            self.assertFalse((results / '02').exists())
            self.assertFalse((results / '03').exists())
            self.assertTrue((results / '04').exists())


if __name__ == '__main__':
    unittest.main()
