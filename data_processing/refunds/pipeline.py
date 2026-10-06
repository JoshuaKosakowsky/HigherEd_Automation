from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from tempfile import TemporaryDirectory
from time import perf_counter

from shared.cancellation import CancellationToken
from shared.progress import ProgressReporter

import pandas as pd

from .allocation import allocate_refunds
from .export import export_refund_report
from .extract import ExtractSettings, SQLClient, extract_refund_data, read_refund_extracts
from .ingest import read_refund_download
from .terms import RefundParameters


def _create_review(
    transactions: pd.DataFrame, context: pd.DataFrame,
    parameters: RefundParameters, output_file: Path,
    progress: Callable[[str], None] | None,
    cancellation: CancellationToken | None,
    progress_reporter: ProgressReporter | None = None,
) -> tuple[Path, pd.DataFrame]:
    if cancellation:
        cancellation.check()
    if progress:
        progress(
            f"Calculating refunds locally from {len(transactions):,} transactions "
            f"for {transactions['pidm'].nunique() if not transactions.empty else 0:,} accounts..."
        )
    started = perf_counter()
    report = allocate_refunds(transactions, context, parameters, cancellation=cancellation,
                              progress_reporter=progress_reporter)
    if progress:
        progress(f"Refund calculation completed in {perf_counter() - started:.1f}s.")
    if cancellation:
        cancellation.check()
    output_file.parent.mkdir(parents=True, exist_ok=True)
    started = perf_counter()
    # Stage on the same filesystem: cancellation or a failed save leaves no
    # partial workbook under the staff-selected output filename.
    with TemporaryDirectory(prefix=".refund-review-", dir=output_file.parent) as directory:
        staged = export_refund_report(report, Path(directory) / output_file.name, cancellation=cancellation,
                                      progress_reporter=progress_reporter)

        def publish() -> None:
            if cancellation and output_file.exists():
                raise ValueError("The output workbook already exists. Choose a new filename.")
            staged.replace(output_file)

        if progress_reporter:
            progress_reporter.report("Publishing completed refund workbook")
        if cancellation:
            cancellation.publish(publish)
        else:
            publish()
    if progress:
        progress(f"Refund workbook created in {perf_counter() - started:.1f}s.")
    return output_file, report


def run_refund_pipeline(
    *,
    parameters: RefundParameters,
    extract_settings: ExtractSettings,
    transaction_template_path: Path,
    context_template_path: Path,
    output_file: Path,
    client: SQLClient | None = None,
    offline: bool = False,
    progress: Callable[[str], None] | None = None,
    cancellation: CancellationToken | None = None,
    progress_reporter: ProgressReporter | None = None,
) -> tuple[Path, pd.DataFrame]:
    """Extract Banner rows, calculate locally, and export the review workbook."""
    if cancellation:
        cancellation.check()
    started = perf_counter()
    if offline:
        if progress_reporter:
            progress_reporter.report("Reading cached refund extracts")
        transactions, context = read_refund_extracts(extract_settings)
    else:
        if client is None:
            raise ValueError("An Insights client is required unless --offline is used.")
        transactions, context = extract_refund_data(
            client,
            extract_settings,
            transaction_template_path=transaction_template_path,
            context_template_path=context_template_path,
            progress=progress,
            cancellation=cancellation,
            progress_reporter=progress_reporter,
        )

    if progress:
        progress(f"Refund extraction completed in {perf_counter() - started:.1f}s.")
    return _create_review(transactions, context, parameters, output_file, progress, cancellation, progress_reporter)


def run_refund_download_pipeline(
    *,
    parameters: RefundParameters,
    transaction_file: Path,
    context_file: Path,
    output_file: Path,
    progress: Callable[[str], None] | None = None,
    cancellation: CancellationToken | None = None,
    progress_reporter: ProgressReporter | None = None,
) -> tuple[Path, pd.DataFrame]:
    """Calculate the report from two manually downloaded Insights results."""
    if cancellation:
        cancellation.check()
    if progress_reporter:
        progress_reporter.report("Reading refund transaction download")
    transactions = read_refund_download(
        transaction_file,
        label="Transaction",
        expected_target_term=parameters.target_term,
    )
    if cancellation:
        cancellation.check()
    if progress_reporter:
        progress_reporter.report("Reading refund account-context download")
    context = read_refund_download(
        context_file,
        label="Context",
        expected_target_term=parameters.target_term,
    )
    return _create_review(transactions, context, parameters, output_file, progress, cancellation, progress_reporter)
