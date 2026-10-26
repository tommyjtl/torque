"""Acceptance defaults must not cause inference or reset an active user's work."""
import importlib.util
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import Mock, patch

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / 'packages/session/src'), str(ROOT / 'packages/device/src')]
spec = importlib.util.spec_from_file_location('verify_controls', ROOT / 'install/verify-controls.py')
verify = importlib.util.module_from_spec(spec)
spec.loader.exec_module(verify)


class VerifierTests(unittest.TestCase):
    def state(self, active=False):
        return {'active': active, 'pending': [], 'device': {'ready': True, 'owner': None, 'display_mode': 'status'},
                'model': 'fixture', 'session_id': 'history', 'default_permission_mode': 'auto'}

    def test_busy_guard_prevents_every_effectful_acceptance_step(self):
        with patch.object(verify, 'command', return_value=self.state(True)) as command:
            with self.assertRaisesRegex(RuntimeError, 'idle'):
                verify.verify(models=True, reset=True)
            command.assert_called_once_with('status', '--json')

    def test_default_is_read_only_and_preserves_configuration(self):
        board = Mock()
        board.__enter__ = Mock(return_value=board)
        board.__exit__ = Mock()
        board.info.return_value = {'boot_id': 7}
        with tempfile.TemporaryDirectory() as directory:
            home = Path(directory)
            config = home / '.config/torque/settings.json'
            config.parent.mkdir(parents=True)
            config.write_text(json.dumps({'release_root': str(home), 'model': 'fixture'}))
            before = config.read_bytes()
            with patch.object(verify, 'command', return_value=self.state()) as command, \
                 patch.object(verify.subprocess, 'run', return_value=Mock(stdout='model reset')), \
                 patch('torque.installation.verify_python_sources', return_value={'matched': True, 'modules': 12}), \
                 patch('torque.Board', return_value=board), patch.object(verify.Path, 'home', return_value=home):
                result = verify.verify()
            self.assertTrue(result['passed'])
            self.assertEqual(config.read_bytes(), before)
            self.assertTrue(all(call.args == ('status', '--json') for call in command.call_args_list))
            board.snapshot.assert_not_called()


if __name__ == '__main__':
    unittest.main()
