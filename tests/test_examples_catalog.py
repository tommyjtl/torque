"""Manifest discovery, safe entrypoints and argument forwarding without hardware."""
import contextlib
import io
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import Mock, patch

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT/'packages/session/src'), str(ROOT/'packages/device/src')]
from torque import cli, examples


def fixture(root, directory='01-test', slug='test', args=(), requires=()):
    path=root/directory;path.mkdir(parents=True)
    (path/'main.py').write_text('import sys\nprint(sys.argv[1:])\n')
    manifest=path/'example.toml'
    manifest.write_text('schema_version = 1\nslug = '+json.dumps(slug)+'\n'
        'title = "Test example"\ndescription = "Fixture only"\nentrypoint = "main.py"\n'
        '[modes.run]\nargs = '+json.dumps(list(args))+'\nrequires = '+json.dumps(list(requires))+'\n'
        '[modes.preview]\nargs = []\nrequires = []\n')
    return manifest


class CatalogTests(unittest.TestCase):
    def test_builtin_catalog_has_six_python_examples_and_excludes_replacement_sketch(self):
        catalog=examples.discover(ROOT/'examples')
        self.assertTrue({'linux-rgb-led','mcu-rgb-led','matrix-patterns',
                         'matrix-animation','state-observer','dot-matrix-animations'}.issubset(catalog))
        self.assertNotIn('idle-sketch',catalog)
        gallery=catalog['dot-matrix-animations']
        self.assertEqual(gallery.modes['run'].args,('--play','--output-dir','{output_dir}'))
        self.assertEqual(gallery.modes['preview'].requires,())

    def test_new_folder_is_discovered_without_editing_python_or_an_index(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);fixture(root)
            self.assertEqual(list(examples.discover(root)),['test'])
            fixture(root,'99-another','another',args=['--custom-new-flag','value'])
            self.assertEqual(list(examples.discover(root)),['test','another'])
            self.assertEqual(examples.discover(root)['another'].modes['run'].args,('--custom-new-flag','value'))

    def test_duplicate_slugs_are_rejected(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);fixture(root);fixture(root,'02-second')
            with self.assertRaisesRegex(ValueError,'Duplicate example slug'):examples.discover(root)

    def test_malformed_schema_modes_and_argument_templates_are_rejected(self):
        changes=[('schema_version = 1','schema_version = true'),('slug = "test"','slug = "../test"'),
                 ('[modes.run]','[modes.other]'),('args = []','args = "--flag"'),
                 ('requires = []','requires = "daemon"'),('args = []','args = ["{unknown}"]'),
                 ('args = []','args = ["{workspace!r}"]'),('args = []','args = ["{output_dir:>20}"]'),
                 ('description = "Fixture only"','description = "Fixture only"\ncommand = "shell"')]
        with tempfile.TemporaryDirectory() as temp:
            path=fixture(Path(temp));original=path.read_text()
            for before,after in changes:
                with self.subTest(after=after):
                    path.write_text(original.replace(before,after,1))
                    with self.assertRaises(ValueError):examples.read_manifest(path)

    def test_missing_escaping_and_symlinked_entrypoints_are_rejected(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);path=fixture(root);original=path.read_text()
            outside=root/'outside.py';outside.write_text('raise AssertionError("not executed")')
            for entry in ('../outside.py',str(outside),'missing.py'):
                path.write_text(original.replace('entrypoint = "main.py"','entrypoint = '+json.dumps(entry)))
                with self.assertRaises(ValueError):examples.read_manifest(path)
            path.write_text(original)
            (path.parent/'main.py').unlink();(path.parent/'main.py').symlink_to(outside)
            with self.assertRaises(ValueError):examples.read_manifest(path)

    def test_build_resources_include_local_helpers_and_assets_but_reject_escape(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);path=fixture(root)
            (path.parent/'asset.csv').write_text('data')
            (path.parent/'helper.py').write_text('value=1')
            (path.parent/'__pycache__').mkdir();(path.parent/'__pycache__/ignored.pyc').write_bytes(b'cache')
            (path.parent/'.env').write_text('not bundled')
            entry=examples.read_manifest(path)
            names={p.name for p in examples.resource_files(entry)}
            self.assertEqual(names,{'main.py','example.toml','helper.py','asset.csv'})
            outside=root/'outside.txt';outside.write_text('outside')
            (path.parent/'escape.txt').symlink_to(outside)
            with self.assertRaisesRegex(ValueError,'outside its directory'):list(examples.resource_files(entry))


class LaunchTests(unittest.TestCase):
    def test_defaults_precede_forwarded_arguments_and_outputs_stay_in_workspace(self):
        with tempfile.TemporaryDirectory(prefix='torque catalog ') as temp:
            root=Path(temp)/'catalog';fixture(root,args=['--value','default','--output','{output_dir}'])
            workspace=Path(temp)/'workspace with spaces'
            with patch.object(examples.subprocess,'call',return_value=7) as call, \
                 patch.dict(os.environ,{'TEST_API_KEY':'fixture-secret','EXAMPLE_VISIBLE':'visible'}):
                self.assertEqual(examples.run('test',['--value','override'],root=root,workspace=workspace),7)
            argv=call.call_args.args[0];options=call.call_args.kwargs
            output=workspace.resolve()/'projects/examples/test'
            self.assertEqual(argv,[sys.executable,str((root/'01-test/main.py').resolve()),'--value','default',
                                   '--output',str(output),'--value','override'])
            self.assertEqual(options['cwd'],output)
            self.assertTrue(output.is_dir())
            self.assertFalse('TEST_API_KEY' in options['env'])
            self.assertEqual(options['env']['EXAMPLE_VISIBLE'],'visible')
            self.assertFalse(options.get('shell',False))

    def test_preview_and_linux_modes_do_not_connect_to_daemon(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp)/'catalog';fixture(root,requires=['daemon'])
            factory=Mock(side_effect=AssertionError('Daemon contacted'))
            with patch.object(examples.subprocess,'call',return_value=0):
                examples.run('test',mode='preview',root=root,workspace=Path(temp)/'work',connection_factory=factory)
            factory.assert_not_called()

    def test_default_workspace_is_canonicalized_before_output_containment_check(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp)/'catalog';fixture(root)
            workspace=Path(temp)/'work'
            with patch.object(examples,'_workspace',return_value=workspace), \
                 patch.object(examples.subprocess,'call',return_value=0) as launch:
                self.assertEqual(examples.run('test',root=root),0)
            self.assertEqual(launch.call_args.kwargs['cwd'],workspace.resolve()/'projects/examples/test')

    def test_capabilities_checked_read_only_before_launch_without_taking_ownership(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp)/'catalog';fixture(root,requires=['daemon','matrix-grayscale'])
            connection=Mock();connection.__enter__=Mock(return_value=connection);connection.__exit__=Mock(return_value=False)
            connection.request.side_effect=[{'workspace':str(Path(temp)/'work'),'device':{'ready':True,'owner':'another-program'}},
                                             '{"bits":3}']
            with patch.object(examples.subprocess,'call',return_value=0):
                examples.run('test',root=root,connection_factory=lambda:connection)
            self.assertEqual([c.args[0] for c in connection.request.call_args_list],['status','device'])
            self.assertEqual(connection.request.call_args.kwargs['arguments'],
                             {'method':'system.capability','args':['matrix-grayscale']})

    def test_missing_capability_or_unready_daemon_rejects_before_process_or_output_creation(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp)/'catalog';fixture(root,requires=['daemon','matrix-grayscale'])
            for ready,capability in ((False,None),(True,'null')):
                connection=Mock();connection.__enter__=Mock(return_value=connection);connection.__exit__=Mock(return_value=False)
                connection.request.side_effect=[{'workspace':str(Path(temp)/'work'),'device':{'ready':ready}},capability]
                with patch.object(examples.subprocess,'call') as launch:
                    with self.assertRaises(RuntimeError):
                        examples.run('test',root=root,connection_factory=lambda:connection)
                    launch.assert_not_called()
                self.assertFalse((Path(temp)/'work').exists())

    def test_help_needs_neither_daemon_nor_workspace_and_unknown_slug_is_not_a_path(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp)/'catalog';fixture(root,requires=['daemon'])
            factory=Mock(side_effect=AssertionError('Daemon contacted'))
            with patch.object(examples,'_workspace',side_effect=AssertionError('Settings read')), \
                 patch.object(examples.subprocess,'call',return_value=0) as launch:
                examples.run('test',['--help'],root=root,connection_factory=factory)
                self.assertEqual(launch.call_args.kwargs['cwd'],(root/'01-test').resolve())
                with self.assertRaisesRegex(ValueError,'Unknown example'):
                    examples.run('../../outside',root=root,connection_factory=factory)
            factory.assert_not_called()

    def test_symlinked_output_directory_cannot_escape_projects(self):
        with tempfile.TemporaryDirectory() as temp:
            base=Path(temp);fixture(base/'catalog')
            workspace=base/'work';workspace.mkdir();outside=base/'outside';outside.mkdir()
            (workspace/'projects').symlink_to(outside)
            with self.assertRaisesRegex(ValueError,'escapes the workspace'):
                examples.run('test',root=base/'catalog',workspace=workspace)


class CliTests(unittest.TestCase):
    def test_list_is_offline_and_dispatches_manifest_modes_and_arguments(self):
        with patch.object(cli,'Connection',side_effect=AssertionError('Daemon contacted')), \
             contextlib.redirect_stdout(io.StringIO()) as output:
            self.assertEqual(cli.main(['example']),0)
        self.assertIn('dot-matrix-animations',output.getvalue())
        with patch.object(examples,'run',return_value=0) as launch:
            self.assertEqual(cli.main(['example','--mode','preview','dot-matrix-animations','--frame-ms','40']),0)
            launch.assert_called_once_with('dot-matrix-animations',['--frame-ms','40'],mode='preview')

    def test_child_options_are_not_registered_in_the_launcher(self):
        with patch.object(examples,'run',return_value=0) as launch:
            self.assertEqual(cli.main(['example','linux-rgb-led','--future-flag','some value']),0)
            launch.assert_called_once_with('linux-rgb-led',['--future-flag','some value'],mode='run')
        with patch.object(examples,'run',return_value=0) as launch:
            self.assertEqual(cli.main(['example','linux-rgb-led','--','--help']),0)
            launch.assert_called_once_with('linux-rgb-led',['--help'],mode='run')

    def test_all_six_real_entrypoints_exit_on_help_before_hardware_access(self):
        env={**os.environ,'PYTHONPATH':os.pathsep.join((str(ROOT/'packages/session/src'),str(ROOT/'packages/device/src'))),
             'TORQUE_SOCKET':'/nonexistent-torque-test.sock'}
        for entry in examples.discover(ROOT/'examples').values():
            with self.subTest(slug=entry.slug):
                result=subprocess.run([sys.executable,str(entry.entrypoint),'--help'],env=env,
                                      capture_output=True,text=True,timeout=10)
                self.assertEqual(result.returncode,0,result.stderr)
                self.assertIn('usage:',result.stdout)


if __name__=='__main__':unittest.main()
