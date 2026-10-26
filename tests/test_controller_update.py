"""Upgrade compatibility and repeat-run checks without touching a board or service."""
import contextlib
import getpass
import hashlib
import importlib.util
import io
import json
from pathlib import Path
import re
import subprocess
import sys
import tempfile
import tomllib
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'install'))


def load(path):
    spec = importlib.util.spec_from_file_location(path.stem.replace('-', '_'), path)
    result = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(result)
    return result


update = load(ROOT / 'install/update-controller.py')
system = load(ROOT / 'install/system.py')
stage = load(ROOT / 'install/stage.py')
prepare_update = load(ROOT / 'install/stage-controller-update.py')


class UpdateTests(unittest.TestCase):
    def test_existing_user_animation_gets_a_versioned_project_before_activation(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);reference=root/'reference';reference.mkdir()
            for name in ('main.py','README.md'):(reference/name).write_text('new reference')
            original=root/'home/torque/projects/dot-matrix-animations';original.mkdir(parents=True)
            (original/'main.py').write_text('user code')
            project=update.example_project(reference,root/'home','0.1.0-a123')
            self.assertEqual(project.name,'dot-matrix-animations-0.1.0-a123')
            self.assertFalse(project.exists())
            self.assertEqual((original/'main.py').read_text(),'user code')

    def test_older_installer_without_readiness_helper_completes_readiness_check(self):
        with tempfile.TemporaryDirectory() as temp:
            source = Path(temp)
            (source / 'install').mkdir()
            (source / 'install/system.py').write_text(
                'import subprocess\n'
                'def run(*args, **kwargs):\n'
                '    return subprocess.CompletedProcess([], 0, stdout=\'{"device":{"ready":true}}\')\n'
                'def app(*args, **kwargs): raise AssertionError("Unexpected app operation")\n'
                'def verify_stage(*args): return {}\n'
                'def copy_release(*args): raise AssertionError("Unexpected copy")\n')
            old = update.load_system(source)
            self.assertFalse(hasattr(old, 'wait_for_ready'))
            self.assertTrue(update.wait_for_ready(old, 'fixture')['device']['ready'])

    def test_readiness_retries_bad_json_wrong_shape_and_transient_timeout(self):
        responses = [subprocess.CompletedProcess([], 1, stdout=''),
                     subprocess.CompletedProcess([], 0, stdout='[]'),
                     subprocess.CompletedProcess([], 0, stdout='{"device":null}'),
                     subprocess.TimeoutExpired('torque', 1),
                     subprocess.CompletedProcess([], 0, stdout='{"device":{"ready":false}}'),
                     subprocess.CompletedProcess([], 0, stdout='{"device":{"ready":true}}')]
        old = SimpleNamespace(run=Mock(side_effect=responses))
        with patch.object(update.time, 'sleep'):
            self.assertTrue(update.wait_for_ready(old, 'fixture')['device']['ready'])
        self.assertEqual(old.run.call_count, len(responses))
        self.assertTrue(all(c.kwargs['check'] is False for c in old.run.call_args_list))

    def test_readiness_deadline_retains_device_diagnostic(self):
        clock = [0.0]
        old = SimpleNamespace(run=Mock(return_value=subprocess.CompletedProcess(
            [], 1, stdout='{"device":{"ready":false,"error":"router unavailable"}}')))
        with patch.object(update.time, 'monotonic', side_effect=lambda: clock[0]), \
             patch.object(update.time, 'sleep', side_effect=lambda seconds: clock.__setitem__(0, clock[0] + seconds)):
            with self.assertRaisesRegex(RuntimeError, 'router unavailable'):
                update.wait_for_ready(old, 'fixture', timeout=1)
        self.assertEqual(clock[0], 1)

    def repeat_fixture(self, temp, version='0.3.0'):
        root = Path(temp)
        releases = root / 'releases'
        target = releases / '0.1.0-a123'
        target.mkdir(parents=True)
        current = root / 'current'; current.symlink_to(target)
        stage_root = root / 'stage'; (stage_root / 'release').mkdir(parents=True)
        (stage_root / 'plan.json').write_text(json.dumps(dict(release=target.name,
            previous_release=str(releases / 'old'), firmware='0.3.0', protocol=[1, 2])))
        (stage_root / 'applied.json').write_text(json.dumps({'release': target.name}))
        def run(command, **kwargs):
            if command[1:] == ['status', '--json']:
                return subprocess.CompletedProcess([], 0, stdout='{"device":{"ready":true}}')
            if '-c' in command:
                return subprocess.CompletedProcess([], 0, stdout=json.dumps(
                    dict(version=version, protocol=[1, 2], ready=True)))
            raise AssertionError('Unexpected mutation: ' + repr(command))
        old = SimpleNamespace(run=Mock(side_effect=run), app=Mock(side_effect=AssertionError('App mutation')),
                              copy_release=Mock(side_effect=AssertionError('Release mutation')))
        return stage_root, current, releases, old

    def test_sudo_repeat_checks_as_service_user_and_never_reflashes_or_restarts(self):
        with tempfile.TemporaryDirectory() as temp:
            stage_root, current, releases, old = self.repeat_fixture(temp)
            with patch.object(update, 'CURRENT', current), patch.object(update, 'RELEASES', releases), \
                 patch.object(update, 'load_system', return_value=old), \
                 patch.object(update.os, 'geteuid', return_value=0), contextlib.redirect_stdout(io.StringIO()) as output:
                self.assertEqual(update.main(['--stage', str(stage_root), '--apply', '--user', 'fixture']), 0)
            self.assertTrue(json.loads(output.getvalue())['no_flash_or_restart_repeated'])
            self.assertTrue(all(c.kwargs['user'] == 'fixture' for c in old.run.call_args_list))
            old.app.assert_not_called(); old.copy_release.assert_not_called()

    def test_repeat_rejects_a_receipt_with_wrong_live_firmware_without_mutations(self):
        with tempfile.TemporaryDirectory() as temp:
            stage_root, current, releases, old = self.repeat_fixture(temp, version='0.2.0')
            with patch.object(update, 'CURRENT', current), patch.object(update, 'RELEASES', releases), \
                 patch.object(update, 'load_system', return_value=old):
                with self.assertRaisesRegex(RuntimeError, 'does not match the live firmware'):
                    update.main(['--stage', str(stage_root), '--apply'])
            old.app.assert_not_called(); old.copy_release.assert_not_called()

    def test_missing_old_helper_is_reported_before_any_control_or_copy(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp); (root / 'release/install').mkdir(parents=True)
            (root / 'plan.json').write_text('{}')
            (root / 'release/install/system.py').write_text(
                'def run(*args, **kwargs): raise AssertionError("Unexpected control call")\n')
            with self.assertRaisesRegex(RuntimeError, 'missing required helpers'):
                update.main(['--stage', str(root), '--apply'])


class BundleTests(unittest.TestCase):
    def test_prepared_build_accepts_verified_binary_and_rejects_later_tampering(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp); (root / 'build').mkdir()
            binary = root / 'build/controller.bin'; binary.write_bytes(b'compiled firmware fixture')
            checksum = hashlib.sha256(binary.read_bytes()).hexdigest()
            manifest = dict(source_sha256='source-fixture', firmware_version=system.FIRMWARE_VERSION, profile_resolved=True,
                            artifacts={'controller.bin': checksum})
            (root / 'build.json').write_text(json.dumps(manifest))
            self.assertEqual(prepare_update.compiled_artifacts(root, 'source-fixture'), {str(binary.resolve()): checksum})
            binary.write_bytes(b'changed')
            with self.assertRaisesRegex(RuntimeError, 'artifact changed'):
                prepare_update.compiled_artifacts(root, 'source-fixture')
            manifest['source_sha256'] = 'another-source'
            (root / 'build.json').write_text(json.dumps(manifest))
            with self.assertRaisesRegex(RuntimeError, 'current pinned controller source'):
                prepare_update.compiled_artifacts(root, 'source-fixture')

    def test_isolated_compile_snapshot_matches_source_and_rejects_changed_source(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp); source = root / 'firmware/uno-q/controller/sketch'
            source.mkdir(parents=True); (source / 'sketch.ino').write_text('compiled source fixture')
            (root / 'build').mkdir(); (root / 'build/controller.bin').write_bytes(b'compiled fixture')
            fingerprint = prepare_update.firmware_hash(source.parent)
            self.assertEqual(len(prepare_update.compiled_artifacts(root, fingerprint)), 1)
            (source / 'sketch.ino').write_text('different source')
            with self.assertRaisesRegex(RuntimeError, 'differs from the successful isolated compile'):
                prepare_update.compiled_artifacts(root, fingerprint)

    def test_installer_identity_agrees_with_firmware_and_sdk_sources(self):
        cpp = (ROOT / 'firmware/uno-q/controller/sketch/src/protocol.cpp').read_text()
        firmware = re.search(r'VERSION = "([^"]+)"', cpp).group(1)
        protocol = [int(n) for n in re.search(r'\\"protocol\\":\[(\d+),(\d+)\]', cpp).groups()]
        sdk = tomllib.loads((ROOT / 'packages/device/pyproject.toml').read_text())['project']['version']
        self.assertEqual(stage.bundle_identity(), dict(firmware=firmware, protocol=protocol))
        self.assertEqual(system.bundle_identity(), stage.bundle_identity())
        self.assertEqual(firmware, sdk)

    def test_mismatched_staged_identity_is_rejected_even_when_file_hashes_match(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp); (root / 'file').write_bytes(b'valid source')
            manifest = dict(release='0.1.0-a123', firmware='0.2.0', protocol=[1, 1],
                            files={'file': hashlib.sha256(b'valid source').hexdigest()})
            (root / 'release.json').write_text(json.dumps(manifest))
            with self.assertRaisesRegex(RuntimeError, 'does not match this installer bundle'):
                system.verify_stage(root)

    def test_upgrade_from_020_requires_a_fresh_selected_bundle_identity_after_upload(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp); target, state = root / 'release', root / 'state'
            source = target / 'firmware/uno-q/controller'; source.mkdir(parents=True); state.mkdir()
            (source / 'app.yaml').write_text('name: fixture')
            identities = [dict(version='0.2.0', protocol=[1, 1], ready=True, boot_id=7),
                          dict(version=system.FIRMWARE_VERSION, protocol=list(system.FIRMWARE_PROTOCOL), ready=True, boot_id=8)]
            replies = [subprocess.CompletedProcess([], 0, stdout=json.dumps(i)) for i in identities]
            def app(command, user, timeout=120):
                return '{"apps":null}' if command[:2] == ['app', 'ps'] else '{}'
            with patch.object(system, 'run', side_effect=replies), patch.object(system, 'app', side_effect=app) as calls, \
                 patch.object(system.os, 'chown'):
                result = system.controller(target, state, getpass.getuser(), Path('/python'))
            self.assertEqual(result['identity'], identities[-1])
            self.assertEqual(sum(c.args[0][:2] == ['app', 'start'] for c in calls.call_args_list), 1)


if __name__ == '__main__':
    unittest.main()
