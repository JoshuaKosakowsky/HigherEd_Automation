"""GUI adapter for the existing refund review download pipeline."""

from __future__ import annotations

from datetime import date
from pathlib import Path

from app.gui.models import WorkflowContext, WorkflowResult
from data_processing.refunds.pipeline import run_refund_download_pipeline
from data_processing.refunds.terms import RefundParameters, validate_term


def run_refund_review(context: WorkflowContext) -> WorkflowResult:
    """Create a refund review from two staff-downloaded Insights files."""
    target_term = validate_term(str(context.parameters["target_term"]))
    transaction_file = Path(context.parameters["transaction_file"])
    context_file = Path(context.parameters["context_file"])
    output_file = Path(context.parameters["output_file"])

    if transaction_file.resolve() == context_file.resolve():
        raise ValueError(
            "The transaction and context downloads must be different files."
        )
    if output_file.exists():
        raise ValueError(
            "The output workbook already exists. Choose a new filename so an "
            "earlier review is not overwritten."
        )

    created_file, report = run_refund_download_pipeline(
        parameters=RefundParameters(
            target_term=target_term,
            run_date=date.today(),
        ),
        transaction_file=transaction_file,
        context_file=context_file,
        output_file=output_file,
    )

    return WorkflowResult(
        success=True,
        message=(
            f"Created a refund review workbook for {len(report):,} account(s). "
            "This workflow does not approve or issue refunds."
        ),
        output_path=created_file,
    )
