from pathlib import Path
import subprocess
import sys
from tempfile import TemporaryDirectory
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

from app.gui import runtime_check
from app.gui.runtime_check import require_windows_plugin
from app.gui.services import process


class WindowsPluginTests(unittest.TestCase):
    def test_missing_plugin_reports_exact_path_and_repair(self) -> None:
        with TemporaryDirectory() as directory:
            plugins = Path(directory)
            with self.assertRaises(RuntimeError) as raised:
                require_windows_plugin(plugins)
            self.assertIn(str(plugins / "platforms" / "qwindows.dll"), str(raised.exception))
            self.assertIn("setup.ps1 -RepairGui", str(raised.exception))

    def test_plugin_directory_alone_is_not_sufficient(self) -> None:
        with TemporaryDirectory() as directory:
            plugins = Path(directory)
            (plugins / "platforms" / "qwindows.dll").mkdir(parents=True)
            with self.assertRaises(RuntimeError):
                require_windows_plugin(plugins)

    def test_existing_plugin_passes_the_presence_check(self) -> None:
        with TemporaryDirectory() as directory:
            plugins = Path(directory)
            (plugins / "platforms").mkdir()
            (plugins / "platforms" / "qwindows.dll").write_bytes(b"synthetic fixture")
            require_windows_plugin(plugins)


class DesktopShortcutTests(unittest.TestCase):
    def test_native_launch_preserves_windows_venv(self):
        windows = SimpleNamespace(
            platform="win32", executable=r"C:\Program Files\Python311\pythonw.exe",
            _base_executable=r"C:\Program Files\Python311\pythonw.exe",
            prefix=r"C:\Program Files\Python311", base_prefix=r"C:\Program Files\Python311",
        )
        venv = Path(r"C:\School\Project\.venv\Scripts\pythonw.exe")
        with patch.object(process, "sys", windows):
            command, environment = process.python_module_launch(
                "app.gui.runtime_check", "--launch", venv_executable=venv,
            )
        self.assertEqual(command, [windows.executable, "-m", "app.gui.runtime_check", "--launch"])
        self.assertEqual(environment["__PYVENV_LAUNCHER__"], str(venv))

        windows.executable = str(venv)
        windows.prefix = r"C:\School\Project\.venv"
        with patch.object(process, "sys", windows):
            command, environment = process.python_module_launch("workflows.check_scanning.watch")
        self.assertEqual(command, [windows._base_executable, "-m", "workflows.check_scanning.watch"])
        self.assertEqual(environment["__PYVENV_LAUNCHER__"], str(venv))

    def test_launch_writes_probe_diagnostics_and_runs_gui_without_shortcut_args(self):
        with TemporaryDirectory() as directory:
            settings = Path(directory) / "HigherEdAutomation" / "user-settings.json"
            gui_main = Mock(return_value=0)

            def probe(_command, **options):
                options["stdout"].write("Qt runtime verification succeeded.\n")
                gui_main.assert_not_called()

            with (patch.object(runtime_check, "get_user_settings_path", return_value=settings),
                  patch.object(runtime_check.subprocess, "CREATE_NO_WINDOW", 0x08000000, create=True),
                  patch.object(runtime_check.subprocess, "run", side_effect=probe) as launch,
                  patch.dict(sys.modules, {"app.gui.main": SimpleNamespace(main=gui_main)})):
                self.assertEqual(runtime_check.launch_desktop(), 0)

            self.assertEqual(launch.call_args.args[0], process.python_module_launch("app.gui.runtime_check")[0])
            self.assertEqual(launch.call_args.kwargs["creationflags"], 0x08000000)
            self.assertIn("verification succeeded", settings.with_name("gui-runtime-check.log").read_text())
            gui_main.assert_called_once_with([])

    def test_probe_failure_shows_repair_instructions_and_stops_gui_launch(self):
        with TemporaryDirectory() as directory:
            settings = Path(directory) / "user-settings.json"
            gui_main = Mock()
            failure = subprocess.CalledProcessError(1, "runtime probe")
            with (patch.object(runtime_check, "get_user_settings_path", return_value=settings),
                  patch.object(runtime_check.subprocess, "run", side_effect=failure),
                  patch.object(runtime_check, "show_launch_error") as error,
                  patch.dict(sys.modules, {"app.gui.main": SimpleNamespace(main=gui_main)})):
                self.assertEqual(runtime_check.launch_desktop(), 1)

            gui_main.assert_not_called()
            self.assertIn("setup.ps1 -RepairGui", error.call_args.args[0])
            self.assertIn(str(settings.with_name("gui-runtime-check.log")), error.call_args.args[0])

    def test_shortcut_bootstrap_uses_the_project_virtual_environment(self):
        with TemporaryDirectory() as directory:
            project = Path(directory)
            venv = project / ".venv"
            venv.mkdir()
            (venv / "pyvenv.cfg").touch()
            command = ["base-pythonw.exe", "-m", "app.gui.runtime_check", "--launch"]
            environment = {"__PYVENV_LAUNCHER__": str(venv / "Scripts" / "pythonw.exe")}
            with (patch.object(runtime_check, "PROJECT_ROOT", project),
                  patch.object(runtime_check, "python_module_launch", return_value=(command, environment)) as build,
                  patch.object(runtime_check.subprocess, "run", return_value=SimpleNamespace(returncode=0)) as launch):
                self.assertEqual(runtime_check.bootstrap_desktop(), 0)

            build.assert_called_once_with(
                "app.gui.runtime_check", "--launch", venv_executable=venv / "Scripts" / "pythonw.exe",
            )
            self.assertEqual(launch.call_args.args[0], command)
            self.assertEqual(launch.call_args.kwargs["env"], environment)


if __name__ == "__main__":
    unittest.main()
