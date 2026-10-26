"""Activation races, durable recovery, inherited leases and unchanged inputs."""
import asyncio
import contextlib
import json
import os
from pathlib import Path
import signal
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import Mock, patch

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT/'packages/session/src'),str(ROOT/'packages/device/src')]
from torque import update
from torque.runtime import Lock, Store, read_json, write_json, pinned_python
from torque.daemon import Daemon


class FakeHost:
    def __init__(self, updater):
        self.updater = updater
        self.running = str(updater.current.resolve())
        self.epoch = 'initial'
        self.calls = []
        self.fenced = None
        self.fail_target = False

    def baseline(self):
        return {'epoch':self.epoch,'unit':{'MainPID':'123','InvocationID':'old'},
                'firmware':{'version':'0.4.0','protocol':[1,3],'boot_id':17},'retained':None}

    def control(self, action, record, **args):
        self.calls.append(action)
        if action=='fence':
            self.fenced = record['id']
            return {'epoch':self.epoch,'pid':123}
        self.updater.store.clear(record['id'])
        self.fenced = None

    def status(self):
        if not self.running:
            raise RuntimeError('Service stopped')
        return {'release_root':self.running,'epoch':self.epoch,'update_id':self.fenced}

    def check_unit(self, **kwargs):
        return {'ActiveState':'active' if self.running else 'inactive',
                'MainPID':'123' if self.running else '0','InvocationID':'old'}

    def stop(self, unit):
        self.calls.append('stop');self.running = None

    def restart(self):
        self.calls.append('restart')
        self.running = str(self.updater.current.resolve())
        self.epoch = 'new-'+str(len(self.calls))
        self.fenced = self.updater.store.pending()['id']

    def verify(self, record, target, **kwargs):
        self.calls.append('verify')
        if self.fail_target and str(target)==record['target']:
            raise RuntimeError('Wrong boot identity')
        return self.status()


class Fixture(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve()
        self.base = self.root/'installation';self.releases = self.base/'releases'
        self.old = self.releases/'0.2.0-111111111111';self.old.mkdir(parents=True)
        for name in update.APPLICATION:
            path = self.old/name
            if '.' in path.name:
                path.write_text('fixture\n')
            else:
                path.mkdir(parents=True)
        (self.old/'pyproject.toml').write_text('[project]\nversion="0.2.0"\ndependencies=["unoq-control==0.4.0"]\n[build-system]\nrequires=["setuptools>=68"]\n')
        (self.old/'install/torque_bundle.py').write_text('FIRMWARE_VERSION="0.4.0"\nFIRMWARE_PROTOCOL=(1,3)\n')
        (self.old/'packages/session/code.py').write_text('print("before")\n')
        self.deps = {'fixture':'unchanged'}
        identity = update.content_id({'application':update.input_files(self.old,update.APPLICATION),'dependencies':self.deps})
        update.manifest(self.old,{'input_id':identity,'firmware':'0.4.0','protocol':[1,3]})
        (self.base/'current').symlink_to(self.old)
        self.state = self.root/'state';self.state.mkdir(mode=0o700)
        write_json(self.state/'installed.json',{'release':self.old.name})
        self.updater = update.Updater({'state_dir':str(self.state)},base=self.base)
        self.updater.configured = Mock()
        self.host = FakeHost(self.updater);self.updater.host = self.host
        self.source = self.root/'source'
        import shutil
        shutil.copytree(self.old,self.source)
        self.stack = contextlib.ExitStack();self.addCleanup(self.stack.close)
        self.stack.enter_context(patch.object(update,'dependencies',return_value=self.deps))
        self.fresh = self.stack.enter_context(patch.object(update,'fresh_python'))
        self.smoke = self.stack.enter_context(patch.object(update,'smoke'))

    def prepared(self):
        (self.source/'packages/session/code.py').write_text('print("after")\n')
        return self.updater.prepare(self.source)


class TransactionTests(Fixture):
    def test_noop_and_examples_scope_does_not_ship_unrelated_source(self):
        self.assertTrue(self.updater.prepare(self.source)['unchanged'])
        (self.source/'packages/session/code.py').write_text('UNRELATED')
        project=self.source/'pyproject.toml'
        project.write_text(project.read_text().replace('0.4.0','0.5.0'))
        (self.source/'examples/example.txt').write_text('new example')
        record = self.updater.prepare(self.source,scope='examples')
        target = Path(record['target'])
        self.assertIn('before',(target/'packages/session/code.py').read_text())
        self.assertEqual((target/'examples/example.txt').read_text(),'new example')
        self.assertIn('0.4.0',(target/'pyproject.toml').read_text())

    def test_commit_and_repeat_do_not_restart_twice(self):
        record = self.prepared()
        result = self.updater.apply(record['id'])
        self.assertEqual(result['phase'],'committed')
        self.assertEqual(str(self.updater.current.resolve()),record['target'])
        self.assertIsNone(self.updater.store.pending())
        self.assertEqual(self.host.calls,['fence','stop','restart','verify','release'])
        self.assertTrue(self.updater.apply(record['id'])['no_restart'])
        self.assertEqual(self.host.calls.count('restart'),1)
        self.assertTrue(self.updater.prepare(self.source)['unchanged'])

    def test_startup_or_firmware_failure_restores_base(self):
        record = self.prepared();self.host.fail_target=True
        with self.assertRaisesRegex(RuntimeError,'previous runtime restored'):
            self.updater.apply(record['id'])
        self.assertEqual(self.updater.current.resolve(),self.old)
        self.assertEqual(self.updater.store.get(record['id'])['phase'],'rolled_back')
        self.assertEqual(self.host.calls.count('restart'),2)
        self.assertIsNone(self.updater.store.pending())

    def test_stale_plan_or_modified_artifact_never_stops_service(self):
        record = self.prepared()
        (Path(record['target'])/'packages/session/code.py').write_text('tampered')
        with self.assertRaisesRegex(RuntimeError,'changed after validation'):
            self.updater.apply(record['id'])
        self.assertFalse(self.host.calls)
        other = self.releases/'0.2.0-222222222222';other.mkdir()
        self.updater.current.unlink();self.updater.current.symlink_to(other)
        with self.assertRaisesRegex(RuntimeError,'stale'):
            self.updater.apply(record['id'])
        self.assertFalse(self.host.calls)

    def test_busy_admission_unwinds_without_cancelling_or_stopping(self):
        record = self.prepared()
        self.host.control = Mock(side_effect=RuntimeError('Work started'))
        with self.assertRaisesRegex(RuntimeError,'previous runtime restored'):
            self.updater.apply(record['id'])
        self.assertIsNone(self.updater.store.pending())
        self.assertFalse(self.host.calls)

    def test_recover_verified_target_finishes_without_restart(self):
        record = self.prepared();record['baseline']=self.host.baseline()
        self.updater.phase(record,'activated');self.updater.store.activate(record['id'])
        self.updater.switch(record,Path(record['target']))
        self.host.running=record['target'];self.host.epoch='after';self.host.fenced=record['id']
        self.assertEqual(self.updater.recover(record['id'])['phase'],'committed')
        self.assertNotIn('restart',self.host.calls)

    def test_interrupted_final_bookkeeping_does_not_roll_back_verified_code(self):
        record = self.prepared()
        with patch.object(self.updater,'installed',side_effect=OSError('disk full')):
            with self.assertRaisesRegex(RuntimeError,'finish bookkeeping'):
                self.updater.apply(record['id'])
        self.assertEqual(str(self.updater.current.resolve()),record['target'])
        self.assertEqual(self.updater.store.get(record['id'])['phase'],'verified')
        self.assertEqual(self.updater.recover(record['id'])['phase'],'committed')
        self.assertEqual(self.host.calls.count('restart'),1)

    def test_repeat_apply_finishes_a_committed_receipt_with_fence_still_held(self):
        record=self.prepared();original=self.host.control
        def failing_release(action,*args,**kwargs):
            if action=='release':raise RuntimeError('Lost connection before release')
            return original(action,*args,**kwargs)
        with patch.object(self.host,'control',side_effect=failing_release):
            with self.assertRaisesRegex(RuntimeError,'finish bookkeeping'):
                self.updater.apply(record['id'])
        self.assertEqual(self.updater.store.get(record['id'])['phase'],'committed')
        self.assertIsNotNone(self.updater.store.pending())
        self.assertEqual(self.updater.apply(record['id'])['phase'],'committed')
        self.assertIsNone(self.updater.store.pending())
        self.assertEqual(self.host.calls.count('restart'),1)

    def test_recovering_a_crash_before_active_pointer_does_not_restart(self):
        record=self.prepared();self.updater.phase(record,'fencing')
        self.assertEqual(self.updater.recover(record['id'])['phase'],'rolled_back')
        self.assertFalse(self.host.calls)

    def test_recovery_does_not_undo_another_activation(self):
        record=self.prepared();record['baseline']=self.host.baseline()
        self.updater.phase(record,'activated');self.updater.store.activate(record['id'])
        third=self.releases/'0.2.0-333333333333';third.mkdir()
        self.updater.current.unlink();self.updater.current.symlink_to(third)
        with self.assertRaisesRegex(RuntimeError,'different release'):
            self.updater.recover(record['id'])
        self.assertEqual(self.updater.current.resolve(),third)

    def test_dependency_or_controller_changes_are_rejected(self):
        project=self.source/'pyproject.toml'
        project.write_text(project.read_text().replace('0.4.0','0.5.0'))
        with self.assertRaisesRegex(RuntimeError,'Dependency changes'):
            self.updater.prepare(self.source)
        project.write_text((self.old/'pyproject.toml').read_text())
        (self.source/'install/torque_bundle.py').write_text('FIRMWARE_VERSION="0.5.0"\nFIRMWARE_PROTOCOL=(1,4)\n')
        with self.assertRaisesRegex(RuntimeError,'another controller'):
            self.updater.prepare(self.source)
        self.fresh.assert_not_called()

    def test_mutating_source_stays_incomplete_and_undeployable(self):
        (self.source/'packages/session/code.py').write_text('new')
        original=update.copy_inputs
        def changing(*args):
            original(*args)
            (self.source/'packages/session/code.py').write_text('changed during copy')
        with patch.object(update,'copy_inputs',side_effect=changing):
            with self.assertRaisesRegex(RuntimeError,'Source changed'):
                self.updater.prepare(self.source)
        self.assertTrue(any(p.name=='.incomplete' for p in self.releases.rglob('.incomplete')))
        self.assertFalse(self.host.calls)
        self.assertEqual(len(self.updater.gc()['removed']),1)

    def test_program_and_deploy_locks_reject_competing_work(self):
        record=self.prepared()
        with self.updater.store.use(shared=True):
            with self.assertRaisesRegex(RuntimeError,'managed program'):
                self.updater.apply(record['id'])
        with self.updater.store.lock():
            with self.assertRaisesRegex(RuntimeError,'managed program'):
                self.updater.apply(record['id'])
        self.assertFalse(self.host.calls)

    def test_sighup_unwinds_the_fence_and_restores_signal_handlers(self):
        record=self.prepared();previous=signal.getsignal(signal.SIGHUP)
        self.host.stop=Mock(side_effect=lambda _:os.kill(os.getpid(),signal.SIGHUP))
        with self.assertRaisesRegex(RuntimeError,'previous runtime restored'):
            self.updater.apply(record['id'])
        self.assertIsNone(self.updater.store.pending())
        self.assertEqual(signal.getsignal(signal.SIGHUP),previous)
        self.assertEqual(self.updater.current.resolve(),self.old)

    def test_recovery_cleans_only_its_own_interrupted_activation_link(self):
        record=self.prepared();record['baseline']=self.host.baseline()
        self.updater.phase(record,'activating');self.updater.store.activate(record['id'])
        temporary=self.base/('.update-'+record['id']);temporary.symlink_to(record['target'])
        self.assertEqual(self.updater.recover(record['id'])['phase'],'rolled_back')
        self.assertFalse(temporary.is_symlink())

    def test_failed_service_with_no_process_can_roll_back_without_a_signal(self):
        record=self.prepared();record['baseline']=self.host.baseline()
        self.updater.phase(record,'activated');self.updater.store.activate(record['id'])
        self.updater.switch(record,Path(record['target']));self.host.running=None
        self.host.check_unit=Mock(return_value={'ActiveState':'failed','MainPID':'0'})
        self.assertEqual(self.updater.recover(record['id'])['phase'],'rolled_back')
        self.assertNotIn('stop',self.host.calls)

    def test_source_link_escape_is_refused_before_building(self):
        outside=self.root/'not-a-source';outside.write_text('outside')
        (self.source/'examples/escape.py').symlink_to(outside)
        with self.assertRaisesRegex(RuntimeError,'escapes'):
            self.updater.prepare(self.source)
        self.fresh.assert_not_called();self.assertFalse(self.host.calls)

    def test_gc_keeps_current_rollback_and_live_release_leases(self):
        record=self.prepared();self.updater.apply(record['id'])
        orphan=self.releases/'0.2.0-444444444444';orphan.mkdir()
        update.manifest(orphan,{'firmware':'0.4.0','protocol':[1,3]})
        with self.updater.store.release_use(orphan.name):
            self.assertIn(orphan.name,self.updater.gc()['skipped'])
        self.assertIn(orphan.name,self.updater.gc()['removed'])
        self.assertTrue(self.old.exists())
        self.assertTrue(Path(record['target']).exists())


class LeaseTests(unittest.TestCase):
    def test_child_interpreter_uses_the_imported_release_after_current_changes(self):
        with patch('torque.runtime.managed_release',return_value=Path('/opt/torque/releases/0.2.0-111111111111')):
            with patch('torque.runtime.sys.prefix','/opt/torque/current/runtime/python'):
                self.assertEqual(pinned_python(),'/opt/torque/releases/0.2.0-111111111111/runtime/python/bin/python')

    def test_inherited_lock_survives_frontend_closing_its_descriptor(self):
        with tempfile.TemporaryDirectory() as temp:
            path=Path(temp)/'use.lock'
            with Lock(path,shared=True) as lease:
                child=subprocess.Popen([sys.executable,'-c','import time;time.sleep(30)'],pass_fds=(lease.fd,))
            try:
                with self.assertRaisesRegex(RuntimeError,'managed program'):
                    with Lock(path):pass
            finally:
                child.terminate();child.wait(timeout=5)
            with Lock(path):pass

    def test_private_records_reject_links_permissions_and_bad_identities(self):
        with tempfile.TemporaryDirectory() as temp:
            store=Store(Path(temp))
            with self.assertRaises(ValueError):store.get('../escape')
            path=store.root/'unsafe';path.write_text('{}');path.chmod(0o644)
            with self.assertRaisesRegex(RuntimeError,'private owned'):read_json(path)
            link=store.root/'link';link.symlink_to(path)
            with self.assertRaises(OSError):read_json(link)
            with self.assertRaises(OSError):
                with Lock(link):pass


class FakeDevice:
    def __init__(self,*args):self.maintenance=False;self.owner=None
    def status(self):return {'ready':True,'owner':self.owner}
    def set_maintenance(self,value):self.maintenance=value
    def fence_update(self):
        if self.owner:raise RuntimeError('Device busy')
        self.maintenance=True


class FenceTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name);key=self.root/'key';key.write_text('PRIVATE-FIXTURE');key.chmod(0o600)
        self.config={'release_root':str(ROOT),'workspace':str(self.root),'state_dir':str(self.root/'state'),
                     'key_file':str(key),'python':sys.executable,'model':'fixture'}
        self.daemon=Daemon(self.config,device_factory=FakeDevice)
        self.record={'id':'a'*32,'phase':'fencing','base':str(ROOT),'target':'candidate'}
        self.daemon.updates.save(self.record);self.daemon.updates.activate(self.record['id'])

    async def fence(self):
        return await self.daemon.request('updater',{'v':1,'op':'update','action':'fence',
            'update_id':self.record['id'],'expected_release':str(ROOT)})

    async def test_fence_blocks_mutations_survives_restart_and_releases_by_owner(self):
        state=await self.fence();self.assertEqual(state['update_id'],self.record['id'])
        self.assertTrue(self.daemon.device.maintenance)
        for request in ({'op':'prompt','prompt':'never run'},{'op':'reset','blank':False},
                        {'op':'cancel'},{'op':'model','action':'use','model_id':'fixture'}):
            with self.assertRaises(RuntimeError):await self.daemon.request('client',{'v':1,**request})
        restarted=Daemon(self.config,device_factory=FakeDevice)
        self.assertEqual(restarted.maintenance,'runtime-update')
        self.assertTrue(restarted.device.maintenance)
        with self.assertRaises(RuntimeError):
            await restarted.update_control({'action':'release','update_id':'b'*32})
        await restarted.update_control({'action':'release','update_id':self.record['id']})
        self.assertIsNone(restarted.maintenance);self.assertFalse(restarted.device.maintenance)

    async def test_busy_controls_tools_and_device_owner_refuse_fence(self):
        for field,value in (('turn_active',True),('cancelling',True),('pending',{'id':{}}),('maintenance','reset')):
            with self.subTest(field=field):
                old=getattr(self.daemon,field);setattr(self.daemon,field,value)
                with self.assertRaisesRegex(RuntimeError,'active'):await self.fence()
                setattr(self.daemon,field,old)
        task=asyncio.create_task(asyncio.sleep(30));self.daemon.tool_tasks.add(task)
        with self.assertRaisesRegex(RuntimeError,'active'):await self.fence()
        task.cancel();await asyncio.gather(task,return_exceptions=True);self.daemon.tool_tasks.clear()
        self.daemon.device.owner='project'
        with self.assertRaisesRegex(RuntimeError,'busy'):await self.fence()
        self.assertIsNone(self.daemon.maintenance)

    async def test_process_paths_are_pinned_without_rewriting_persisted_settings(self):
        link=self.root/'current';link.symlink_to(ROOT,target_is_directory=True)
        config={**self.config,'release_root':str(link),'python':str(link/'runtime/python/bin/python'),
                'node':str(link/'runtime/node/bin/node'),'libfx_path':str(link/'node_modules/libfx')}
        daemon=Daemon(config,device_factory=FakeDevice)
        self.assertEqual(daemon.config['python'],str(ROOT/'runtime/python/bin/python'))
        self.assertEqual(config['release_root'],str(link))


if __name__=='__main__':unittest.main()
