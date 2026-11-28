"""Open the interactive check queue through the ordinary authorized workflow runner."""

from importlib import import_module
from pathlib import Path
import subprocess

from app.gui.models import WorkflowContext, WorkflowResult
from app.gui.services.process import python_module_launch
from shared.mines_paths import get_papercut_scan_directory
from shared.workflow_errors import WorkflowUserError


def start_check_scan_process(module: str) -> subprocess.Popen:
    """Start a review or support process without a Windows console."""
    command, environment = python_module_launch(module)
    return subprocess.Popen(
        command,
        cwd=Path(__file__).resolve().parents[3],
        env=environment,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
    )


def run_check_scanning(context: WorkflowContext) -> WorkflowResult:
    if not get_papercut_scan_directory().is_dir():
        raise ValueError("Sync Apps / Scans for PaperCut MF in business OneDrive and reopen Check Scan Review.")
    try:
        # Intake imports the PDF renderer. Verify the OCR runtime before
        # starting the watcher, which would otherwise load it on the first scan.
        intake = import_module("workflows.check_scanning.intake")
        import_module("rapidocr")
        import_module("onnxruntime")
    except (ImportError, OSError) as error:
        raise WorkflowUserError(
            "Check Scan Review could not load its PDF or OCR components. "
            "Close the app, run setup.ps1 from the updated repository, then reopen the app."
        ) from error
    intake.queue_path()
    context.progress.report("Reviewing PaperCut scans in the check queue")
    with start_check_scan_process("app.gui.pages.check_scans") as process:
        code = process.wait()
    return WorkflowResult(code == 0, "Check Scan Review closed." if code == 0
                          else "Check Scan Review could not run. Verify setup and local OneDrive access.")
