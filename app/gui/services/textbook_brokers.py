"""GUI adapter for the existing local Textbook Brokers transformation."""

from __future__ import annotations

from pathlib import Path

from data_processing.textbook_brokers.pipeline import (
    TransformationError,
    run_transformation,
)

from app.gui.models import WorkflowContext, WorkflowResult


def run_textbook_brokers(context: WorkflowContext) -> WorkflowResult:
    """Create a Banner-ready TSPLOAD file from staff-selected local sources."""
    try:
        result = run_transformation(
            term_code=str(context.parameters["term_code"]),
            output_path=Path(context.parameters["output_file"]),
            source_paths=tuple(context.parameters["source_files"]),
        )
    except TransformationError as error:
        # These are safe business/input validation messages intended for staff.
        raise ValueError(str(error)) from error

    return WorkflowResult(
        success=True,
        message=(
            f"Created TSPLOAD.csv from {len(result.source_summaries)} file(s) "
            f"containing {result.total_rows:,} row(s)."
        ),
        output_path=result.output_path,
    )
