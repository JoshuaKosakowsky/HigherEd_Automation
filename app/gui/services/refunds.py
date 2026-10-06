"""GUI adapter for the existing manual and SQL refund review pipelines."""

from __future__ import annotations

from datetime import date
import logging
from pathlib import Path
from tempfile import TemporaryDirectory

from app.gui.models import WorkflowContext, WorkflowMode, WorkflowResult
from app.gui.services.access import get_current_login, load_access_configuration
from data_processing.refunds.extract import ExtractSettings, QUERY_DIRECTORY
from data_processing.refunds.pipeline import run_refund_download_pipeline, run_refund_pipeline
from data_processing.refunds.terms import RefundParameters, validate_term
from shared.insights.config import load_department_profiles
from shared.insights.session_auth import build_authenticated_client
from shared.mines_paths import get_shared_gui_access_path


def run_refund_review(context: WorkflowContext) -> WorkflowResult:
    """Create a review using the existing download or batched SQL pipeline."""
    if context.cancellation:
        context.cancellation.check()
    context.progress.report("Validating Refund Review inputs")
    source = context.parameters.get("refund_source", "manual")
    if source not in ("manual", "sql"):
        raise ValueError("Choose manual files or Insights SQL for Refund Review.")
    target_term = validate_term(str(context.parameters["target_term"]))
    output_file = Path(context.parameters["output_file"])

    if output_file.exists():
        raise ValueError(
            "The output workbook already exists. Choose a new filename so an "
            "earlier review is not overwritten."
        )

    parameters = RefundParameters(target_term=target_term, run_date=date.today())
    if source == "sql":
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
        with client, TemporaryDirectory(prefix="refund-review-") as directory:
            created_file, report = run_refund_pipeline(
                parameters=parameters,
                extract_settings=ExtractSettings(
                    target_term=target_term,
                    batch_count=20,
                    extract_directory=Path(directory),
                    run_date=parameters.run_date,
                ),
                transaction_template_path=QUERY_DIRECTORY / "refund_transactions_extract.sql",
                context_template_path=QUERY_DIRECTORY / "refund_context_extract.sql",
                output_file=output_file,
                client=client,
                progress=logging.getLogger("highered_automation.gui").info,
                cancellation=context.cancellation,
                progress_reporter=context.progress,
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
            progress=logging.getLogger("highered_automation.gui").info,
            progress_reporter=context.progress,
        )

    return WorkflowResult(
        success=True,
        message=(
            f"Created a refund review workbook for {len(report):,} account(s). "
            "This workflow does not approve or issue refunds."
        ),
        output_path=created_file,
    )
