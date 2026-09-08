from __future__ import annotations

import argparse
from datetime import date, datetime
from pathlib import Path

from dotenv import load_dotenv

from data_processing.refunds.extract import ExtractSettings
from data_processing.refunds.pipeline import (
    run_refund_download_pipeline,
    run_refund_pipeline,
)
from data_processing.refunds.terms import RefundParameters, derive_target_term, validate_term
from shared.insights.config import InsightsSettings
from shared.insights.session_auth import build_authenticated_client


REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
REFUND_QUERY_DIRECTORY = REPOSITORY_ROOT / "query" / "AR" / "refunds"
TRANSACTION_TEMPLATE = REFUND_QUERY_DIRECTORY / "refund_transactions_extract.sql"
CONTEXT_TEMPLATE = REFUND_QUERY_DIRECTORY / "refund_context_extract.sql"


def _iso_date(value: str) -> date:
    try:
        return date.fromisoformat(value)
    except ValueError as error:
        raise argparse.ArgumentTypeError("Date must use YYYY-MM-DD.") from error


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Extract simple Banner account rows from Insights, calculate refund "
            "allocation locally, and create the refund review workbook."
        )
    )
    parser.add_argument("--target-term", type=validate_term)
    parser.add_argument("--previous-term", type=validate_term)
    parser.add_argument("--run-date", type=_iso_date, default=date.today())
    parser.add_argument(
        "--batch-count",
        type=int,
        default=20,
        help="Number of PIDM extraction batches (default: 20).",
    )
    parser.add_argument(
        "--cwid",
        help="Run one account for validation. The value is not written to logs.",
    )
    parser.add_argument("--extract-dir", type=Path)
    parser.add_argument("--output-file", type=Path)
    parser.add_argument(
        "--transactions-file",
        type=Path,
        help="XLSX or CSV downloaded from refund_transactions_manual.sql.",
    )
    parser.add_argument(
        "--context-file",
        type=Path,
        help="XLSX or CSV downloaded from refund_context_manual.sql.",
    )
    parser.add_argument(
        "--resume",
        action="store_true",
        help="Reuse completed CSV batches in the matching extract directory.",
    )
    parser.add_argument(
        "--offline",
        action="store_true",
        help="Use an already-complete extract directory without contacting Insights.",
    )
    parser.add_argument(
        "--browser",
        choices=["edge", "chrome"],
        default="edge",
        help="Browser used for Insights SSO when no daily session is cached.",
    )
    parser.add_argument("--fresh-login", action="store_true")
    return parser


def main() -> int:
    parser = build_parser()
    arguments = parser.parse_args()
    manual_downloads = bool(arguments.transactions_file or arguments.context_file)
    if manual_downloads and not (
        arguments.transactions_file and arguments.context_file
    ):
        parser.error("--transactions-file and --context-file must be supplied together.")
    if manual_downloads and (arguments.offline or arguments.resume):
        parser.error("Manual download files cannot be combined with --offline or --resume.")
    if manual_downloads and arguments.cwid:
        parser.error(
            "For manual downloads, set cwid_filter in both manual SQL files "
            "instead of using --cwid."
        )
    run_date = arguments.run_date
    target_term = arguments.target_term or derive_target_term(run_date)
    batch_count = 1 if arguments.cwid else arguments.batch_count
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    extract_directory = arguments.extract_dir or (
        REPOSITORY_ROOT / "data" / "refunds" / f"extract_{target_term}"
    )
    output_file = arguments.output_file or (
        REPOSITORY_ROOT / "data" / "refunds" / f"refund_review_{target_term}_{timestamp}.xlsx"
    )
    parameters = RefundParameters(
        target_term=target_term,
        previous_term_override=arguments.previous_term,
        run_date=run_date,
    )
    extract_settings = ExtractSettings(
        target_term=target_term,
        batch_count=batch_count,
        extract_directory=extract_directory,
        cwid=arguments.cwid,
        resume=arguments.resume,
        run_date=run_date,
    )

    print(f"Target term: {target_term}")
    print(f"Run date: {run_date.isoformat()}")
    if not manual_downloads:
        print(f"Extraction batches: {batch_count}")
        print(f"Extract directory: {extract_directory}")
    client = None
    if not manual_downloads and not arguments.offline:
        load_dotenv(REPOSITORY_ROOT / ".env")
        settings = InsightsSettings.from_environment()
        print(f"Insights environment: {settings.environment} (read only)")
        client, authentication_method = build_authenticated_client(
            settings,
            browser=arguments.browser,
            force_login=arguments.fresh_login,
        )
        print(f"Authentication: {authentication_method}")

    try:
        if manual_downloads:
            print("Input mode: manual Insights downloads")
            path, report = run_refund_download_pipeline(
                parameters=parameters,
                transaction_file=arguments.transactions_file,
                context_file=arguments.context_file,
                output_file=output_file,
                progress=print,
            )
        else:
            path, report = run_refund_pipeline(
                parameters=parameters,
                extract_settings=extract_settings,
                transaction_template_path=TRANSACTION_TEMPLATE,
                context_template_path=CONTEXT_TEMPLATE,
                output_file=output_file,
                client=client,
                offline=arguments.offline,
                progress=print,
            )
    finally:
        if client is not None:
            client.close()

    print()
    print(f"Accounts in refund review: {len(report):,}")
    print(f"Workbook: {path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
