"""Checkout setup delegates to the staged installer without shell key arguments."""
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]


class BootstrapTests(unittest.TestCase):
    def test_checkout_path_with_spaces_preserves_arguments(self):
        with tempfile.TemporaryDirectory(prefix='torque checkout ') as tmp:
            root = Path(tmp)
            shutil.copyfile(ROOT / 'setup.sh', root / 'setup.sh')
            (root / 'install').mkdir()
            (root / 'install/stage.py').write_text('import sys\nprint(repr(sys.argv[1:]))\n')
            result = subprocess.run(['bash', str(root / 'setup.sh'), '--model', 'some/model', '--stage-only'],
                                    capture_output=True, text=True, check=True)
            self.assertIn("['--model', 'some/model', '--stage-only']", result.stdout)

    def test_help_does_not_touch_board_configuration(self):
        result = subprocess.run(['bash', str(ROOT / 'setup.sh'), '--help'], capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn('--reuse-fx-key', result.stdout)
        self.assertIn('--stage-only', result.stdout)

    def test_key_as_argument_is_rejected(self):
        result = subprocess.run(['bash', str(ROOT / 'setup.sh'), '--api-key', 'fixture'], capture_output=True, text=True)
        self.assertEqual(result.returncode, 2)
        self.assertIn('unrecognized arguments', result.stderr)
