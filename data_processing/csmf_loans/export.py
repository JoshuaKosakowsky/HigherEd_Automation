"""R1 loan worksheets with confirmed amount adjustments; no full reconciliation."""

from __future__ import annotations

from decimal import Decimal
from math import ceil

from openpyxl import Workbook
from openpyxl.styles import Alignment, Font, PatternFill
from openpyxl.utils import get_column_letter

from data_processing.shared.source_exports import SourceData
from data_processing.shared.xlsx_output_format import (
    CURRENCY_FORMAT, apply_default_font, format_table_columns, style_header_row,
)
from shared.cancellation import CancellationToken
from .balances import OpeningBalances
from .sources import LOANS, SECTIONS, LoanActivity


HEADERS = ["Activity", "Journal Number", "Accounting Date", "Source", "Description",
           "Amount", "Debit/Credit", "Adjusted Amount"]
SUBTOTAL_FILL = PatternFill("solid", fgColor="CFDCE9")


def _append(sheet, values) -> int:
    if sheet.max_row >= 1_048_576:
        raise ValueError("A CSMF worksheet exceeds Excel's row limit. Upload a shorter range.")
    values = list(values) or [None]
    sheet.append([float(value) if isinstance(value, Decimal) else value for value in values])
    for cell in sheet[sheet.max_row]:
        if isinstance(cell.value, str):
            cell.data_type = "s"
    return sheet.max_row


def _source_sheet(book: Workbook, name: str, source: SourceData) -> None:
    sheet = book.create_sheet(name)
    _append(sheet, ["Source Row", *source.headers, "Import Status"])
    for number, values in source.rows:
        width = len(source.headers)
        _append(sheet, [number, *(values + [None] * width)[:width], source.dispositions.get(number, "")])
    apply_default_font(sheet)
    style_header_row(sheet)
    format_table_columns(sheet, headers=["Source Row", *source.headers, "Import Status"])
    sheet.sheet_view.showGridLines = False
    for row in sheet.iter_rows():
        lines = 1
        for cell in row:
            cell.alignment = Alignment(vertical="top", wrap_text=True)
            width = sheet.column_dimensions[get_column_letter(cell.column)].width
            # Preserve the complete tag/memo text while making it readable in
            # the source sheet, including literal HTML break tags from Workday.
            lines = max(lines, sum(max(1, ceil(len(part) / max(1, width - 3)))
                                   for part in str(cell.value or "").split("\n")))
        sheet.row_dimensions[row[0].row].height = max(22, 18 * lines)
    sheet.freeze_panes = "B2"
    sheet.auto_filter.ref = sheet.dimensions


def build_workbook(
    activity: LoanActivity, balances: OpeningBalances, *, app_version: str,
    trial_source: SourceData | None = None, cancellation: CancellationToken | None = None,
) -> Workbook:
    book = Workbook()
    book.active.title = "Current Recon"
    book.properties.title = "CSMF Loans — R1"
    book.properties.description = f"Mines Bursar Automation {app_version}; source-value review, not a completed reconciliation."
    opening = dict(balances.values)
    for project, loan in LOANS.items():
        if cancellation:
            cancellation.check()
        sheet = book.create_sheet(f"{loan} - {project}")
        sheet.sheet_view.showGridLines = False
        sheet.freeze_panes = "F7"
        _append(sheet, ["Find Journal Lines"])
        _append(sheet, [])
        _append(sheet, ["Fiscal Year", "Period", "Project", "Loan"])
        _append(sheet, [f"FY{activity.fiscal_year}", ", ".join(activity.periods), project, loan])
        _append(sheet, [])
        _append(sheet, HEADERS)
        adjusted_opening = -opening[project] if opening[project] is not None else None
        _append(sheet, ["Beginning Balance of the FY", None, None, "Trial Balance", None,
                        opening[project], "Debit" if opening[project] is not None else None, adjusted_opening])
        _append(sheet, ["Beginning Balance Total", None, None, None, None, None, None, None])
        sheet["H8"] = '=IF(COUNT(H7)=0,"",SUM(H7:H7))'
        _append(sheet, [])
        totals = [8]
        project_rows = [row for row in activity.rows if row.project == project]
        sections = dict(SECTIONS)
        if any(row.section == "other" for row in project_rows):
            sections["other"] = "Other ledger activity — review"
        for section, title in sections.items():
            first = sheet.max_row + 1
            for row in project_rows:
                if row.section != section:
                    continue
                if cancellation:
                    cancellation.check()
                _append(sheet, [row.label, row.journal, row.day, row.source, row.description,
                                row.amount, row.direction, row.adjusted_amount])
            last = sheet.max_row
            total_row = _append(sheet, [f"{title} Total", None, None, None, None, None, None,
                                        0 if last < first else None])
            if last >= first:
                sheet.cell(total_row, 8, f"=SUM(H{first}:H{last})")
            totals.append(total_row)
            _append(sheet, [])
        loan_total = _append(sheet, ["Loan Total"])
        # Reference subtotals only so detail rows are not counted a second time.
        sheet.cell(loan_total, 8, f"=SUM({','.join(f'H{number}' for number in totals)})")
        totals.append(loan_total)
        apply_default_font(sheet)
        style_header_row(sheet, row_number=3)
        style_header_row(sheet, row_number=6)
        sheet["A1"].font = Font(name="Aptos", size=18, bold=True, color="21314D")
        sheet.merge_cells("A1:H1")
        for column, width in {"A": 38, "B": 26, "C": 19, "D": 27, "E": 60, "F": 20, "G": 17, "H": 22}.items():
            sheet.column_dimensions[column].width = width
        for row in sheet.iter_rows(min_row=7):
            row[2].number_format = "yyyy-mm-dd"
            for column in (5, 7):
                row[column].number_format = CURRENCY_FORMAT
            for cell in row:
                cell.alignment = Alignment(vertical="top", wrap_text=True)
            description = str(row[4].value or "")
            sheet.row_dimensions[row[0].row].height = max(22, 16 * ceil(max(len(description), 1) / 55))
        for number in totals:
            for cell in sheet[number]:
                cell.fill = SUBTOTAL_FILL
                cell.font = Font(name="Aptos", size=12, bold=True)
            sheet.row_dimensions[number].height = 34
        sheet.row_dimensions[1].height = 32
        for cell in sheet[4]:
            cell.alignment = Alignment(vertical="top", wrap_text=True)
        sheet.row_dimensions[4].height = max(34, 18 * ceil(len(", ".join(activity.periods)) / 23))
        sheet.row_dimensions[6].height = 32
        sheet.print_title_rows = "1:6"
        sheet.sheet_properties.pageSetUpPr.fitToPage = True
        sheet.page_setup.orientation = "landscape"
        sheet.page_setup.paperSize = sheet.PAPERSIZE_A3
        sheet.page_setup.fitToWidth = 1
        sheet.page_setup.fitToHeight = 0
    snapshot = book.create_sheet("Opening Balances")
    _append(snapshot, ["Fiscal Year", "Project", "Loan", "Opening Balance", "Last Uploaded/Updated", "Source"])
    for project, balance in balances.projects:
        _append(snapshot, [balances.fiscal_year, project, LOANS[project], balance.amount,
                           balance.updated_at, balance.source_name])
    apply_default_font(snapshot)
    style_header_row(snapshot)
    format_table_columns(snapshot, headers=[cell.value for cell in snapshot[1]], currency_headers={"Opening Balance"})
    snapshot.column_dimensions["E"].width = 32
    snapshot.sheet_view.showGridLines = False
    snapshot.freeze_panes = "A2"
    _source_sheet(book, "Journal Lines", activity.source)
    if trial_source is not None:
        _source_sheet(book, "Trial Balance", trial_source)
    # Show the first populated loan worksheet rather than the intentionally empty summary.
    book.active = 1
    return book
