"""The selected entrypoint must keep CPU execution explicit."""
import importlib.util
from pathlib import Path
import sys
import unittest

PROJECT = Path(__file__).resolve().parents[1] / 'projects/zipformer-cpu'


def module(name, filename):
    spec = importlib.util.spec_from_file_location(name, PROJECT / filename)
    result = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(result)
    return result


class CpuSelectionTests(unittest.TestCase):
    def test_native_command_pins_cpu(self):
        # Import with project-local helpers without changing other tests' modules.
        previous = {name: sys.modules.get(name) for name in ('common', 'evidence')}
        try:
            sys.modules['common'] = module('cpu_common', 'common.py')
            sys.modules['evidence'] = module('cpu_evidence', 'evidence.py')
            runner = module('cpu_runner', 'main.py')
            argv = runner.command('/native', '/models', 1, True, [{'path': 'fixtures/clip.wav'}])
            self.assertEqual(argv[:5], ['/native', 'cpu', '/models', '1', 'bulk'])
            self.assertNotIn('gpu', argv)
        finally:
            for name, value in previous.items():
                if value is None:
                    sys.modules.pop(name, None)
                else:
                    sys.modules[name] = value

    def test_acceptance_rejects_gpu_and_incomplete_output(self):
        evidence = module('cpu_evidence_checks', 'evidence.py')
        rows = [{'kind': 'initialization', 'gpu_requested': False},
                {'kind': 'file', 'natural_final_proven': True, 'text': 'hello'},
                {'kind': 'speech_complete', 'passed': True}]
        self.assertTrue(evidence.cpu_completed(rows, 1))
        rows[0]['gpu_requested'] = True
        self.assertFalse(evidence.cpu_completed(rows, 1))
        rows[0]['gpu_requested'] = False
        self.assertFalse(evidence.cpu_completed(rows[:-1], 1))
