"""Artifact parity must detect stale/missing/extra Python code, ignoring mtimes."""
import os
from pathlib import Path
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / 'packages/session/src'), str(ROOT / 'packages/device/src')]
from torque.installation import verify_python_sources


class ArtifactTests(unittest.TestCase):
    def fixture(self, root):
        source = root / 'packages/session/src/torque'
        installed = root / 'installed/torque'
        source.mkdir(parents=True)
        installed.mkdir(parents=True)
        for name in ('__init__.py', 'protocol.py'):
            (source / name).write_text('version = "fresh"\n')
            (installed / name).write_bytes((source / name).read_bytes())
        return source, installed

    def test_stale_same_second_artifact_is_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source, installed = self.fixture(root)
            (installed / 'protocol.py').write_text('version = "stale"\n')
            os.utime(source / 'protocol.py', (1700000000.9, 1700000000.9))
            os.utime(installed / 'protocol.py', (1700000000.1, 1700000000.1))
            with self.assertRaisesRegex(RuntimeError, 'protocol.py'):
                verify_python_sources(root, installed=installed)

    def test_missing_extra_modules_are_rejected_but_examples_are_data(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source, installed = self.fixture(root)
            (installed / '_examples').mkdir()
            (installed / '_examples/main.py').write_text('example = True')
            self.assertEqual(verify_python_sources(root, installed=installed)['modules'], 2)
            (installed / 'unexpected.py').write_text('old = True')
            with self.assertRaisesRegex(RuntimeError, 'unexpected.py'):
                verify_python_sources(root, installed=installed)
            (installed / 'unexpected.py').unlink()
            (installed / 'protocol.py').unlink()
            with self.assertRaisesRegex(RuntimeError, 'protocol.py'):
                verify_python_sources(root, installed=installed)


if __name__ == '__main__':
    unittest.main()
