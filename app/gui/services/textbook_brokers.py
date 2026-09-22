"""GUI adapter for the existing Textbook Brokers SFTP workflow."""

from __future__ import annotations

import logging
import shutil
import subprocess
import sys
from pathlib import Path

from app.gui.models import WorkflowContext, WorkflowResult


PROJECT_ROOT = Path(__file__).resolve().parents[3]
WORKFLOW_SCRIPT = PROJECT_ROOT / "launcher" / "run_textbook_brokers.ps1"
OUTPUT_MARKER = "HIGHERED_OUTPUT_PATH="
NO_PENDING_MARKER = "HIGHERED_NO_PENDING_FILES=1"


def run_textbook_brokers(context: WorkflowContext) -> WorkflowResult:
    """Download pending SFTP sources and create the Banner-ready TSPLOAD file."""
    if sys.platform != "win32":
        raise ValueError(
            "Textbook Brokers SFTP processing is Windows-only. Run it on your work PC."
        )
    if not WORKFLOW_SCRIPT.is_file():
        raise ValueError(
            "The Textbook Brokers workflow launcher is missing. Restore the repository files."
        )
    powershell = shutil.which("powershell.exe")
    if powershell is None:
        raise ValueError("Windows PowerShell could not be found on this computer.")

    term_code = str(context.parameters["term_code"])
    logger = logging.getLogger("highered_automation.gui")
    try:
        completed = subprocess.run(
            [
                powershell,
                "-NoLogo",
                "-NoProfile",
                "-NonInteractive",
                "-File",
                str(WORKFLOW_SCRIPT),
                "-TermCode",
                term_code,
                "-PrepareOnly",
            ],
            cwd=PROJECT_ROOT,
            capture_output=True,
            text=True,
            errors="replace",
            creationflags=subprocess.CREATE_NO_WINDOW,
            timeout=300,
            check=False,
        )
    except subprocess.TimeoutExpired:
        logger.error("Textbook Brokers SFTP preparation exceeded its 300-second timeout.")
        return WorkflowResult(
            False,
            "Textbook Brokers did not finish in time. Files may have downloaded, but "
            "nothing was archived. Open the GUI log folder or contact your administrator.",
        )

    if completed.stdout:
        logger.info("Textbook Brokers workflow: %s", completed.stdout.strip())
    if completed.stderr:
        logger.warning("Textbook Brokers diagnostics: %s", completed.stderr.strip())
    if completed.returncode != 0:
        return WorkflowResult(
            False,
            "Textbook Brokers could not download or prepare the files. Nothing was "
            "archived. Open the GUI log folder for details or contact your administrator.",
        )

    if NO_PENDING_MARKER in completed.stdout.splitlines():
        return WorkflowResult(
            True,
            "No pending Finaid or IA files were found on the Textbook Brokers SFTP "
            "server. Nothing was downloaded, transformed, moved, or archived.",
        )

    output_path = _extract_output_path(completed.stdout)
    if output_path is None:
        logger.error("Textbook Brokers completed without an output-path marker.")
        return WorkflowResult(
            False,
            "Textbook Brokers finished without identifying the prepared TSPLOAD file. "
            "Nothing was archived. Open the GUI log folder for details.",
        )

    return WorkflowResult(
        success=True,
        message=(
            "Downloaded the pending Finaid and IA files from the Textbook Brokers "
            "SFTP server and created TSPLOAD.csv. After the Banner upload succeeds, "
            f"run archive-textbook-brokers -TermCode {term_code} from PowerShell to "
            "archive the pending files."
        ),
        output_path=output_path,
    )


def _extract_output_path(output: str) -> Path | None:
    """Read the launcher's stable result marker without parsing human log text."""
    for line in reversed(output.splitlines()):
        if line.startswith(OUTPUT_MARKER):
            value = line.removeprefix(OUTPUT_MARKER).strip()
            return Path(value) if value else None
    return None
