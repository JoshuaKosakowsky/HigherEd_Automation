from pathlib import Path
from shared.progress import ProgressReporter

from .assignment import (
    assign_testing_environments,
    assign_testing_staff,
)
from .buckets import assign_population_buckets
from .clean import clean_population
from .config import PopulationTestingConfig
from .export import export_population_workbook
from .ingest import read_population_workbook
from .sampling import select_testing_sample
from .validate import validate_population_results


def run_population_testing_pipeline(
    config: PopulationTestingConfig,
    *, progress_reporter: ProgressReporter | None = None,
) -> Path:
    """
    Run the complete population-testing workflow.
    """
    stages = (
        "Reading population workbook", "Cleaning population", "Assigning population groups",
        "Selecting testing samples", "Assigning testing staff", "Assigning TEST/PROD environments",
        "Validating population results", "Writing population workbook",
    )

    def stage(index: int) -> None:
        if progress_reporter:
            progress_reporter.report(f"Step {index + 1} of {len(stages)}: {stages[index]}")

    stage(0)
    raw_df = read_population_workbook(
        config.input_file,
        sheet_name=config.sheet_name,
    )

    stage(1)
    clean_df = clean_population(
        raw_df
    )

    stage(2)
    bucketed_df = assign_population_buckets(
        clean_df
    )

    stage(3)
    sampled_df = select_testing_sample(
        bucketed_df,
        sample_fraction=config.sample_fraction,
        random_seed=config.random_seed,
    )

    stage(4)
    assigned_df = assign_testing_staff(
        sampled_df,
        staff_names=config.staff_names,
        random_seed=config.random_seed,
    )

    stage(5)
    environment_df = assign_testing_environments(
        assigned_df,
        staff_names=config.staff_names,
        random_seed=config.random_seed,
    )

    stage(6)
    validation_df = validate_population_results(
        environment_df,
        sample_fraction=config.sample_fraction,
        staff_names=config.staff_names,
    )

    stage(7)
    return export_population_workbook(
        environment_df,
        validation_df=validation_df,
        output_file=config.output_file,
        staff_names=config.staff_names,
    )
