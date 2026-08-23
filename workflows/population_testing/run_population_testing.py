from __future__ import annotations

import argparse
from pathlib import Path


PROJECT_ROOT = (
    Path(__file__)
    .resolve()
    .parents[2]
)

from data_processing.population_testing.config import (
    DEFAULT_INPUT_FILE,
    DEFAULT_OUTPUT_FILE,
    DEFAULT_RANDOM_SEED,
    DEFAULT_SAMPLE_FRACTION,
    DEFAULT_STAFF_NAMES,
    PopulationTestingConfig,
)
from data_processing.population_testing.pipeline import (
    run_population_testing_pipeline,
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Create population-testing buckets, "
            "samples, and staff assignments."
        )
    )

    parser.add_argument(
        "--input-file",
        type=Path,
        default=(
            PROJECT_ROOT
            / DEFAULT_INPUT_FILE
        ),
    )

    parser.add_argument(
        "--output-file",
        type=Path,
        default=(
            PROJECT_ROOT
            / DEFAULT_OUTPUT_FILE
        ),
    )

    parser.add_argument(
        "--sheet-name",
        default=0,
        help=(
            "Source worksheet name. The first "
            "worksheet is used by default."
        ),
    )

    parser.add_argument(
        "--sample-percent",
        type=float,
        default=(
            DEFAULT_SAMPLE_FRACTION * 100
        ),
        help=(
            "Percentage selected from every regular "
            "bucket. The default is "
            f"{DEFAULT_SAMPLE_FRACTION * 100:g}."
        ),
    )

    parser.add_argument(
        "--staff",
        nargs="*",
        default=list(DEFAULT_STAFF_NAMES),
        help=(
            "Staff names receiving testing "
            "assignments."
        ),
    )

    parser.add_argument(
        "--random-seed",
        type=int,
        default=DEFAULT_RANDOM_SEED,
    )

    return parser.parse_args()


def main() -> int:
    args = parse_args()

    sample_fraction = (
        args.sample_percent / 100
    )

    if str(args.sheet_name).isdigit():
        sheet_name = int(
            args.sheet_name
        )
    else:
        sheet_name = args.sheet_name

    config = PopulationTestingConfig(
        input_file=args.input_file,
        output_file=args.output_file,
        sheet_name=sheet_name,
        sample_fraction=sample_fraction,
        staff_names=tuple(args.staff),
        random_seed=args.random_seed,
    )

    output_file = (
        run_population_testing_pipeline(
            config
        )
    )

    print(
        "Population testing workbook created: "
        f"{output_file}"
    )

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
