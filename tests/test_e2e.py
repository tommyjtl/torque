"""Fresh-install test boundaries and report preservation; no root or board required."""
import getpass
import importlib.util
import json
import os
from pathlib import Path
import pwd
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('e2e', ROOT / 'install/e2e.py')
e2e = importlib.util.module_from_spec(spec)
spec.loader.exec_module(e2e)


class FreshE2ETests(unittest.TestCase):
    def test_archive_moves_only_enumerated_managed_paths_and_keeps_contents(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            workspace = root / 'workspace'
            workspace.mkdir()
            (workspace / 'user.py').write_text('user program')
            credential = root / 'credential'
            credential.write_text('fixture only')
            runtime = root / 'managed-runtime'
            runtime.mkdir()
            (runtime / 'module.py').write_text('runtime')
            state = root / 'managed-state'
            state.mkdir()
            (state / 'session.json').write_text('{}')
            e2e.archive_entries([('runtime', runtime), ('state', state)], root / 'backup')
            self.assertEqual((root / 'backup/runtime/module.py').read_text(), 'runtime')
            self.assertEqual((root / 'backup/state/session.json').read_text(), '{}')
            self.assertFalse(runtime.exists())
            self.assertEqual((workspace / 'user.py').read_text(), 'user program')
            self.assertEqual(credential.read_text(), 'fixture only')

    def test_preservation_detects_changed_or_deleted_existing_user_files(self):
        with tempfile.TemporaryDirectory() as temp:
            home = Path(temp)
            workspace = home / 'torque'
            workspace.mkdir()
            (workspace / 'AGENTS.md').write_text('my preferences')
            (workspace / 'link').symlink_to('AGENTS.md')
            (home / '.fx').mkdir()
            (home / '.fx/settings.json').write_text('{"provider":"example"}')
            plan = {'home': str(home), 'workspace': str(workspace),
                    'workspace_before': e2e.workspace_snapshot(workspace),
                    'global_fx_settings_before': e2e.digest(home / '.fx/settings.json')}
            (workspace / 'new-test.py').write_text('new file is allowed')
            e2e.preserved(plan)
            (workspace / 'AGENTS.md').write_text('overwritten')
            with self.assertRaisesRegex(RuntimeError, 'workspace'):
                e2e.preserved(plan)
            (workspace / 'AGENTS.md').write_text('my preferences')
            (home / '.fx/settings.json').write_text('{}')
            with self.assertRaisesRegex(RuntimeError, 'Global FX'):
                e2e.preserved(plan)

    def test_boot_unit_runs_tests_as_user_and_removes_its_own_registration(self):
        plan = {'run_id': '20261024T230000-a123b456', 'user': 'arduino',
                'run_dir': '/home/arduino/.cache/torque/e2e/20261024T230000-a123b456'}
        name, unit = e2e.unit_text(plan)
        self.assertIn('"/usr/sbin/runuser" "-u" "arduino" "--"', unit)
        self.assertIn('"after-boot"', unit)
        self.assertIn('ExecStopPost=-/usr/bin/systemctl disable ' + name, unit)
        self.assertIn('/etc/systemd/system/' + name, unit)
        self.assertNotIn('--now', unit)

    def test_plan_rejects_unrelated_directories_before_system_actions(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            plan = {'run_id': '20261024T230000-a123b456', 'user': getpass.getuser(),
                    'run_dir': str(root), 'home': str(Path.home()),
                    'workspace': str(Path.home() / 'torque'), 'stage': str(root / 'stage')}
            path = root / 'plan.json'
            path.write_text(json.dumps(plan))
            with self.assertRaisesRegex(RuntimeError, 'outside'):
                e2e.load_plan(path)

    def test_reset_rejects_an_unrelated_active_app_before_stopping_anything(self):
        class System:
            base64 = __import__('base64')
            def __init__(self):
                self.calls=[]
            def run(self, *args, **kwargs):
                self.calls.append(args)
            def app(self, *args):
                return json.dumps({'apps':[{'id':'unrelated','status':'running'}]})
        system=System()
        # Avoid reading host installation paths; all paths are absent in this fixture.
        with patch.object(e2e.Path, 'exists', return_value=False), \
             patch.object(e2e.Path, 'is_symlink', return_value=False):
            with self.assertRaisesRegex(RuntimeError, 'Another Arduino app'):
                e2e.reset_managed(system, {'user':'arduino'})
        self.assertEqual(system.calls, [])

    def test_install_requires_explicit_reset_authorization(self):
        with self.assertRaises(SystemExit) as result:
            with patch.object(e2e,'load_plan',return_value=({},None)):
                e2e.main(['install','--plan','/fixture'])
        self.assertEqual(result.exception.code,2)
