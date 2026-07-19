from pathlib import Path

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
) -> Path:
    """
    Run the complete population-testing workflow.
    """
    raw_df = read_population_workbook(
        config.input_file,
        sheet_name=config.sheet_name,
    )

    clean_df = clean_population(
        raw_df
    )

    bucketed_df = assign_population_buckets(
        clean_df
    )

    sampled_df = select_testing_sample(
        bucketed_df,
        sample_fraction=config.sample_fraction,
        random_seed=config.random_seed,
    )

    assigned_df = assign_testing_staff(
        sampled_df,
        staff_names=config.staff_names,
        random_seed=config.random_seed,
    )

    environment_df = assign_testing_environments(
        assigned_df,
        staff_names=config.staff_names,
        random_seed=config.random_seed,
    )

    validation_df = validate_population_results(
        environment_df,
        sample_fraction=config.sample_fraction,
        staff_names=config.staff_names,
    )

    return export_population_workbook(
        environment_df,
        validation_df=validation_df,
        output_file=config.output_file,
        staff_names=config.staff_names,
    )