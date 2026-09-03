from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

import pandas as pd

from .allocation import allocate_refunds
from .export import export_refund_report
from .extract import ExtractSettings, SQLClient, extract_refund_data, read_refund_extracts
from .ingest import read_refund_download
from .terms import RefundParameters


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
) -> tuple[Path, pd.DataFrame]:
    """Extract Banner rows, calculate locally, and export the review workbook."""
    if offline:
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
        )

    if progress:
        progress(
            f"Calculating refunds locally from {len(transactions):,} transactions "
            f"for {transactions['pidm'].nunique() if not transactions.empty else 0:,} accounts..."
        )
    report = allocate_refunds(transactions, context, parameters)
    return export_refund_report(report, output_file), report


def run_refund_download_pipeline(
    *,
    parameters: RefundParameters,
    transaction_file: Path,
    context_file: Path,
    output_file: Path,
    progress: Callable[[str], None] | None = None,
) -> tuple[Path, pd.DataFrame]:
    """Calculate the report from two manually downloaded Insights results."""
    transactions = read_refund_download(
        transaction_file,
        label="Transaction",
        expected_target_term=parameters.target_term,
    )
    context = read_refund_download(
        context_file,
        label="Context",
        expected_target_term=parameters.target_term,
    )
    if progress:
        progress(
            f"Calculating refunds locally from {len(transactions):,} transactions "
            f"for {transactions['pidm'].nunique() if not transactions.empty else 0:,} accounts..."
        )
    report = allocate_refunds(transactions, context, parameters)
    return export_refund_report(report, output_file), report
