"""Check the actual Qt runtime before setup or the hidden desktop launch."""

from __future__ import annotations

import os
from pathlib import Path
import sys


def require_windows_plugin(plugins_path: Path) -> None:
    """Fail with a repair instruction before Qt aborts on a missing DLL."""
    plugin = plugins_path / "platforms" / "qwindows.dll"
    if not plugin.is_file():
        raise RuntimeError(
            f"Qt's Windows platform plugin is missing: {plugin}\n"
            "Close the automation app and run .\\setup.ps1 -RepairGui."
        )


def verify_qt_runtime(*, show_window: bool = False) -> None:
    # Flush diagnostics before QApplication: Qt initialization can abort the
    # process without raising a catchable Python exception.
    print(f"Python executable: {sys.executable}", flush=True)
    for name in ("QT_PLUGIN_PATH", "QT_QPA_PLATFORM_PLUGIN_PATH", "QT_QPA_PLATFORM"):
        print(f"{name}: {os.environ.get(name, '(unset)')}", flush=True)
    os.environ["QT_DEBUG_PLUGINS"] = "1"

    import PySide6
    from PySide6.QtCore import QLibraryInfo
    from PySide6.QtWidgets import QApplication, QWidget

    plugins_path = Path(QLibraryInfo.path(QLibraryInfo.LibraryPath.PluginsPath))
    print(f"PySide6 version: {PySide6.__version__}", flush=True)
    print(f"Qt plugins directory: {plugins_path}", flush=True)
    if sys.platform == "win32":
        require_windows_plugin(plugins_path)

    app = QApplication([])
    window = QWidget()
    if show_window:
        window.show()
    app.processEvents()
    window.close()
    app.quit()
    print("Qt runtime verification succeeded.", flush=True)


if __name__ == "__main__":
    verify_qt_runtime()
