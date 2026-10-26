import importlib.util
import json
import os
from pathlib import Path
import stat
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import MagicMock, patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts'))
from fx_common import SetupError, load_catalog, run_fx, saved_key
spec = importlib.util.spec_from_file_location('configure_fx', ROOT / 'scripts/configure-fx.py')
configure_fx = importlib.util.module_from_spec(spec)
spec.loader.exec_module(configure_fx)

FIXTURE_KEY = 'test-token-not-a-real-credential'


class ConfigurationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.profile = Path(self.temp.name)
        self.catalog = load_catalog()
        self.model = self.catalog['default_model']

    def configure(self, key=FIXTURE_KEY):
        return configure_fx.configure(self.profile, self.catalog, key, self.model)

    def test_new_profile_is_private_and_credentials_are_not_configuration(self):
        backup = self.configure()
        settings = self.profile / '.fx/settings.json'
        key = self.profile / '.config/fx/modular-api-key'
        self.assertNotIn(FIXTURE_KEY, settings.read_text())
        self.assertEqual(saved_key(self.profile), FIXTURE_KEY)
        self.assertEqual(stat.S_IMODE(key.stat().st_mode), 0o600)
        self.assertEqual(stat.S_IMODE(key.parent.stat().st_mode), 0o700)
        self.assertEqual(stat.S_IMODE(settings.stat().st_mode), 0o600)
        self.assertIn('.fx/settings.json', json.loads((backup / 'originally-absent.json').read_text()))
        self.assertFalse((backup / '.config/fx/modular-api-key').exists())

    def test_merge_preserves_unrelated_settings_and_existing_metadata(self):
        existing = {'permission_mode': 'ask', 'theme': 'dark', 'workspaces': {'/somewhere': {'provider': 'codex'}},
                    'models': {'codex': 'example'}, 'providers': {'other': {'custom': True}, 'modular': {
                        'reviewer_model': 'custom-reviewer', 'model_metadata': {
                            self.model: {'max_output_tokens': 1234}, 'extra/model': {'context_window': 2000}}}}}
        path = self.profile / '.fx/settings.json'
        path.parent.mkdir()
        before = json.dumps(existing).encode()
        path.write_bytes(before)
        backup = self.configure()
        after = json.loads(path.read_text())
        for name in ['permission_mode', 'theme', 'workspaces']:
            self.assertEqual(after[name], existing[name])
        self.assertEqual(after['providers']['other'], existing['providers']['other'])
        self.assertEqual(after['models']['codex'], 'example')
        modular = after['providers']['modular']
        self.assertEqual(modular['reviewer_model'], 'custom-reviewer')
        self.assertEqual(modular['model_metadata'][self.model]['max_output_tokens'], 1234)
        self.assertIn('extra/model', modular['model_metadata'])
        self.assertEqual((backup / '.fx/settings.json').read_bytes(), before)
        self.assertEqual(stat.S_IMODE((backup / '.fx/settings.json').stat().st_mode), 0o600)

    def test_rerun_is_idempotent_and_does_not_duplicate_hooks_or_backups(self):
        self.configure()
        paths = [self.profile / x for x in ['.fx/settings.json', '.bashrc', '.profile', '.config/fx/modular-env.sh']]
        before = [p.read_bytes() for p in paths]
        backups = list((self.profile / '.fx/backups').iterdir())
        self.assertIsNone(self.configure())
        self.assertEqual([p.read_bytes() for p in paths], before)
        self.assertEqual(list((self.profile / '.fx/backups').iterdir()), backups)
        self.assertEqual((self.profile / '.bashrc').read_text().count(configure_fx.START), 1)

    def test_credential_is_data_not_shell_code_and_loads_before_early_return(self):
        # These are fixture characters, not a real API key or a shell assignment.
        literal = 'fixture-$(touch-SHOULD_NOT_EXIST)-`echo`-quote\"\''
        (self.profile / '.bashrc').write_text('case $- in *i*) ;; *) return;; esac\n# original content\n')
        self.configure(literal)
        env = os.environ.copy()
        env['HOME'] = str(self.profile)
        env.pop('MODULAR_API_KEY', None)
        # Compare internally; never ask the shell to print the credential.
        command = '. "$HOME/.bashrc"; python3 -c \'import os,pathlib; assert os.environ["MODULAR_API_KEY"] == (pathlib.Path.home()/".config/fx/modular-api-key").read_text().strip()\''
        result = subprocess.run(['bash', '-c', command], env=env, capture_output=True)
        self.assertEqual(result.returncode, 0, result.stderr.decode())
        self.assertEqual(result.stdout, b'')
        self.assertTrue((self.profile / '.bashrc').read_text().endswith('# original content\n'))

    def test_existing_login_file_is_preserved_and_backed_up(self):
        original = '# user login\nexport EXAMPLE_SETTING=yes\n'
        (self.profile / '.bash_profile').write_text(original)
        backup = self.configure()
        self.assertTrue((self.profile / '.bash_profile').read_text().endswith(original))
        self.assertEqual((backup / '.bash_profile').read_text(), original)
        self.assertFalse((self.profile / '.profile').exists())

    def test_invalid_json_and_duplicate_fields_do_not_change_profile(self):
        path = self.profile / '.fx/settings.json'
        path.parent.mkdir()
        for content in ['{bad', '{"models":{},"models":{}}', '[]', '{"providers":[]}']:
            path.write_text(content)
            with self.assertRaises(SetupError):
                self.configure()
            self.assertEqual(path.read_text(), content)
            self.assertFalse((self.profile / '.config/fx/modular-api-key').exists())

    def test_discovery_filters_owned_models_and_preserves_custom_models(self):
        self.configure()
        path = self.profile / '.fx/settings.json'
        data = json.loads(path.read_text())
        data['providers']['modular']['model_metadata']['custom/model'] = {'context_window': 12345}
        path.write_text(json.dumps(data))
        visible = {'google/gemma-4-31b-it', 'new/unknown-model'}
        configure_fx.configure(self.profile, self.catalog, FIXTURE_KEY, 'google/gemma-4-31b-it', available=visible)
        data = json.loads(path.read_text())
        self.assertEqual(set(data['providers']['modular']['model_metadata']), {'google/gemma-4-31b-it', 'custom/model'})
        self.assertEqual(data['models']['modular'], 'google/gemma-4-31b-it')

    def test_discovery_failure_does_not_install_fx_or_change_settings(self):
        path = self.profile / '.fx/settings.json'
        path.parent.mkdir()
        path.write_text('{"theme":"preserve"}')
        with patch.object(sys, 'argv', ['configure-fx.py', '--no-verify']), \
             patch.object(configure_fx, 'ensure_board'), \
             patch.object(configure_fx.Path, 'home', return_value=self.profile), \
             patch.object(configure_fx, 'obtain_key', return_value=FIXTURE_KEY), \
             patch.object(configure_fx, 'discover_models', side_effect=SetupError('unavailable')), \
             patch.object(configure_fx, 'ensure_fx') as install:
            with self.assertRaises(SetupError):
                configure_fx.main()
            install.assert_not_called()
        self.assertEqual(path.read_text(), '{"theme":"preserve"}')
        self.assertFalse((self.profile / '.config').exists())

    def test_bad_marker_is_reported_before_any_writes(self):
        (self.profile / '.bashrc').write_text(configure_fx.START + '\n')
        with self.assertRaises(SetupError):
            self.configure()
        self.assertFalse((self.profile / '.fx').exists())

    def test_key_rejects_whitespace_and_controls(self):
        for key in ['', 'key\nsecond', 'key with space', 'key\x00', 'key\t']:
            with self.assertRaises(SetupError):
                self.configure(key)
        self.assertFalse((self.profile / '.fx').exists())

    def test_unsafe_credential_mode_is_rejected(self):
        self.configure()
        path = self.profile / '.config/fx/modular-api-key'
        path.chmod(0o644)
        with self.assertRaises(SetupError):
            saved_key(self.profile)
        with self.assertRaises(SetupError):
            self.configure()

    def test_symlinked_credential_is_not_followed(self):
        target = self.profile / 'keep-me'
        target.write_text('untouched')
        path = self.profile / '.config/fx/modular-api-key'
        path.parent.mkdir(parents=True)
        path.symlink_to(target)
        with self.assertRaises(SetupError):
            self.configure()
        self.assertEqual(target.read_text(), 'untouched')

    def test_symlinked_settings_are_not_followed(self):
        target = self.profile / 'keep-me'
        target.write_text('{}')
        path = self.profile / '.fx/settings.json'
        path.parent.mkdir()
        path.symlink_to(target)
        with self.assertRaises(SetupError):
            self.configure()
        self.assertEqual(target.read_text(), '{}')

    def test_missing_fx_uses_official_release_tag_and_isolates_vendor_changes(self):
        response = MagicMock()
        response.__enter__.return_value.read.return_value = b'#!/bin/bash\n'
        binary = str(self.profile / '.local/bin/fx')
        results = [subprocess.CompletedProcess([], 0, b'', b''),
                   subprocess.CompletedProcess([], 0, '0.0.14\n', '')]
        with patch.object(configure_fx, 'fx_path', side_effect=[None, binary]), \
             patch.object(configure_fx.urllib.request, 'urlopen', return_value=response), \
             patch.object(configure_fx.subprocess, 'run', side_effect=results) as run, \
             patch.dict(os.environ, {'MODULAR_API_KEY': FIXTURE_KEY}):
            self.assertEqual(configure_fx.ensure_fx(self.profile), binary)
        installer = run.call_args_list[0]
        self.assertEqual(installer.args[0][-1], 'v0.0.14')
        env = installer.kwargs['env']
        self.assertNotIn('MODULAR_API_KEY', env)
        self.assertEqual(env['HOME'], str(self.profile))
        self.assertEqual(env['FX_INSTALL_DIR'], str(self.profile / '.local/bin'))
        self.assertEqual(env['PATH'].split(os.pathsep)[0], env['FX_INSTALL_DIR'])

    def test_existing_older_fx_is_not_silently_upgraded(self):
        with patch.object(configure_fx, 'fx_path', return_value='/example/fx'), \
             patch.object(configure_fx.subprocess, 'run', return_value=subprocess.CompletedProcess([], 0, '0.0.13', '')), \
             patch.object(configure_fx.urllib.request, 'urlopen') as download:
            with self.assertRaises(SetupError):
                configure_fx.ensure_fx(self.profile)
            download.assert_not_called()

    def test_diagnostics_redact_the_credential_and_argv_excludes_it(self):
        result = subprocess.CompletedProcess([], 1, FIXTURE_KEY, 'error ' + FIXTURE_KEY)
        with patch('fx_common.subprocess.run', return_value=result) as run:
            output = run_fx('/example/fx', ['status', '--json'], self.profile, FIXTURE_KEY)
            argv = run.call_args.args[0]
            self.assertNotIn(FIXTURE_KEY, argv)
            self.assertEqual(run.call_args.kwargs['env']['MODULAR_API_KEY'], FIXTURE_KEY)
        self.assertNotIn(FIXTURE_KEY, output.stdout + output.stderr)


if __name__ == '__main__':
    unittest.main()
