from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

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


if __name__ == "__main__":
    unittest.main()
