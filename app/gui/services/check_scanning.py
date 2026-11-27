"""Open the interactive check queue through the ordinary authorized workflow runner."""

from pathlib import Path
import subprocess
import sys

from app.gui.models import WorkflowContext, WorkflowResult
from shared.mines_paths import get_papercut_scan_directory
from workflows.check_scanning.intake import queue_path


def run_check_scanning(context: WorkflowContext) -> WorkflowResult:
    if not get_papercut_scan_directory().is_dir():
        raise ValueError("Sync Apps / Scans for PaperCut MF in business OneDrive and reopen Check Scan Review.")
    queue_path()
    context.progress.report("Reviewing PaperCut scans in the check queue")
    result = subprocess.run([sys.executable, "-m", "app.gui.pages.check_scans"],
                            cwd=Path(__file__).resolve().parents[3], check=False,
                            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    return WorkflowResult(result.returncode == 0, "Check Scan Review closed." if result.returncode == 0
                          else "Check Scan Review could not run. Verify setup and local OneDrive access.")
