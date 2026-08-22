"""Command-line entry point for the Textbook Brokers transformation."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path


REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
if str(REPOSITORY_ROOT) not in sys.path:
    sys.path.insert(0, str(REPOSITORY_ROOT))

from data_processing.textbook_brokers.pipeline import (  # noqa: E402
    TransformationError,
    run_transformation,
)


def parse_arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Combine Textbook Brokers Finaid and IA files into a Banner "
            "TSPLOAD CSV file."
        )
    )
    parser.add_argument(
        "--term-code",
        required=True,
        help="Six-digit Banner term code, such as 202680.",
    )
    parser.add_argument(
        "--output",
        required=True,
        type=Path,
        help="Destination path for TSPLOAD.csv.",
    )
    parser.add_argument(
        "source_files",
        nargs="+",
        type=Path,
        help="One or more finaid_*.csv or ia_*.csv source files.",
    )
    return parser.parse_args()


def main() -> int:
    arguments = parse_arguments()

    try:
        result = run_transformation(
            term_code=arguments.term_code,
            output_path=arguments.output,
            source_paths=arguments.source_files,
        )
    except TransformationError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1

    for summary in result.source_summaries:
        print(
            f"Processed [{summary.source_type}] "
            f"{summary.row_count} row(s): {summary.path}"
        )

    print(
        f"Created {result.output_path} with "
        f"{result.total_rows} data row(s)."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
