"""Run GUI launchers with live, explicit progress markers and bounded waits."""

from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess
import sys
from threading import Thread

from shared.progress import ProgressReporter, ProgressUpdate


PROGRESS_MARKER = "HIGHERED_PROGRESS="


def python_module_launch(
    module: str, *arguments: str, venv_executable: Path | None = None,
) -> tuple[list[str], dict[str, str] | None]:
    """Build a Python command that preserves the virtual environment."""
    executable = sys.executable
    environment = None
    if sys.platform == "win32" and (venv_executable is not None or sys.prefix != sys.base_prefix):
        # The Windows venv redirector creates another process without passing
        # CREATE_NO_WINDOW on. Invoke the native interpreter and give CPython
        # the same virtual environment path that its redirector would supply.
        environment = dict(os.environ, __PYVENV_LAUNCHER__=str(venv_executable or executable))
        executable = sys._base_executable
    return [executable, "-m", module, *arguments], environment


def _report_marker(line: str, reporter: ProgressReporter) -> None:
    if not line.startswith(PROGRESS_MARKER):
        return
    try:
        payload = json.loads(line.removeprefix(PROGRESS_MARKER))
        update = ProgressUpdate(payload["stage"], payload.get("completed"), payload.get("total"))
    except (ValueError, TypeError, KeyError):
        # Bad telemetry must not interrupt a financial workflow. Ordinary log
        # text is never interpreted as progress or copied into the GUI status.
        return
    reporter.report(update.stage, completed=update.completed, total=update.total)


def run_process(
    command: list[str], *, cwd: Path, timeout: int, creationflags: int,
    progress_reporter: ProgressReporter,
) -> subprocess.CompletedProcess[str]:
    """Drain both pipes while waiting, preserving stdout/stderr and timeout behavior."""
    with subprocess.Popen(
        command, cwd=cwd, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
        text=True, errors="replace", creationflags=creationflags,
    ) as process:
        stdout: list[str] = []
        stderr: list[str] = []

        def read(stream, lines: list[str], *, report: bool) -> None:
            for line in stream:
                lines.append(line)
                if report:
                    _report_marker(line.rstrip("\r\n"), progress_reporter)

        readers = (
            Thread(target=read, args=(process.stdout, stdout), kwargs={"report": True}, daemon=True),
            Thread(target=read, args=(process.stderr, stderr), kwargs={"report": False}, daemon=True),
        )
        for reader in readers:
            reader.start()
        try:
            process.wait(timeout=timeout)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait()
            raise
        finally:
            for reader in readers:
                reader.join()
        return subprocess.CompletedProcess(command, process.returncode, "".join(stdout), "".join(stderr))
