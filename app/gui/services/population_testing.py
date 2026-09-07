"""GUI adapter for the existing Population Testing pipeline."""

from __future__ import annotations

from pathlib import Path

from data_processing.population_testing.config import PopulationTestingConfig
from data_processing.population_testing.pipeline import run_population_testing_pipeline

from app.gui.models import WorkflowContext, WorkflowResult


def run_population_testing(context: WorkflowContext) -> WorkflowResult:
    """Translate staff-facing form values into the existing pipeline config."""
    input_file = Path(context.parameters["input_file"])
    output_file = Path(context.parameters["output_file"])

    if input_file.resolve() == output_file.resolve():
        raise ValueError(
            "The output workbook must be different from the source workbook."
        )

    config = PopulationTestingConfig(
        input_file=input_file,
        output_file=output_file,
        sample_fraction=float(context.parameters["sample_percent"]) / 100,
        staff_names=tuple(context.parameters["staff_names"]),
    )
    created_file = run_population_testing_pipeline(config)

    return WorkflowResult(
        success=True,
        message="The population testing workbook was created successfully.",
        output_path=created_file,
    )
