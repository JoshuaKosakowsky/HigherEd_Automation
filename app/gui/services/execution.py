"""Non-blocking workflow execution and staff-safe error reporting."""

from __future__ import annotations

import logging
import queue
import threading
from dataclasses import replace
from pathlib import Path

from app.gui.models import WorkflowContext, WorkflowDefinition, WorkflowResult
from data_processing.refunds.extract import RefundExtractError
from shared.cancellation import CancellationToken, WorkflowCancelled
from shared.progress import ProgressReporter, ProgressUpdate


def friendly_error_message(error: Exception) -> str:
    if isinstance(error, RefundExtractError):
        return str(error)
    if isinstance(error, FileNotFoundError):
        return (
            "The source file could not be found. Check the selected file and "
            "confirm that OneDrive has finished synchronizing it."
        )
    if isinstance(error, PermissionError):
        return (
            "A workbook appears to be open or unavailable. Close it in Excel "
            "and try again."
        )
    if isinstance(error, ValueError):
        return f"The input could not be validated. {error}"
    return (
        "The process could not be completed. Review the application log or "
        "contact the automation administrator."
    )


class WorkflowExecutor:
    """Run one workflow at a time without touching UI widgets from a worker."""

    def __init__(self, logger: logging.Logger, log_path: Path) -> None:
        self._logger = logger
        self._log_path = log_path
        self._lock = threading.Lock()
        self._running = False
        self._cancellation: CancellationToken | None = None
        self._progress = ProgressReporter()

    @property
    def progress_snapshot(self) -> ProgressUpdate | None:
        return self._progress.snapshot

    def cancel(self) -> bool:
        with self._lock:
            return bool(self._running and self._cancellation and self._cancellation.request())

    @property
    def is_running(self) -> bool:
        with self._lock:
            return self._running

    @property
    def log_directory(self) -> Path:
        return self._log_path.parent

    def run_async(
        self,
        definition: WorkflowDefinition,
        context: WorkflowContext,
    ) -> queue.Queue[WorkflowResult]:
        with self._lock:
            if self._running:
                raise RuntimeError("Another workflow is already running.")
            self._running = True
            self._cancellation = CancellationToken() if definition.cancellable else None
            self._progress = ProgressReporter()
            self._progress.report("Starting workflow")
            context = replace(context, cancellation=self._cancellation, progress=self._progress)

        results: queue.Queue[WorkflowResult] = queue.Queue(maxsize=1)
        worker = threading.Thread(
            target=self._execute,
            args=(definition, context, results),
            name=f"workflow-{definition.workflow_id}",
            daemon=True,
        )
        worker.start()
        return results

    def _execute(
        self,
        definition: WorkflowDefinition,
        context: WorkflowContext,
        results: queue.Queue[WorkflowResult],
    ) -> None:
        mode = context.mode.value if context.mode else "not applicable"
        self._logger.info(
            "Workflow started: id=%s mode=%s parameter_keys=%s",
            definition.workflow_id,
            mode,
            sorted(context.parameters),
        )

        try:
            result = definition.runner(context)
            result = WorkflowResult(
                success=result.success,
                message=result.message,
                output_path=result.output_path,
                log_path=result.log_path or self._log_path,
                cancelled=result.cancelled,
            )
            self._logger.info(
                "Workflow completed: id=%s success=%s output=%s",
                definition.workflow_id,
                result.success,
                result.output_path,
            )
        except WorkflowCancelled as error:
            self._logger.info("Workflow cancelled: id=%s", definition.workflow_id)
            result = WorkflowResult(False, str(error), log_path=self._log_path, cancelled=True)
        except Exception as error:
            if context.cancellation and context.cancellation.is_requested:
                # A cancelled in-flight request can return a timeout or network
                # error before the next checkpoint. Treat that as a normal stop.
                self._logger.info("Workflow cancelled: id=%s", definition.workflow_id)
                result = WorkflowResult(False, str(WorkflowCancelled()), log_path=self._log_path, cancelled=True)
            else:
                self._logger.exception("Workflow failed: id=%s", definition.workflow_id)
                result = WorkflowResult(
                    success=False,
                    message=friendly_error_message(error),
                    log_path=self._log_path,
                )
        finally:
            with self._lock:
                self._running = False
                self._cancellation = None

        results.put(result)
