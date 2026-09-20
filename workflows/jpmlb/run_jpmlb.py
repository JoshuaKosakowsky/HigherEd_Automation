"""Command-line entry point for the JPMLB CSV-to-XLSX transformation."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from data_processing.jpmlb import JPMLBTransformationError, transform_jpmlb_csv


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Convert a Transaction Results CSV into a JPMLB workbook."
    )
    parser.add_argument("--input", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    return parser


def main(argv: list[str] | None = None) -> int:
    arguments = build_parser().parse_args(argv)

    try:
        result = transform_jpmlb_csv(
            source_path=arguments.input,
            output_path=arguments.output,
        )
    except JPMLBTransformationError as exc:
        print(str(exc), file=sys.stderr)
        return 1
    except OSError as exc:
        print(f"JPMLB workbook could not be written: {exc}", file=sys.stderr)
        return 1

    print(
        f"Created {result.output_path} from {result.data_row_count} data rows."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
