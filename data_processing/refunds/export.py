from __future__ import annotations

from pathlib import Path

from openpyxl import Workbook
import pandas as pd

from data_processing.shared.xlsx_output_format import write_table_sheet

from .allocation import REPORT_COLUMNS


CURRENCY_COLUMNS = {
    "full_account_balance",
    "total_refund_amount",
    "student_refund_amount",
    "parent_refund_amount",
    "target_term_fdpl_amount",
    "unused_fdpl_amount",
    "unused_non_fdpl_amount",
    "total_unused_payment_amount",
    "unpaid_charge_amount",
    "previous_term_balance_before_current_payments",
    "prior_terms_balance_before_current_payments",
    "title_iv_applied_to_older_fiscal_years",
    "unrestricted_applied_to_older_terms",
    "original_payment_total",
}

COUNT_COLUMNS = {
    "fdpl_row_count",
    "original_payment_row_count",
    "plus_auth_row_count",
    "negative_source_count",
    "ambiguous_source_pool_count",
}


def export_refund_report(report: pd.DataFrame, output_file: Path) -> Path:
    """Write the refund review using the repository's standard table style."""
    missing = [column for column in REPORT_COLUMNS if column not in report.columns]
    if missing:
        raise ValueError(f"Refund report is missing columns: {', '.join(missing)}")

    workbook = Workbook()
    workbook.remove(workbook.active)
    rows = (
        tuple(None if pd.isna(value) else value for value in row)
        for row in report[REPORT_COLUMNS].itertuples(index=False, name=None)
    )
    write_table_sheet(
        workbook,
        sheet_name="Refund Review",
        table_name="RefundReview",
        headers=REPORT_COLUMNS,
        rows=rows,
        currency_headers=CURRENCY_COLUMNS,
        count_headers=COUNT_COLUMNS,
    )
    worksheet = workbook["Refund Review"]
    deceased_column = REPORT_COLUMNS.index("deceased_date") + 1
    for column in worksheet.iter_cols(
        min_col=deceased_column,
        max_col=deceased_column,
        min_row=2,
    ):
        for cell in column:
            cell.number_format = "mm/dd/yyyy"

    for header in (
        "last_ar_activity_date",
        "account_control_activity_date",
        "ed_activity_date",
        "plus_auth_activity_date",
    ):
        column_number = REPORT_COLUMNS.index(header) + 1
        for column in worksheet.iter_cols(
            min_col=column_number,
            max_col=column_number,
            min_row=2,
        ):
            for cell in column:
                cell.number_format = "mm/dd/yyyy h:mm AM/PM"

    output_file.parent.mkdir(parents=True, exist_ok=True)
    workbook.save(output_file)
    return output_file
