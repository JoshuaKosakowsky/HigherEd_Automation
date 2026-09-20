"""GUI adapter for the existing current-user report-watcher installer."""

from __future__ import annotations

import logging
import shutil
import subprocess
import sys
from pathlib import Path

from app.gui.models import WorkflowContext, WorkflowResult
from shared.user_settings import read_automation_user_settings


PROJECT_ROOT = Path(__file__).resolve().parents[3]
SETUP_SCRIPT = PROJECT_ROOT / "setup" / "setup_report_filing_watcher.ps1"


def run_setup_report_watcher(context: WorkflowContext) -> WorkflowResult:
    """Install through the proven PowerShell entry point without elevation."""
    if sys.platform != "win32":
        raise ValueError("Report watcher setup is Windows-only. Run it on your work PC.")
    if read_automation_user_settings() is None:
        raise ValueError(
            "Run setup.ps1 first to save your name and cashier initials, then try again."
        )
    if not SETUP_SCRIPT.is_file():
        raise ValueError("The report watcher installer is missing. Restore the repository files.")
    powershell = shutil.which("powershell.exe")
    if powershell is None:
        raise ValueError("Windows PowerShell could not be found on this computer.")

    logger = logging.getLogger("highered_automation.gui")
    try:
        completed = subprocess.run(
            [powershell, "-NoLogo", "-NoProfile", "-NonInteractive",
             "-File", str(SETUP_SCRIPT)],
            cwd=PROJECT_ROOT,
            capture_output=True,
            text=True,
            errors="replace",
            creationflags=subprocess.CREATE_NO_WINDOW,
            timeout=120,
            check=False,
        )
    except subprocess.TimeoutExpired:
        logger.error("Report watcher installer exceeded its 120-second timeout.")
        return WorkflowResult(False, (
            "Report watcher setup did not finish in time. It may have partially completed; "
            "ask your administrator to check the scheduled task before trying again."
        ))
    # The installer emits setup diagnostics, not report contents.
    if completed.stdout:
        logger.info("Report watcher setup: %s", completed.stdout.strip())
    if completed.stderr:
        logger.warning("Report watcher setup diagnostics: %s", completed.stderr.strip())
    if completed.returncode != 0:
        return WorkflowResult(False, (
            "Report watcher setup failed. Open the GUI log folder for details or contact "
            "your administrator. Check that setup.ps1 has completed and Windows permits "
            "creating the scheduled task."
        ))
    return WorkflowResult(True, (
        "The report filing watcher was installed or updated for your Windows login "
        "and a start was requested. It will also start when you sign in. Matching "
        "reports will ask for confirmation before being filed; unrelated downloads are ignored."
    ))
