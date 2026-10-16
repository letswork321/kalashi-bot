from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import Mock, patch
import windows_setup as w

class WindowsSetupTests(unittest.TestCase):
    def test_platform_python_paths(self):
        directory=Path('project-env')
        with patch.object(w.os,'name','nt'):
            self.assertEqual(str(w.environment_python(directory)),str(directory/'Scripts/python.exe'))
        with patch.object(w.os,'name','posix'):
            self.assertEqual(w.environment_python(directory),directory/'bin/python')

    def test_incomplete_environment_is_preserved(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);(root/'.venv').mkdir()
            marker=root/'.venv'/'keep-me';marker.write_text('untouched')
            with self.assertRaisesRegex(w.SetupError,'incomplete'):
                w.prepare(root)
            self.assertEqual(marker.read_text(),'untouched')

    def test_unsupported_base_version_stops_before_creation(self):
        with tempfile.TemporaryDirectory() as tmp, patch.object(w.sys,'version_info',(3,11,9)):
            with self.assertRaisesRegex(w.SetupError,'Python 3.12 is required'):w.prepare(tmp)
            self.assertFalse((Path(tmp)/'.venv').exists())

    def test_existing_env_installs_with_its_own_interpreter(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);python=w.environment_python(root/'.venv');python.parent.mkdir(parents=True);python.touch()
            runner=Mock(return_value=subprocess.CompletedProcess([],0,stdout='3.12\n'))
            with patch.object(w,'checked',runner), patch.object(w.subprocess,'run',return_value=Mock(returncode=0)):
                self.assertEqual(w.prepare(root),python)
            commands=[call.args[0] for call in runner.call_args_list]
            self.assertTrue(all(Path(command[0])==python for command in commands))
            self.assertTrue(any('install' in c and root/'requirements.txt' in c for c in commands))
            self.assertTrue(any('check' in c for c in commands))
            self.assertFalse(any('ensurepip' in c for c in commands))

    def test_missing_pip_restores_bundled_ensurepip(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);python=w.environment_python(root/'.venv');python.parent.mkdir(parents=True);python.touch()
            runner=Mock(return_value=subprocess.CompletedProcess([],0,stdout='3.12\n'))
            with patch.object(w,'checked',runner), patch.object(w.subprocess,'run',return_value=Mock(returncode=1)):
                w.prepare(root)
            runner.assert_any_call([python,'-I','-m','ensurepip','--upgrade'])

    def test_wrong_existing_version_never_installs_dependencies(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);python=w.environment_python(root/'.venv');python.parent.mkdir(parents=True);python.touch()
            with patch.object(w,'checked',return_value=Mock(stdout='3.11\n')) as runner:
                with self.assertRaisesRegex(w.SetupError,'different Python version'):w.prepare(root)
                self.assertEqual(runner.call_count,1)

    def test_new_venv_uses_bundled_pip(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp)
            with patch.object(w.venv,'EnvBuilder') as builder, patch.object(w,'checked',return_value=Mock(stdout='3.12\n')), patch.object(w.subprocess,'run',return_value=Mock(returncode=0)):
                w.prepare(root)
                builder.assert_called_once_with(with_pip=True)
                builder.return_value.create.assert_called_once_with(root/'.venv')

    def test_setup_failure_never_launches_or_removes_history(self):
        with patch.object(w,'prepare',side_effect=w.SetupError('dependency failure')),patch.object(w.subprocess,'call') as launch:
            self.assertEqual(w.main([]),1)
            launch.assert_not_called()

    def test_setup_only_does_not_launch_or_send_messages(self):
        with patch.object(w,'prepare',return_value=Path('venv-python')),patch.object(w.subprocess,'call') as launch:
            self.assertEqual(w.main(['--setup-only']),0)
            launch.assert_not_called()

    def test_launcher_calls_private_setup_with_selected_venv(self):
        with patch.object(w,'prepare',return_value=Path('venv-python')),patch.object(w.subprocess,'call',return_value=0) as launch:
            self.assertEqual(w.main([]),0)
            self.assertEqual(launch.call_args.args[0],['venv-python',str(w.ROOT/'private_setup.py')])

    def test_subprocess_failures_preserve_exit_failure(self):
        with patch.object(w.subprocess,'run',return_value=Mock(returncode=7)):
            with self.assertRaisesRegex(w.SetupError,'exit 7'):w.checked(['pip','check'])

    def test_batch_has_quoted_nuget_path_no_py_launcher(self):
        batch=(w.ROOT/'start-windows.cmd').read_text()
        self.assertIn('%USERPROFILE%\\Downloads\\python.3.12.10\\tools\\python.exe',batch)
        self.assertIn('"%botPython%" "%~dp0windows_setup.py"',batch)
        self.assertIn('DisableDelayedExpansion',batch)
        self.assertNotIn('py -3.12',batch)
        self.assertNotIn('where py',batch)
        self.assertNotIn('ExecutionPolicy',batch)
