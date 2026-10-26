"""Linux-only release activation preserves the MCU and never starts Arduino apps."""
import contextlib
import importlib.util
import io
import json
from pathlib import Path
import subprocess
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

ROOT=Path(__file__).resolve().parents[1]
spec=importlib.util.spec_from_file_location('update_runtime',ROOT/'install/update-runtime.py')
runtime=importlib.util.module_from_spec(spec);spec.loader.exec_module(runtime)


class RuntimeUpdateTests(unittest.TestCase):
    def fixture(self, root):
        releases=root/'releases';old=releases/'0.1.0-old';old.mkdir(parents=True)
        current=root/'current';current.symlink_to(old)
        stage=root/'stage';(stage/'release').mkdir(parents=True)
        state=root/'state';state.mkdir();(state/'installed.json').write_text(json.dumps({'release':old.name}))
        unit=root/'service';unit.write_text('unchanged service fixture')
        identity=dict(name='base-controller',version='0.4.0',protocol=[1,3],boot_id=99,ready=True)
        plan=dict(kind='runtime-only',release='0.2.0-new',previous_release=str(old.resolve()),firmware='0.4.0',protocol=[1,3])
        (stage/'plan.json').write_text(json.dumps(plan))
        manifest=dict(release=plan['release'],firmware=plan['firmware'],protocol=plan['protocol'])
        calls=[]
        def run(command, **kwargs):
            calls.append(command)
            if command[1:] == ['status','--json']:
                output=json.dumps(dict(active=False,pending=[],device=dict(ready=True,owner=None)))
            elif command[:3] == ['arduino-app-cli','properties','get']:
                output=json.dumps({'app':{'FullPath':'/stable/controller'}})
            elif command[0]=='systemctl':output=''
            elif '-I' in command:output='{}'
            else:raise AssertionError('Unexpected command: '+repr(command))
            return subprocess.CompletedProcess(command,0,stdout=output)
        def copy_release(source,target,metadata):
            target.mkdir();(target/'release.json').write_text(json.dumps(metadata))
        system=SimpleNamespace(run=Mock(side_effect=run),verify_stage=Mock(return_value=manifest),
                               copy_release=Mock(side_effect=copy_release))
        support=SimpleNamespace(load_system=lambda source:system,wait_for_ready=Mock(return_value={'device':{'ready':True}}))
        return SimpleNamespace(releases=releases,old=old,current=current,stage=stage,state=state,unit=unit,
                               identity=identity,plan=plan,calls=calls,system=system,support=support)

    def patches(self,f):
        stack=contextlib.ExitStack()
        original_exists=Path.exists
        def exists(path):
            return False if str(path)=='/etc/torque-runtime-updates.json' else original_exists(path)
        stack.enter_context(patch.object(runtime.Path,'exists',autospec=True,side_effect=exists))
        for name,value in [('CURRENT',f.current),('RELEASES',f.releases),('STATE',f.state),('SERVICE_UNIT',f.unit)]:
            stack.enter_context(patch.object(runtime,name,value))
        stack.enter_context(patch.object(runtime,'support',return_value=f.support))
        stack.enter_context(patch.object(runtime.os,'geteuid',return_value=0))
        stack.enter_context(patch.object(runtime.os,'umask'))
        stack.enter_context(patch.object(runtime.os,'chown'))
        stack.enter_context(patch.object(runtime.pwd,'getpwnam',return_value=SimpleNamespace(pw_uid=1000,pw_gid=1000)))
        stack.enter_context(contextlib.redirect_stdout(io.StringIO()))
        return stack

    def test_enabled_layout_refuses_legacy_helper_before_loading_or_mutating(self):
        with tempfile.TemporaryDirectory() as temp:
            f=self.fixture(Path(temp))
            with patch.object(runtime.Path,'exists',return_value=True),patch.object(runtime,'support') as support:
                with self.assertRaisesRegex(RuntimeError,'use torque update'):
                    runtime.apply(f.stage,'fixture',True)
                support.assert_not_called()

    def test_activation_changes_only_runtime_and_repeat_does_not_restart(self):
        with tempfile.TemporaryDirectory() as temp:
            f=self.fixture(Path(temp))
            with self.patches(f),patch.object(runtime,'probe',return_value=f.identity):
                self.assertEqual(runtime.apply(f.stage,'fixture',True),0)
                self.assertEqual(f.current.resolve(),(f.releases/f.plan['release']).resolve())
                self.assertEqual(runtime.apply(f.stage,'fixture',True),0)
            report=json.loads((f.stage/'applied.json').read_text())
            self.assertTrue(report['firmware_boot_unchanged'])
            self.assertFalse(report['firmware_upload'])
            self.assertEqual([c for c in f.calls if c[0]=='systemctl'],
                             [['systemctl','stop','torque.service'],['systemctl','start','torque.service']])
            self.assertFalse(any(c[:2]==['arduino-app-cli','app'] for c in f.calls))
            self.assertFalse(any(c[:3]==['arduino-app-cli','properties','set'] for c in f.calls))

    def test_unexpected_mcu_change_rolls_back_runtime_without_flashing(self):
        with tempfile.TemporaryDirectory() as temp:
            f=self.fixture(Path(temp));changed={**f.identity,'boot_id':100}
            with self.patches(f),patch.object(runtime,'probe',side_effect=[f.identity,changed]):
                with self.assertRaisesRegex(RuntimeError,'MCU identity changed'):
                    runtime.apply(f.stage,'fixture',True)
            self.assertEqual(f.current.resolve(),f.old.resolve())
            self.assertFalse((f.stage/'applied.json').exists())
            self.assertFalse(any(c[:2]==['arduino-app-cli','app'] for c in f.calls))

    def test_preflight_does_not_stop_services_or_copy_a_release(self):
        with tempfile.TemporaryDirectory() as temp:
            f=self.fixture(Path(temp))
            with self.patches(f),patch.object(runtime,'probe',return_value=f.identity):
                self.assertEqual(runtime.apply(f.stage,'fixture',False),0)
            self.assertEqual(f.current.resolve(),f.old.resolve())
            f.system.copy_release.assert_not_called()
            self.assertFalse(any(c[0]=='systemctl' for c in f.calls))

    def test_mismatched_installed_wheel_is_rejected_before_activation(self):
        with tempfile.TemporaryDirectory() as temp:
            f=self.fixture(Path(temp))
            original=f.system.run.side_effect
            def run(command,**kwargs):
                if '-I' in command:
                    raise RuntimeError('Installed Python modules differ from source: protocol.py')
                return original(command,**kwargs)
            f.system.run.side_effect=run
            with self.patches(f):
                with self.assertRaisesRegex(RuntimeError,'protocol.py'):
                    runtime.apply(f.stage,'fixture',True)
            f.system.copy_release.assert_not_called()
            self.assertFalse(any(c[0]=='systemctl' for c in f.calls))


if __name__=='__main__':unittest.main()
