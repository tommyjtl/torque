import importlib.util
import base64
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts'))
sys.path.insert(0, str(ROOT / 'packages/device/src'))
import controller_common


def load_script(name):
    spec = importlib.util.spec_from_file_location(name.replace('-', '_'), ROOT / 'scripts' / (name + '.py'))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


prepare = load_script('prepare-controller')
flash = load_script('flash-controller')
verify = load_script('verify-controller')


class ControllerToolTests(unittest.TestCase):
    def test_interrupted_output_verification_requests_cleanup_and_reports_interruption(self):
        import unoq_control
        calls = []
        class TestBoard:
            matrix = type('Matrix',(),{'clear':lambda self:calls.append('clear')})()
            def __enter__(self):return self
            def __exit__(self,*args):pass
            def info(self):return {'version':'0.2.0'}
            def snapshot(self):return {}
            def health(self):return {}
            def rgb(self,led):
                return type('Rgb',(),{'set':lambda self,*value:calls.append((led,value))})()
        with tempfile.TemporaryDirectory() as temp:
            report = Path(temp)/'report.json'
            with patch.object(verify,'require_board'), patch.object(unoq_control,'Board',TestBoard), \
                 patch.object(verify,'exercise',side_effect=KeyboardInterrupt):
                self.assertEqual(verify.main(['--exercise-outputs','--report',str(report)]),130)
            self.assertEqual(calls,['clear',(3,(False,False,False)),(4,(False,False,False))])
            self.assertEqual(json.loads(report.read_text())['result'],'interrupted')

    def test_default_controller_verification_is_read_only(self):
        import unoq_control
        class ReadOnlyBoard:
            def __enter__(self):return self
            def __exit__(self,*args):pass
            def info(self):return {'version':'0.2.0'}
            def snapshot(self):return {'source':'test'}
            def health(self):return {'observer_active':False}
        with tempfile.TemporaryDirectory() as temp:
            report = Path(temp)/'report.json'
            with patch.object(verify,'require_board'), patch.object(unoq_control,'Board',ReadOnlyBoard), \
                 patch.object(verify,'exercise') as actuate:
                self.assertEqual(verify.main(['--report',str(report)]),0)
                actuate.assert_not_called()
            data = json.loads(report.read_text())
            self.assertFalse(data['exercised_outputs'])
            self.assertEqual(data['result'],'passed')

    def test_build_outputs_do_not_change_the_source_fingerprint(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            (root / 'sketch').mkdir()
            source = root / 'sketch/sketch.ino'
            source.write_text('void loop() {}')
            with patch.object(controller_common, 'FIRMWARE', root):
                first = controller_common.source_hash()
                (root / '.cache').mkdir()
                (root / '.cache/generated.cpp').write_text('generated artifact')
                self.assertEqual(first, controller_common.source_hash())
                source.write_text('void loop() { updateController(); }')
                self.assertNotEqual(first, controller_common.source_hash())

    def test_flash_requires_explicit_replacement_option(self):
        with patch.object(flash, 'require_board') as board, self.assertRaises(SystemExit) as result:
            flash.main([])
        self.assertEqual(result.exception.code, 2)
        board.assert_not_called()

    def preflight(self, temp, fingerprint):
        cache = Path(temp)
        (cache / 'build.json').write_text(json.dumps({'source_sha256': fingerprint, 'profile_resolved': True,
                                                     'firmware_version': flash.firmware_version()}))
        (cache / 'venv/bin').mkdir(parents=True)
        (cache / 'venv/bin/unoq-control').touch()
        return cache

    def test_denied_router_access_stops_before_app_start(self):
        with tempfile.TemporaryDirectory() as temp:
            cache = self.preflight(temp, 'source')
            with patch.object(flash, 'CACHE', cache), patch.object(flash, 'source_hash', return_value='source'), \
                 patch.object(flash, 'require_board'), patch.object(flash.shutil, 'which', return_value='/usr/bin/arduino-app-cli'), \
                 patch.object(flash.os, 'access', return_value=False), patch.object(flash.subprocess, 'run') as run:
                self.assertEqual(flash.main(['--replace-firmware', '--venv', str(cache / 'venv')]), 1)
                run.assert_not_called()

    def test_changed_source_stops_before_any_deployment_command(self):
        with tempfile.TemporaryDirectory() as temp:
            cache = self.preflight(temp, 'old-source')
            with patch.object(flash, 'CACHE', cache), patch.object(flash, 'source_hash', return_value='new-source'), \
                 patch.object(flash, 'require_board'), patch.object(flash.shutil, 'which', return_value='/usr/bin/arduino-app-cli'), \
                 patch.object(flash.subprocess, 'run') as run:
                self.assertEqual(flash.main(['--replace-firmware', '--venv', str(cache / 'venv')]), 1)
                run.assert_not_called()

    def test_failed_compile_removes_previous_deployable_manifest(self):
        with tempfile.TemporaryDirectory() as temp:
            cache = self.preflight(temp, 'old-source')
            with patch.object(prepare, 'CACHE', cache), patch.object(prepare, 'source_hash', return_value='source'), \
                 patch.object(prepare, 'require_board'), patch.object(prepare.shutil, 'which', return_value='/usr/bin/arduino-cli'), \
                 patch.object(prepare.subprocess, 'run', side_effect=subprocess.CalledProcessError(1, ['compile'])):
                self.assertEqual(prepare.main(['--resolve']), 1)
                self.assertFalse((cache / 'build.json').exists())

    def test_client_install_rejects_a_system_python_destination(self):
        with tempfile.TemporaryDirectory() as temp:
            destination = Path(temp)
            (destination / 'bin').mkdir()
            (destination / 'bin/python').touch()
            result = subprocess.CompletedProcess([], 1)
            with patch.object(prepare.subprocess, 'run', return_value=result) as run, \
                 patch.object(prepare.urllib.request, 'urlopen') as download:
                with self.assertRaisesRegex(RuntimeError, 'virtual environment'):
                    prepare.install_client(destination)
                self.assertEqual(run.call_count, 1)
                download.assert_not_called()

    def test_deploy_waits_for_stop_and_requires_expected_firmware_version(self):
        with tempfile.TemporaryDirectory() as temp:
            cache = self.preflight(temp, 'source')
            calls = []
            ps_calls = 0
            target_id = base64.urlsafe_b64encode(str(flash.FIRMWARE.resolve()).encode()).decode().rstrip('=')
            def run(command, **options):
                nonlocal ps_calls
                calls.append(command)
                if command[0] == 'arduino-app-cli':
                    if command[2] == 'ps':
                        ps_calls += 1
                        apps = [{'id':target_id,'status':'running' if ps_calls==1 else 'stopping'}] if ps_calls<3 else []
                        return subprocess.CompletedProcess(command,0,stdout=json.dumps({'apps':apps}),stderr='')
                    return subprocess.CompletedProcess(command, 0, stdout='', stderr='')
                return subprocess.CompletedProcess(command, 0, stdout=json.dumps({'name':'base-controller','version':'0.0.0','ready':True}), stderr='')
            with patch.object(flash,'CACHE',cache), patch.object(flash,'source_hash',return_value='source'), \
                 patch.object(flash,'require_board'), patch.object(flash.shutil,'which',return_value='/usr/bin/arduino-app-cli'), \
                 patch.object(flash.os,'access',return_value=True), patch.object(flash.subprocess,'run',side_effect=run), \
                 patch.object(flash.time,'sleep'):
                self.assertEqual(flash.main(['--replace-firmware','--venv',str(cache/'venv')]),1)
            stop_index = next(i for i,c in enumerate(calls) if c[:3]==['arduino-app-cli','app','stop'])
            start_index = next(i for i,c in enumerate(calls) if c[:3]==['arduino-app-cli','app','start'])
            self.assertGreater(start_index,stop_index+2)
            self.assertEqual(ps_calls,3)


if __name__ == '__main__':
    unittest.main()
