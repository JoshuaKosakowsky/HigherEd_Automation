"""Check the actual Qt runtime before setup or the hidden desktop launch."""

from __future__ import annotations

import ctypes
import os
from pathlib import Path
import subprocess
import sys

from app.gui import APP_NAME
from app.gui.services.process import python_module_launch
from shared.user_settings import get_user_settings_path
from shared.windows_platform import prime_windows_platform

PROJECT_ROOT = Path(__file__).resolve().parents[2]


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
    if sys.platform == "win32":
        print(f"Native Python executable: {sys._base_executable}", flush=True)
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
    command, environment = python_module_launch("app.gui.runtime_check")
    try:
        diagnostics.parent.mkdir(parents=True, exist_ok=True)
        with diagnostics.open("w", encoding="utf-8") as log:
            subprocess.run(
                command,
                cwd=PROJECT_ROOT,
                env=environment,
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


def bootstrap_desktop() -> int:
    """Start the desktop from the native GUI interpreter using the project venv."""
    venv = PROJECT_ROOT / ".venv"
    if not (venv / "pyvenv.cfg").is_file():
        show_launch_error("The desktop app could not find its Python environment. Run .\\setup.ps1.")
        return 1

    command, environment = python_module_launch(
        "app.gui.runtime_check", "--launch", venv_executable=venv / "Scripts" / "pythonw.exe",
    )
    try:
        return subprocess.run(
            command, cwd=PROJECT_ROOT, env=environment,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0), check=False,
        ).returncode
    except OSError:
        show_launch_error("The desktop app could not start Python. Run .\\setup.ps1.")
        return 1


if __name__ == "__main__":
    if sys.argv[1:] == ["--bootstrap"]:
        raise SystemExit(bootstrap_desktop())
    if sys.argv[1:] == ["--launch"]:
        raise SystemExit(launch_desktop())
    verify_qt_runtime()
