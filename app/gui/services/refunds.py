"""GUI adapter for the existing manual and SQL refund review pipelines."""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from datetime import date
from hashlib import sha256
import json
import logging
from pathlib import Path
import shutil

from PySide6.QtCore import QLockFile, QStandardPaths

from app.gui import APP_VERSION
from app.gui.models import (
    MANUAL_SOURCE, SQL_SOURCE, STANDALONE_REFUND_SOURCE, WorkflowContext, WorkflowMode, WorkflowResult,
)
from app.gui.services.access import get_current_login, load_access_configuration
from data_processing.refunds.extract import ExtractSettings, QUERY_DIRECTORY
from data_processing.refunds.pipeline import (
    run_refund_download_pipeline, run_refund_pipeline, run_standalone_refund_pipeline,
)
from data_processing.refunds.terms import RefundParameters, validate_term
from shared.insights.config import InsightsSettings, load_department_profiles
from shared.insights.session_auth import build_authenticated_client
from shared.mines_paths import get_shared_gui_access_path


@contextmanager
def _refund_extract_cache(
    settings: InsightsSettings, principal_id: int | None, parameters: RefundParameters,
) -> Iterator[Path]:
    """Keep interrupted extracts locally, isolated by connection, user and run."""
    if type(principal_id) is not int:
        raise ValueError("Insights did not identify the signed-in user for refund recovery.")
    local_root = QStandardPaths.writableLocation(QStandardPaths.StandardLocation.GenericCacheLocation)
    if not local_root:
        raise ValueError("A local user cache directory is required for refund recovery.")
    identity = sha256(json.dumps([
        settings.environment, settings.base_url, settings.database_id, principal_id,
    ]).encode()).hexdigest()
    root = Path(local_root) / "HigherEdAutomation" / "refunds" / identity
    root.mkdir(parents=True, exist_ok=True)
    # A second app instance must not read, replace or remove an active cache.
    lock = QLockFile(str(root / "extract.lock"))
    lock.setStaleLockTime(0)
    if not lock.tryLock(0):
        raise ValueError("Another Refund Review SQL run is using this local cache. Close that run first.")
    logger = logging.getLogger("highered_automation.gui")
    try:
        run_day = parameters.run_date.isoformat()
        for previous in root.iterdir():
            if previous.is_dir() and previous.name != run_day:
                # Only remove dated caches created by this adapter.
                try:
                    date.fromisoformat(previous.name)
                except ValueError:
                    continue
                shutil.rmtree(previous)
        fingerprint = sha256(APP_VERSION.encode())
        for name in (
            "refund_transactions_extract.sql", "refund_context_extract.sql",
            "refund_scope.sql", "refund_non_allowable_detail_codes.sql",
            "refund_student_addresses.sql",
        ):
            fingerprint.update(name.encode())
            fingerprint.update((QUERY_DIRECTORY / name).read_bytes())
        directory = root / run_day / f"{parameters.target_term}-{fingerprint.hexdigest()}"
        if (directory / "extract_manifest.json").exists():
            logger.info("Resuming compatible completed refund batches from today's interrupted run.")
        logger.info("Refund recovery cache: %s. Completed batches are retained on failure or cancellation.", directory)
        yield directory
        # Successful reviews must not make the next run reuse an old snapshot.
        if directory.exists():
            try:
                shutil.rmtree(directory)
            except OSError:
                # Invalidate reuse even if antivirus/file locks prevent cleanup.
                (directory / "extract_manifest.json").unlink(missing_ok=True)
                logger.warning("The completed refund cache could not be fully removed; reuse was disabled.")
    finally:
        lock.unlock()


def run_refund_review(context: WorkflowContext) -> WorkflowResult:
    """Create a review from downloads, batched extracts or the standalone SQL report."""
    if context.cancellation:
        context.cancellation.check()
    context.progress.report("Validating Refund Review inputs")
    source = context.parameters.get("refund_source", MANUAL_SOURCE)
    if source not in (MANUAL_SOURCE, SQL_SOURCE, STANDALONE_REFUND_SOURCE):
        raise ValueError("Choose a Refund Review data source.")
    target_term = validate_term(str(context.parameters["target_term"]))
    output_file = Path(context.parameters["output_file"])

    if output_file.exists():
        raise ValueError(
            "The output workbook already exists. Choose a new filename so an "
            "earlier review is not overwritten."
        )

    parameters = RefundParameters(target_term=target_term, run_date=date.today())
    log_progress = logging.getLogger("highered_automation.gui").info
    if source != MANUAL_SOURCE:
        policy = load_access_configuration(get_shared_gui_access_path())
        if not policy.is_administrator(get_current_login()):
            raise ValueError("Only an administrator can run the Insights refund queries.")
        if context.mode != WorkflowMode.PRODUCTION:
            raise ValueError("Refund Review SQL requires the PROD Insights database.")
        profile = load_department_profiles()[WorkflowMode.PRODUCTION.value]
        if profile is None:
            raise ValueError("Insights PROD is not configured.")
        context.progress.report("Connecting to PROD Insights — complete browser sign-in if prompted")
        client, _ = build_authenticated_client(profile.settings, browser="chrome")
        with client:
            if source == STANDALONE_REFUND_SOURCE:
                created_file, report = run_standalone_refund_pipeline(
                    client=client, target_term=target_term, run_date=parameters.run_date,
                    output_file=output_file, progress=log_progress,
                    cancellation=context.cancellation, progress_reporter=context.progress,
                )
            else:
                with _refund_extract_cache(profile.settings, client.get_current_user().id, parameters) as directory:
                    created_file, report = run_refund_pipeline(
                        parameters=parameters,
                        extract_settings=ExtractSettings(
                            target_term=target_term, batch_count=20, extract_directory=directory,
                            resume=(directory / "extract_manifest.json").exists(), run_date=parameters.run_date,
                        ),
                        transaction_template_path=QUERY_DIRECTORY / "refund_transactions_extract.sql",
                        context_template_path=QUERY_DIRECTORY / "refund_context_extract.sql",
                        output_file=output_file, client=client, progress=log_progress,
                        cancellation=context.cancellation, progress_reporter=context.progress,
                    )
    else:
        transaction_file = Path(context.parameters["transaction_file"])
        context_file = Path(context.parameters["context_file"])
        if transaction_file.resolve() == context_file.resolve():
            raise ValueError("The transaction and context downloads must be different files.")
        created_file, report = run_refund_download_pipeline(
            parameters=parameters,
            transaction_file=transaction_file,
            context_file=context_file,
            output_file=output_file,
            cancellation=context.cancellation,
            progress=log_progress,
            progress_reporter=context.progress,
        )

    source_note = ("Used standalone Refunds.sql. See Run Details for the run summary. "
                   if source == STANDALONE_REFUND_SOURCE else "")
    return WorkflowResult(
        success=True,
        message=(
            f"Created a refund review workbook for {len(report):,} account(s). "
            f"{source_note}"
            "This workflow does not approve or issue refunds."
        ),
        output_path=created_file,
    )
