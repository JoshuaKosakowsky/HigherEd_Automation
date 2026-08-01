from __future__ import annotations

from pathlib import Path

from openpyxl import Workbook
from openpyxl.styles import Alignment

from data_processing.shared.files import ensure_dir

from data_processing.shared.xlsx_output_format import (
    write_table_sheet as _write_table_sheet,
)

from .analysis import (
    ChargeAverage,
    DetailCodeTotal,
    FiscalYearAnalysis,
    ReportingGroupTotal,
    TermDetailCodeTotal,
    TermGroupTotal,
)


def _write_definitions_sheet(
    workbook: Workbook,
) -> None:
    definitions = [
        (
            "Fiscal Year",
            "Taken from the workbook filename. "
            "TGIACCD_fy26.xlsx is FY2026.",
        ),
        (
            "Total Amount by Detail Code",
            "Sum of the exported Amount column without "
            "changing its sign.",
        ),
        (
            "Signed AR Effect",
            "Charge codes (type C) add Amount; payment/credit "
            "codes (type P) subtract Amount.",
        ),
        (
            "Gross AR",
            "Sum of positive values in the exported Balance "
            "column. Credit balances are excluded.",
        ),
        (
            "Credit Balances",
            "Sum of negative values in the exported Balance "
            "column. The result remains negative.",
        ),
        (
            "Net AR",
            "Sum of every exported Balance value; equivalent "
            "to Gross AR plus Credit Balances.",
        ),
        (
            "Average Positive Balance",
            "Gross AR divided by the distinct students who "
            "have at least one positive Balance row.",
        ),
        (
            "Average Net Balance - All Students",
            "Net AR divided by every distinct student in the "
            "fiscal-year export.",
        ),
        (
            "Category Charge Amount",
            "Sum of Amount for detail codes in the category "
            "with type C. Negative charge reversals reduce "
            "this total.",
        ),
        (
            "Category Payment/Credit Amount",
            "Sum of Amount for detail codes in the category "
            "with type P. Negative reversals reduce this total.",
        ),
        (
            "Net Category Amount",
            "Category Charge Amount minus Category Payment/"
            "Credit Amount. Category comes from detail_codes.json.",
        ),
        (
            "Mean per Student with Activity",
            "Net Category Amount divided by distinct students "
            "who had at least one C or P transaction in that "
            "category or reporting group.",
        ),
        (
            "Mean per All Students",
            "Net Category Amount divided by every distinct "
            "student appearing in the fiscal-year export. "
            "Students without that charge are effectively zero.",
        ),
        (
            "Room and Board",
            "Combined charge categories HOU (housing) and "
            "MEA (meal plans).",
        ),
        (
            "Reporting Group Totals",
            "Annual summed activity for Tuition, Room and "
            "Board, Fees, and the exact WOFF and BDRC detail "
            "codes. WOFF and BDRC are not grouped with other "
            "codes from their broader Banner categories.",
        ),
        (
            "Reporting Group Totals by Term",
            "The same Tuition, Room and Board, Fees, and exact "
            "WOFF totals split by the exported Term value. "
            "Blank Term values appear as (No Term).",
        ),
        (
            "Collections by Term",
            "Transaction count, distinct students, and Amount "
            "totals for the exact COLL and PCCS detail codes, "
            "split by the exported Term value. Terms appear "
            "only when COLL or PCCS activity exists.",
        ),
        (
            "Gross Tuition Charges",
            "Sum of Amount for category TUI detail codes with "
            "type C.",
        ),
        (
            "Tuition Offsets",
            "Sum of Amount for category TUI detail codes with "
            "type P.",
        ),
        (
            "Net Tuition Revenue",
            "Gross Tuition Charges minus Tuition Offsets.",
        ),
        (
            "WOFF Transactions",
            "Number of transaction rows with detail code WOFF.",
        ),
        (
            "WOFF Students",
            "Distinct students with at least one WOFF row.",
        ),
        (
            "WOFF Amount",
            "Sum of the exported Amount for WOFF rows. Because "
            "WOFF is type P, its Signed AR Effect is negative.",
        ),
         (
            "BDRC Transactions",
            "Number of transaction rows with exact detail "
            "code BDRC (Bad Debt Recovery).",
        ),
        (
            "BDRC Students",
            "Distinct students with at least one BDRC "
            "transaction row.",
        ),
        (
            "BDRC Amount",
            "Sum of Amount for exact detail code BDRC. Its "
            "configured type determines whether it appears "
            "as a charge or payment/credit.",
        ),
    ]

    _write_table_sheet(
        workbook,
        sheet_name="Definitions",
        table_name="DefinitionsTable",
        headers=["Metric", "Definition"],
        rows=definitions,
    )

    worksheet = workbook["Definitions"]
    worksheet.column_dimensions["A"].width = 35
    worksheet.column_dimensions["B"].width = 95

    for cell in worksheet["B"][1:]:
        cell.alignment = Alignment(
            wrap_text=True,
            vertical="top",
        )


def export_trends_workbook(
    *,
    fiscal_year_results: list[FiscalYearAnalysis],
    detail_code_results: list[DetailCodeTotal],
    group_average_results: list[ChargeAverage],
    reporting_group_total_results: list[
        ReportingGroupTotal
    ],
    category_average_results: list[ChargeAverage],
    term_group_total_results: list[TermGroupTotal],
    term_collection_total_results: list[
        TermDetailCodeTotal
    ],
    output_file: Path,
) -> Path:
    """
    Export the fiscal-year summaries and validation checks.
    """
    ensure_dir(output_file.parent)

    workbook = Workbook()
    workbook.remove(workbook.active)

    summary_headers = [
        "Fiscal Year",
        "Source File",
        "Rows",
        "Students in File",
        "Students with Positive AR",
        "Gross AR",
        "Credit Balances",
        "Net AR",
        "Average Positive Balance",
        "Average Net Balance - All Students",
        "Charge Activity",
        "Payment/Credit Activity",
        "Net AR Activity",
        "Gross Tuition Charges",
        "Tuition Offsets",
        "Net Tuition Revenue",
        "WOFF Transactions",
        "WOFF Students",
        "WOFF Amount",
    ]

    summary_rows = [
        (
            result.fiscal_year,
            result.source_file,
            result.row_count,
            result.student_count,
            result.positive_ar_student_count,
            result.gross_ar,
            result.credit_balances,
            result.net_ar,
            result.average_positive_balance,
            result.average_net_balance_all_students,
            result.charge_activity,
            result.payment_credit_activity,
            result.net_ar_activity,
            result.gross_tuition_charges,
            result.tuition_offsets,
            result.net_tuition_revenue,
            result.writeoff_count,
            result.writeoff_student_count,
            result.writeoff_amount,
        )
        for result in fiscal_year_results
    ]

    _write_table_sheet(
        workbook,
        sheet_name="Summary",
        table_name="FiscalYearSummaryTable",
        headers=summary_headers,
        rows=summary_rows,
        currency_headers={
            "Gross AR",
            "Credit Balances",
            "Net AR",
            "Average Positive Balance",
            "Average Net Balance - All Students",
            "Charge Activity",
            "Payment/Credit Activity",
            "Net AR Activity",
            "Gross Tuition Charges",
            "Tuition Offsets",
            "Net Tuition Revenue",
            "WOFF Amount",
        },
        count_headers={
            "Rows",
            "Students in File",
            "Students with Positive AR",
            "WOFF Transactions",
            "WOFF Students",
        },
    )

    charge_average_headers = [
        "Fiscal Year",
        "Charge Group",
        "Included Categories",
        "Category Transactions",
        "Charge Transactions",
        "Payment/Credit Transactions",
        "Students with Category Activity",
        "All Students in File",
        "Charge Amount",
        "Payment/Credit Amount",
        "Net Category Amount",
        "Mean per Student with Activity",
        "Mean per All Students",
    ]

    def charge_average_rows(
        results: list[ChargeAverage],
    ) -> list[tuple[object, ...]]:
        return [
            (
                result.fiscal_year,
                result.label,
                result.category_codes,
                result.transaction_count,
                result.charge_transaction_count,
                result.payment_credit_transaction_count,
                result.student_count_with_activity,
                result.all_student_count,
                result.charge_amount,
                result.payment_credit_amount,
                result.net_category_amount,
                result.average_per_student_with_activity,
                result.average_per_all_students,
            )
            for result in results
        ]

    average_currency_headers = {
        "Charge Amount",
        "Payment/Credit Amount",
        "Net Category Amount",
        "Mean per Student with Activity",
        "Mean per All Students",
    }
    average_count_headers = {
        "Category Transactions",
        "Charge Transactions",
        "Payment/Credit Transactions",
        "Students with Category Activity",
        "All Students in File",
    }

    tuition_average_results = [
        result
        for result in group_average_results
        if result.label == "Tuition"
    ]

    _write_table_sheet(
        workbook,
        sheet_name="TUI Averages",
        table_name="TuitionAveragesTable",
        headers=charge_average_headers,
        rows=charge_average_rows(
            tuition_average_results
        ),
        currency_headers=average_currency_headers,
        count_headers=average_count_headers,
    )

    _write_table_sheet(
        workbook,
        sheet_name="Reporting Group Averages",
        table_name="ChargeGroupAveragesTable",
        headers=charge_average_headers,
        rows=charge_average_rows(
            group_average_results
        ),
        currency_headers=average_currency_headers,
        count_headers=average_count_headers,
    )

    total_headers = [
        "Fiscal Year",
        "Reporting Group",
        "Included Categories or Detail Codes",
        "Transactions",
        "Charge Transactions",
        "Payment/Credit Transactions",
        "Students with Group Activity",
        "All Students in File",
        "Charge Amount",
        "Payment/Credit Amount",
        "Net Amount",
    ]

    total_rows = [
        (
            result.fiscal_year,
            result.label,
            result.included_codes,
            result.transaction_count,
            result.charge_transaction_count,
            result.payment_credit_transaction_count,
            result.student_count_with_activity,
            result.all_student_count,
            result.charge_amount,
            result.payment_credit_amount,
            result.net_amount,
        )
        for result in reporting_group_total_results
    ]

    _write_table_sheet(
        workbook,
        sheet_name="Reporting Group Totals",
        table_name="ReportingGroupTotalsTable",
        headers=total_headers,
        rows=total_rows,
        currency_headers={
            "Charge Amount",
            "Payment/Credit Amount",
            "Net Amount",
        },
        count_headers={
            "Transactions",
            "Charge Transactions",
            "Payment/Credit Transactions",
            "Students with Group Activity",
            "All Students in File",
        },
    )

    term_total_headers = [
        "Fiscal Year",
        "Term",
        "Reporting Group",
        "Included Categories or Detail Codes",
        "Transactions",
        "Charge Transactions",
        "Payment/Credit Transactions",
        "Students with Group Activity",
        "Students in Term",
        "Charge Amount",
        "Payment/Credit Amount",
        "Net Amount",
    ]

    term_total_rows = [
        (
            result.fiscal_year,
            result.term,
            result.label,
            result.included_codes,
            result.transaction_count,
            result.charge_transaction_count,
            result.payment_credit_transaction_count,
            result.student_count_with_activity,
            result.students_in_term,
            result.charge_amount,
            result.payment_credit_amount,
            result.net_amount,
        )
        for result in term_group_total_results
    ]

    _write_table_sheet(
        workbook,
        sheet_name="Reporting Group Totals by Term",
        table_name="ReportingGroupTermTotalsTable",
        headers=term_total_headers,
        rows=term_total_rows,
        currency_headers={
            "Charge Amount",
            "Payment/Credit Amount",
            "Net Amount",
        },
        count_headers={
            "Transactions",
            "Charge Transactions",
            "Payment/Credit Transactions",
            "Students with Group Activity",
            "Students in Term",
        },
    )

    collection_headers = [
        "Fiscal Year",
        "Term",
        "Detail Code",
        "Description",
        "Type",
        "Category",
        "Transaction Count",
        "Distinct Students",
        "Total Amount",
        "Signed AR Effect",
    ]

    collection_rows = [
        (
            result.fiscal_year,
            result.term,
            result.detail_code,
            result.description,
            result.code_type,
            result.category,
            result.transaction_count,
            result.student_count,
            result.total_amount,
            result.signed_ar_effect,
        )
        for result in term_collection_total_results
    ]

    _write_table_sheet(
        workbook,
        sheet_name="Collections by Term",
        table_name="CollectionsByTermTable",
        headers=collection_headers,
        rows=collection_rows,
        currency_headers={
            "Total Amount",
            "Signed AR Effect",
        },
        count_headers={
            "Transaction Count",
            "Distinct Students",
        },
    )

    category_headers = (
        charge_average_headers.copy()
    )
    category_headers[1] = "Banner Category"

    _write_table_sheet(
        workbook,
        sheet_name="Category Averages",
        table_name="CategoryAveragesTable",
        headers=category_headers,
        rows=charge_average_rows(
            category_average_results
        ),
        currency_headers=average_currency_headers,
        count_headers=average_count_headers,
    )

    detail_headers = [
        "Fiscal Year",
        "Detail Code",
        "Description",
        "Type",
        "Category",
        "Transaction Count",
        "Total Amount",
        "Signed AR Effect",
    ]

    detail_rows = [
        (
            result.fiscal_year,
            result.detail_code,
            result.description,
            result.code_type,
            result.category,
            result.transaction_count,
            result.total_amount,
            result.signed_ar_effect,
        )
        for result in detail_code_results
    ]

    _write_table_sheet(
        workbook,
        sheet_name="Detail Code Totals",
        table_name="DetailCodeTotalsTable",
        headers=detail_headers,
        rows=detail_rows,
        currency_headers={
            "Total Amount",
            "Signed AR Effect",
        },
        count_headers={
            "Transaction Count",
        },
    )

    check_headers = [
        "Fiscal Year",
        "Source File",
        "Status",
        "Rows",
        "Mapped Rows",
        "Unmapped Rows",
        "Unmapped Detail Codes",
    ]

    check_rows = [
        (
            result.fiscal_year,
            result.source_file,
            (
                "PASS"
                if (
                    result.unmapped_row_count == 0
                    and result.mapped_row_count
                    == result.row_count
                )
                else "FAIL"
            ),
            result.row_count,
            result.mapped_row_count,
            result.unmapped_row_count,
            ", ".join(
                sorted(
                    result.unmapped_detail_codes
                )
            ),
        )
        for result in fiscal_year_results
    ]

    _write_table_sheet(
        workbook,
        sheet_name="Checks",
        table_name="QualityChecksTable",
        headers=check_headers,
        rows=check_rows,
        count_headers={
            "Rows",
            "Mapped Rows",
            "Unmapped Rows",
        },
    )

    _write_definitions_sheet(
        workbook
    )

    workbook.calculation.fullCalcOnLoad = True
    workbook.calculation.forceFullCalc = True
    workbook.save(output_file)

    return output_file