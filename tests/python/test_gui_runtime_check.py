from pathlib import Path
import subprocess
import sys
from tempfile import TemporaryDirectory
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

from app.gui import runtime_check
from app.gui.runtime_check import require_windows_plugin


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

            self.assertEqual(launch.call_args.args[0], [sys.executable, "-m", "app.gui.runtime_check"])
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


if __name__ == "__main__":
    unittest.main()
