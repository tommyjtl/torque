"""The administrator helper uses no-follow descriptors and one exact sudo rule."""
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import sys
import signal
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT/'packages/session/src'),str(ROOT/'packages/device/src')]
from torque import update
spec=importlib.util.spec_from_file_location('runtime_bootstrap',ROOT/'install/bootstrap-runtime-updates.py')
bootstrap=importlib.util.module_from_spec(spec);spec.loader.exec_module(bootstrap)


class BootstrapTests(unittest.TestCase):
    def setUp(self):
        previous=os.umask(0o022);self.addCleanup(os.umask,previous)
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name).resolve()
        self.release=self.root/'0.2.0-123456789abc';self.release.mkdir()
        self.account=SimpleNamespace(pw_name='arduino',pw_uid=os.getuid(),pw_gid=os.getgid(),pw_dir=str(self.root))
        (self.release/'file').write_text('managed content')
        self.metadata={'release':self.release.name,'files':{'file':bootstrap.sha(self.release/'file')},'links':{}}
        self.save()

    def save(self):
        (self.release/'release.json').write_text(json.dumps(self.metadata))

    def test_valid_graph_and_unknown_or_changed_files(self):
        self.assertEqual(bootstrap.validate_tree(self.release,self.account),self.metadata)
        (self.release/'extra').write_text('unknown')
        with self.assertRaisesRegex(RuntimeError,'hashes/links differ'):
            bootstrap.validate_tree(self.release,self.account)
        (self.release/'extra').unlink();(self.release/'file').write_text('modified')
        with self.assertRaisesRegex(RuntimeError,'hashes/links differ'):
            bootstrap.validate_tree(self.release,self.account)

    def test_external_links_are_rejected_without_following_them(self):
        outside=self.root/'outside';outside.write_text('not part of the release')
        (self.release/'escape').symlink_to(outside)
        self.metadata['links']['escape']=str(outside);self.save()
        with self.assertRaisesRegex(RuntimeError,'escapes'):
            bootstrap.validate_tree(self.release,self.account)

    def test_python_system_link_is_checked_but_ownership_transfer_never_follows_it(self):
        directory=self.release/'runtime/python/bin';directory.mkdir(parents=True)
        (directory/'python3').symlink_to('/usr/bin/python3.13')
        self.metadata['links']['runtime/python/bin/python3']='/usr/bin/python3.13';self.save()
        bootstrap.validate_tree(self.release,self.account)
        touched=[]
        def chown(fd,*args):touched.append(os.fstat(fd).st_ino)
        with patch.object(bootstrap.os,'fchown',side_effect=chown):
            bootstrap.transfer(self.release,self.account)
        self.assertNotIn((directory/'python3').lstat().st_ino,touched)
        self.assertIn((self.release/'file').stat().st_ino,touched)

    def test_manifest_symlinks_hardlinks_and_writable_entries_are_rejected(self):
        manifest=self.release/'release.json';outside=self.root/'outside.json'
        outside.write_bytes(manifest.read_bytes());manifest.unlink();manifest.symlink_to(outside)
        with self.assertRaises(OSError):bootstrap.validate_tree(self.release,self.account)
        manifest.unlink();self.save()
        os.link(self.release/'file',self.root/'hardlink')
        with self.assertRaisesRegex(RuntimeError,'Hardlinked'):
            bootstrap.validate_tree(self.release,self.account)
        (self.root/'hardlink').unlink();(self.release/'file').chmod(0o666)
        with self.assertRaisesRegex(RuntimeError,'writable'):
            bootstrap.validate_tree(self.release,self.account)

    def test_fifo_manifest_is_refused_without_waiting_for_a_writer(self):
        manifest=self.release/'release.json';manifest.unlink();os.mkfifo(manifest,0o600)
        with self.assertRaisesRegex(RuntimeError,'regular file'):
            bootstrap.validate_tree(self.release,self.account)

    def test_fixed_rule_has_no_shell_python_other_unit_or_wildcard_authority(self):
        rule=bootstrap.policy_text(self.account)
        self.assertEqual(rule,'arduino ALL=(root) NOPASSWD: /usr/bin/systemctl restart torque.service\n')
        with self.assertRaisesRegex(RuntimeError,'account'):
            bootstrap.policy_text(SimpleNamespace(pw_name='arduino ALL'))

    def test_global_policy_checks_syntax_and_safe_ownership_without_chmod_vendor_files(self):
        output='/etc/sudoers: parsed OK\n/etc/sudoers.d/10-arduino-passwd: parsed OK\n'
        with patch.object(bootstrap,'run',return_value=output) as run, \
             patch.object(bootstrap,'root_file') as owned,patch.object(bootstrap.os,'chmod') as chmod:
            self.assertEqual(len(bootstrap.validate_policy()),2)
        run.assert_called_once_with(['/usr/sbin/visudo','-cf','/etc/sudoers'])
        self.assertEqual(owned.call_count,2);chmod.assert_not_called()

    def test_service_prefixes_and_extra_hooks_are_refused(self):
        good='[Service]\nUser=arduino\nExecStart=/opt/torque/current/runtime/python/bin/python -m torque.daemon\n'
        self.assertTrue(update.safe_unit_source(good))
        for bad in (good.replace('ExecStart=','ExecStart=+'),good+'ExecStartPre=/tmp/payload\n',
                    good+'ExecCondition=+/tmp/payload\n','.include /tmp/other\n'+good):
            self.assertFalse(update.safe_unit_source(bad))

    def test_delegation_check_rejects_service_context_and_general_cached_sudo(self):
        host=update.Host(Mock())
        host.run=Mock(return_value='(ALL : ALL) ALL\n')
        with patch.object(update.Path,'read_text',return_value='NoNewPrivs:\t1\n'):
            with self.assertRaisesRegex(RuntimeError,'outside torque.service'):host.check_delegation()
        host.run.assert_not_called()
        with patch.object(update.Path,'read_text',return_value='NoNewPrivs:\t0\n'):
            with self.assertRaisesRegex(RuntimeError,'exact password-free'):host.check_delegation()
            host.run.return_value='    (root) NOPASSWD: /usr/bin/systemctl restart torque.service\n'
            host.check_delegation()

    def test_routine_updater_refuses_root_before_any_privileged_action(self):
        with patch.object(update.os,'geteuid',return_value=0):
            with self.assertRaisesRegex(RuntimeError,'never sudo'):
                update.Updater.normal_user(Mock())


class HostTests(unittest.TestCase):
    def test_pid_or_invocation_change_prevents_signaling(self):
        host=update.Host(Mock())
        expected={'MainPID':'123','InvocationID':'old','ActiveState':'active'}
        host.check_unit=Mock(return_value={**expected,'InvocationID':'different'})
        with patch.object(update.os,'pidfd_open',create=True) as opened:
            with self.assertRaisesRegex(RuntimeError,'changed before shutdown'):host.stop(expected)
            opened.assert_not_called()

    def test_pidfd_checks_uid_control_group_and_invocation_before_sigterm(self):
        host=update.Host(Mock())
        expected={'MainPID':'123','InvocationID':'old','ActiveState':'active'}
        host.check_unit=Mock(return_value=expected)
        host.unit=Mock(side_effect=[expected,{'MainPID':'0','ActiveState':'inactive'}])
        def proc(path,*args,**kwargs):
            return 'Uid:\t'+str(os.getuid())+'\n' if path.name=='status' else '0::/system.slice/torque.service\n'
        with patch.object(update.os,'pidfd_open',return_value=987,create=True), \
             patch.object(update.signal,'pidfd_send_signal',create=True) as sent, \
             patch.object(update.Path,'read_text',autospec=True,side_effect=proc), \
             patch.object(update.select,'select',return_value=([987],[],[])),patch.object(update.os,'close'):
            host.stop(expected)
            sent.assert_called_once_with(987,signal.SIGTERM)

    def test_start_limit_retry_uses_only_the_exact_restart_command(self):
        host=update.Host(Mock())
        host.run=Mock(side_effect=[RuntimeError('start limit'),'Result=start-limit-hit\nStartLimitIntervalUSec=10s\n',''])
        with patch.object(update.time,'sleep') as sleep:host.restart()
        sleep.assert_called_once_with(11)
        self.assertEqual(host.run.call_args_list[0].args[0],update.RESTART)
        self.assertEqual(host.run.call_args_list[-1].args[0],update.RESTART)

    def test_readiness_rejects_another_release_or_same_daemon_epoch(self):
        with tempfile.TemporaryDirectory() as temp:
            target=Path(temp);(target/'pyproject.toml').write_text('[project]\nversion="0.2.0"\n')
            correct={'release_root':str(target),'release_id':target.name,'application_version':'0.2.0',
                     'update_protocol':1,'device':{'ready':True},'epoch':'new','pid':123}
            host=update.Host(Mock());host.status=Mock(side_effect=[{**correct,'release_root':'wrong'},
                         {**correct,'epoch':'old'},{**correct,'application_version':'wrong'},correct])
            with patch.object(update.time,'sleep'):
                self.assertEqual(host.ready(target,old_epoch='old'),correct)
            self.assertEqual(host.status.call_count,4)

    def test_retained_output_and_boot_are_verified_without_replaying_writes(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);unit=root/'unit';unit.write_text('root unit fixture')
            config=root/'settings';config.write_text('{}')
            host=update.Host(SimpleNamespace(config_path=config))
            firmware={'version':'0.4.0','boot_id':17}
            retained={'boot_id':17,'frame_hex':'00'*13}
            before={'epoch':'old','unit':{'InvocationID':'old'},'unit_sha256':update.digest(unit),
                    'settings_sha256':update.digest(config),'default':'controller','firmware':firmware,
                    'session_id':'same','model':'same/model','permission_mode':'auto','credential_ready':True,
                    'retained':retained}
            state={'pid':123,'session_id':'same','model':'same/model','default_permission_mode':'auto',
                   'credential_ready':True,'device':{'retained_matrix':retained,
                   'snapshot':{'matrix':{'frame_hex':'00'*13,'playing':False}}}}
            host.ready=Mock(return_value=state);host.check_unit=Mock(return_value={'MainPID':'123','InvocationID':'new'})
            host.default_app=Mock(return_value='controller');host.firmware=Mock(return_value=firmware)
            host.control=Mock()
            with patch.object(update,'UNIT',unit):
                host.verify({'baseline':before},root)
                state['device']['snapshot']['matrix']['playing']=True
                with self.assertRaisesRegex(RuntimeError,'Retained output'):host.verify({'baseline':before},root)
                host.firmware.return_value={**firmware,'boot_id':18}
                with self.assertRaisesRegex(RuntimeError,'Firmware'):host.verify({'baseline':before},root)
            host.control.assert_not_called()


if __name__=='__main__':unittest.main()
