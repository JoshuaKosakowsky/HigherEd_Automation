from __future__ import annotations

import argparse
import sys
from pathlib import Path


PROJECT_ROOT = (
    Path(__file__)
    .resolve()
    .parents[2]
)

if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(
        0,
        str(PROJECT_ROOT),
    )


from data_processing.trends.config import (
    DEFAULT_DETAIL_CODES_FILE,
    DEFAULT_FILE_PATTERN,
    DEFAULT_INPUT_DIR,
    DEFAULT_OUTPUT_FILE,
    PIPELINE_VERSION,
    TrendsConfig,
)
from data_processing.trends.pipeline import (
    run_trends_pipeline,
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Analyze fiscal-year TGIACCD workbooks."
        )
    )

    parser.add_argument(
        "--input-dir",
        type=Path,
        default=PROJECT_ROOT / DEFAULT_INPUT_DIR,
    )

    parser.add_argument(
        "--detail-codes-file",
        type=Path,
        default=(
            PROJECT_ROOT
            / DEFAULT_DETAIL_CODES_FILE
        ),
    )

    parser.add_argument(
        "--output-file",
        type=Path,
        default=PROJECT_ROOT / DEFAULT_OUTPUT_FILE,
    )

    parser.add_argument(
        "--file-pattern",
        default=DEFAULT_FILE_PATTERN,
    )

    parser.add_argument(
        "--allow-unmapped-detail-codes",
        action="store_true",
        help=(
            "Create the report even if an export contains "
            "codes missing from detail_codes.json."
        ),
    )

    return parser.parse_args()


def main() -> int:
    args = parse_args()

    print(
        "TGIACCD trends pipeline version: "
        f"{PIPELINE_VERSION}"
    )

    config = TrendsConfig(
        input_dir=args.input_dir,
        detail_codes_file=args.detail_codes_file,
        output_file=args.output_file,
        file_pattern=args.file_pattern,
        strict_detail_codes=(
            not args.allow_unmapped_detail_codes
        ),
    )

    output_file = run_trends_pipeline(
        config
    )

    print(
        "Fiscal-year TGIACCD analysis created: "
        f"{output_file}"
    )

    return 0


if __name__ == "__main__":
    raise SystemExit(main())