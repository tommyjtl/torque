"""Restart evidence must distinguish state adoption from actuator replay."""
import copy
import importlib.util
from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'install'))
spec = importlib.util.spec_from_file_location('verify_restart', ROOT / 'install/verify-restart.py')
verify = importlib.util.module_from_spec(spec)
spec.loader.exec_module(verify)


class RestartVerificationTests(unittest.TestCase):
    def setUp(self):
        self.before_status = {'epoch': 'before', 'device': {'display_mode': 'user'}}
        self.after_status = {'epoch': 'after', 'device': {'display_mode': 'user'}}
        self.snapshot = {'boot_id': 42, 'command_id': 17, 'matrix': {'frame_hex': '00' * 13, 'playing': False}}

    def test_matching_state_with_new_daemon_and_no_command_is_adopted(self):
        verify.compare(self.before_status, self.snapshot, self.after_status, copy.deepcopy(self.snapshot))

    def test_same_pixels_after_a_replayed_command_are_rejected(self):
        after = copy.deepcopy(self.snapshot)
        after['command_id'] += 1
        with self.assertRaisesRegex(RuntimeError, 'replayed'):
            verify.compare(self.before_status, self.snapshot, self.after_status, after)

    def test_changed_boot_or_status_ownership_is_rejected(self):
        after = copy.deepcopy(self.snapshot)
        after['boot_id'] += 1
        with self.assertRaisesRegex(RuntimeError, 'MCU boot'):
            verify.compare(self.before_status, self.snapshot, self.after_status, after)
        self.after_status['device']['display_mode'] = 'status'
        with self.assertRaisesRegex(RuntimeError, 'not adopted'):
            verify.compare(self.before_status, self.snapshot, self.after_status, self.snapshot)
