from __future__ import annotations

import argparse
from pathlib import Path


PROJECT_ROOT = (
    Path(__file__)
    .resolve()
    .parents[2]
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
            "Analyze fiscal-year TGIACCD workbooks or checked Insights SQL extracts."
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

    parser.add_argument("--source", choices=("files", "sql"), default="files")
    parser.add_argument("--first-fiscal-year", type=int)
    parser.add_argument("--last-fiscal-year", type=int)
    parser.add_argument("--extract-dir", type=Path)
    parser.add_argument("--page-size", type=int, default=1000)
    parser.add_argument("--confirm-prod", action="store_true",
                        help="Confirm read-only PROD Insights extraction and saving account data locally.")
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

    if args.source == "sql":
        from app.gui.models import WorkflowMode
        from data_processing.trends.extract import TrendsExtractSettings, run_sql_trends_pipeline
        from shared.insights.config import load_department_profiles
        from shared.insights.session_auth import build_authenticated_client
        from shared.progress import ProgressReporter

        if not args.confirm_prod:
            raise ValueError("SQL extraction requires --confirm-prod.")
        if args.first_fiscal_year is None or args.last_fiscal_year is None:
            raise ValueError("SQL extraction requires first and last fiscal years.")
        settings = TrendsExtractSettings(args.first_fiscal_year, args.last_fiscal_year,
            args.extract_dir or (config.output_file.parent / f"{config.output_file.stem}_sources"),
            page_size=args.page_size)
        if config.output_file.suffix.lower() != ".xlsx" or config.output_file.exists() or settings.extract_directory.exists():
            raise ValueError("Choose a new output filename and extract directory.")
        profile = load_department_profiles()[WorkflowMode.PRODUCTION.value]
        if profile is None:
            raise ValueError("PROD Insights is not configured.")
        try:
            client, _ = build_authenticated_client(profile.settings, browser="chrome",
                experience_url=profile.experience_url, use_saved_mines_login=True)
        except Exception:
            raise ValueError("Could not connect to PROD Insights. Check configuration and browser sign-in.") from None
        with client:
            output_file = run_sql_trends_pipeline(client, settings, config,
                progress=ProgressReporter(lambda update: print(update.stage, flush=True)))
    else:
        output_file = run_trends_pipeline(config)

    print(
        "Fiscal-year TGIACCD analysis created: "
        f"{output_file}"
    )

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
