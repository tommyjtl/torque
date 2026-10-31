"""GPU probe acceptance must reject skipped, incomplete or inaccurate work."""
import importlib.util
from pathlib import Path
import unittest

PATH = Path(__file__).resolve().parents[1] / 'projects/ncnn-speech-benchmark/evidence.py'
spec = importlib.util.spec_from_file_location('ncnn_evidence', PATH)
evidence = importlib.util.module_from_spec(spec)
spec.loader.exec_module(evidence)


class NcnnEvidenceTests(unittest.TestCase):
    def rows(self):
        return [{'kind': 'device', 'hardware': True, 'name': 'Turnip Adreno (TM) 702'},
                *[{'kind': 'gpu_operation', 'operation': name, 'k': k, 'direct_vkmat': True,
                   'submitted': True, 'max_error': 0, 'elements': 384, 'passed': True}
                  for name, k in (('BinaryOp_ADD', 32), ('InnerProduct_MATRIX', 16), ('InnerProduct_MATRIX', 32), ('InnerProduct_MATRIX', 64))],
                {'kind': 'probe_complete', 'passed': True}]

    def test_initialization_and_software_renderer_are_not_gpu_success(self):
        self.assertFalse(evidence.probe_passed(self.rows()[:1]))
        rows = self.rows(); rows[0]['name'] = 'llvmpipe'; rows[0]['hardware'] = False
        self.assertFalse(evidence.probe_passed(rows))

    def test_all_calculations_and_completion_are_required(self):
        self.assertTrue(evidence.probe_passed(self.rows()))
        self.assertFalse(evidence.probe_passed(self.rows()[:-1]))
        rows = self.rows(); rows.pop(2)
        self.assertFalse(evidence.probe_passed(rows))

    def test_fallback_unsubmitted_bad_or_nonfinite_results_are_rejected(self):
        for key, value in (('direct_vkmat', False), ('submitted', False), ('max_error', .01),
                           ('max_error', float('nan')), ('passed', 'true')):
            with self.subTest(key=key, value=value):
                rows = self.rows(); rows[1][key] = value
                self.assertFalse(evidence.probe_passed(rows))

    def test_invalid_native_output_is_not_silently_dropped(self):
        with self.assertRaises(ValueError):
            evidence.parse_rows('{"kind":"device"}\nnot-json')


if __name__ == '__main__':
    unittest.main()
