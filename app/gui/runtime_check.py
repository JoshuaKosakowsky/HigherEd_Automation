"""Check the actual Qt runtime before setup or the hidden desktop launch."""

from __future__ import annotations

import ctypes
import os
from pathlib import Path
import subprocess
import sys

from app.gui import APP_NAME
from shared.user_settings import get_user_settings_path
from shared.windows_platform import prime_windows_platform


def require_windows_plugin(plugins_path: Path) -> None:
    """Fail with a repair instruction before Qt aborts on a missing DLL."""
    plugin = plugins_path / "platforms" / "qwindows.dll"
    if not plugin.is_file():
        raise RuntimeError(
            f"Qt's Windows platform plugin is missing: {plugin}\n"
            "Close the automation app and run .\\setup.ps1 -RepairGui."
        )


def verify_qt_runtime(*, show_window: bool = False) -> None:
    prime_windows_platform()
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


def show_launch_error(message: str) -> None:
    if sys.platform == "win32":
        ctypes.windll.user32.MessageBoxW(None, message, APP_NAME, 0x10)
    else:
        print(message, file=sys.stderr)


def launch_desktop() -> int:
    """Verify Qt in a separate process before the windowed shortcut starts the GUI."""
    settings = get_user_settings_path()
    if settings is None:
        show_launch_error("The desktop app could not find Windows local app data for this account.")
        return 1

    diagnostics = settings.with_name("gui-runtime-check.log")
    try:
        diagnostics.parent.mkdir(parents=True, exist_ok=True)
        with diagnostics.open("w", encoding="utf-8") as log:
            subprocess.run(
                [sys.executable, "-m", "app.gui.runtime_check"],
                cwd=Path(__file__).resolve().parents[2],
                stdin=subprocess.DEVNULL,
                stdout=log,
                stderr=subprocess.STDOUT,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
                timeout=60,
                check=True,
            )
    except (OSError, subprocess.SubprocessError):
        show_launch_error(
            "The desktop runtime could not start. Run .\\setup.ps1 -RepairGui from the repository.\n\n"
            f"Diagnostic log for IT: {diagnostics}"
        )
        return 1

    prime_windows_platform()
    from app.gui.main import main

    return main([])


if __name__ == "__main__":
    if sys.argv[1:] == ["--launch"]:
        raise SystemExit(launch_desktop())
    verify_qt_runtime()
