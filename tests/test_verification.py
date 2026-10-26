import importlib.util
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts'))
from fx_common import SetupError
spec = importlib.util.spec_from_file_location('verify_fx', ROOT / 'scripts/verify-fx.py')
verify_fx = importlib.util.module_from_spec(spec)
spec.loader.exec_module(verify_fx)


class VerificationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.profile = Path(self.temp.name)
        (self.profile / '.fx').mkdir()
        (self.profile / '.fx/settings.json').write_text('{"models":{"modular":"test/model"}}')
        self.status = {'model_source': 'modular', 'model': 'test/model',
                       'provider_endpoint': 'https://api.modular.com/v1', 'permission_mode': 'auto'}

    def response(self, value):
        return subprocess.CompletedProcess([], 0, json.dumps(value), '')

    def run_mocked(self, responses):
        with patch.object(verify_fx, 'fx_path', return_value='/example/fx'), \
             patch.object(verify_fx, 'saved_key', return_value='fixture-token'), \
             patch.object(verify_fx, 'run_fx', side_effect=responses) as run:
            result = verify_fx.verify(self.profile)
            return result, run.call_args_list

    def test_permission_bypass_is_rejected_before_api_requests(self):
        self.status['permission_mode'] = 'full-access'
        with self.assertRaises(SetupError):
            self.run_mocked([self.response(self.status)])

    def test_fabricated_architecture_without_tool_execution_is_rejected(self):
        with self.assertRaises(SetupError):
            self.run_mocked([self.response(self.status),
                             self.response({'exit_code': 0, 'final_output': 'MODULAR_OK'}),
                             self.response({'exit_code': 0, 'final_output': verify_fx.platform.machine(), 'tool_calls': []})])

    def test_success_requires_exact_command_and_successful_tool_result(self):
        tool = {'exit_code': 0, 'final_output': verify_fx.platform.machine(), 'tool_calls': [
            {'name': 'shell', 'status': 'success', 'command_result': {'command': 'uname -m', 'exit_code': 0}}]}
        result, calls = self.run_mocked([self.response(self.status),
                                        self.response({'exit_code': 0, 'final_output': 'MODULAR_OK'}), self.response(tool)])
        self.assertEqual(result, 0)
        self.assertEqual(len(calls), 3)
        self.assertIn('--no-save', calls[1].args[1])
        self.assertNotIn('--full-access', calls[2].args[1])


if __name__ == '__main__':
    unittest.main()
