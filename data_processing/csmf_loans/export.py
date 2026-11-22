"""R1 loan worksheets and fiscal-year/monthly reconciliation summaries."""

from __future__ import annotations

import re
from collections import defaultdict
from decimal import Decimal
from math import ceil

from openpyxl import Workbook
from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
from openpyxl.utils import get_column_letter
from openpyxl.worksheet.worksheet import Worksheet

from data_processing.shared.source_exports import SourceData, fiscal_scope
from data_processing.shared.xlsx_output_format import (
    CURRENCY_FORMAT, apply_default_font, format_table_columns, style_header_row,
)
from shared.cancellation import CancellationToken
from .balances import OpeningBalances
from .sources import LOANS, SECTIONS, Activity, LoanActivity


HEADERS = ["Activity", "Journal Number", "Accounting Date", "Source", "Description",
           "Amount", "Debit/Credit", "Adjusted Amount"]
SUBTOTAL_FILL = PatternFill("solid", fgColor="CFDCE9")
PRIOR_YEAR_FOOTNOTES = (
    ("2100", "*", "Footnote* — Payment of a prior fiscal year obligation recorded in the current fiscal year."),
    ("1382", "**", "Footnote** — Prior fiscal year accounts receivable activity recorded in the current fiscal year."),
)
AP_DUE_LABEL = "AP due — 2402"
AP_PAID_PREFIX = "AP paid — "
AP_REVIEW_PREFIX = "Review AP — "
AP_PAID_ACCOUNTS = ("2881", "5909R", "8309R")
# Keep the reference summary's order without changing the existing loan tabs.
RECON_LOAN_ORDER = ("694511", "694512", "694513", "694514", "694518", "694521", "694516")
# Reference identifiers remain useful even though Unisa reports are not inputs.
RECON_UNISA_ACCOUNTS = {
    "694511": "6304", "694512": "6308", "694513": "6309", "694514": "6311",
    "694518": "6313", "694521": "6315", "694516": None,
}


def _foundation_receivable_transfers(project_rows: list[Activity]) -> set[int]:
    # The 2881 credit explains how the receivable was booked. Keep its audit
    # label separate from the 1382 booking and the subsequent cash receipt.
    journals = defaultdict(list)
    for row in project_rows:
        if (row.journal and row.source.casefold() == "manual journal eib"
                and (row.account, row.direction) in {("1382", "Debit"), ("2881", "Credit")}):
            journals[(row.day, row.journal.casefold())].append(row)
    return {
        row.source_row for entries in journals.values()
        if any(row.account == "1382" and row.amount for row in entries)
        and sum(row.adjusted_amount for row in entries) == 0
        for row in entries if row.account == "2881"
    }


def _foundation_payable_labels(project_rows: list[Activity]) -> dict[int, str]:
    """Classify the due and paid sides of a loan's Workday payable journal."""
    journals = defaultdict(list)
    labels = {}
    for row in project_rows:
        due = (row.account, row.direction) == ("2402", "Credit")
        paid = row.account in AP_PAID_ACCOUNTS and row.direction == "Debit"
        if row.source.casefold() != "manual journal eib" or not (due or paid):
            continue
        # Line Memo is free text. The numeric project and journal establish
        # identity; month wording and the spelling of the loan name can vary.
        words = set(re.findall(r"[a-z0-9]+", row.description.casefold()))
        payable_memo = "csmf" in words and bool(words & {"pay", "payable", "paid", "payment"})
        if payable_memo and row.journal:
            journals[(row.day, row.journal.casefold())].append(row)
        elif (due or payable_memo) and row.amount:
            labels[row.source_row] = AP_REVIEW_PREFIX + row.account

    for entries in journals.values():
        balanced = (any(row.account == "2402" and row.amount for row in entries)
                    and sum(row.adjusted_amount for row in entries) == 0)
        for row in entries:
            if not balanced:
                labels[row.source_row] = AP_REVIEW_PREFIX + row.account
            elif row.account == "2402":
                labels[row.source_row] = AP_DUE_LABEL
            else:
                labels[row.source_row] = AP_PAID_PREFIX + row.account
    return labels


def _foundation_payable_formulas(
    loan_sheet: str, totals: dict[str, int], detail_rows: dict[str, tuple[int, int]], *, monthly: bool,
) -> tuple[str, str]:
    end = totals["loan"] - 1
    amounts = f"{loan_sheet}!H10:H{end}"
    labels = f"{loan_sheet}!A10:A{end}"
    cutoff = f',{loan_sheet}!C10:C{end},"<"&EDATE($D$3,1)' if monthly else ""

    def sum_labeled(label: str) -> str:
        return f'SUMIFS({amounts},{labels},"{label}"{cutoff})'

    # The signed interest subtotal already includes its transfer debit. The
    # principal transfer is in 2881, so subtract it from collections separately.
    due = [sum_labeled(AP_DUE_LABEL), sum_labeled(AP_PAID_PREFIX + "2881")]
    for section in ("payment", "5909R"):
        first, last = detail_rows[section]
        if not monthly:
            due.append(f"{loan_sheet}!H{totals[section]}")
        elif first <= last:
            due.append(f'SUMIF({loan_sheet}!C{first}:C{last},"<"&EDATE($D$3,1),'
                       f'{loan_sheet}!H{first}:H{last})')
    paid = ",".join(sum_labeled(AP_PAID_PREFIX + account) for account in AP_PAID_ACCOUNTS)
    review = "+".join(f'COUNTIFS({labels},"{AP_REVIEW_PREFIX}{account}"{cutoff})'
                      for account in ("2402", *AP_PAID_ACCOUNTS))
    return (
        f'=IF({review}>0,"Review",ROUND(SUM({",".join(due)}),2))',
        f'=IF({review}>0,"Review",ROUND(SUM({paid}),2))',
    )


def _current_recon_sheet(
    sheet: Worksheet, activity: LoanActivity, subtotal_rows: dict[str, dict[str, int]],
    detail_rows: dict[str, dict[str, tuple[int, int]]], *, monthly: bool = False,
) -> None:
    """Share the layout while keeping FY totals and monthly activity distinct."""
    month = max(row.day for row in activity.rows).replace(day=1)
    _, period, _ = fiscal_scope(month)
    scope = period if monthly else f"FY{activity.fiscal_year}"
    sheet.sheet_view.showGridLines = False
    sheet["A1"] = "Donor Restricted Student Loans - Administered by School"
    sheet["A2"] = (f"{period} — {month:%B %Y}" if monthly
                   else f"FY{activity.fiscal_year} — All uploaded activity")
    sheet["H2"] = f"Included period: {period}" if monthly else "Included periods: " + ", ".join(activity.periods)
    sheet["A3"] = "Reconciliation month"
    sheet["D3"] = month
    sheet["D3"].number_format = "mmmm yyyy"
    labels = {
        "N4": "AP", "P4": "AR", "A5": "Loan Information", "J5": "Interest and Fees",
        "N5": "Total Due to\nFoundation", "O5": "Total Paid to\nFoundation",
        "P5": "Total Due From\nFoundation", "Q5": "Total Paid From\nFoundation",
        "A6": "Loan", "B6": "Unisa\nAcct", "C6": "Project", "D6": "Beginning\nBalance",
        "E6": "Adjustments/\nReclass", "F6": f"{scope}\nLoan Activity (Net)",
        "G6": f"{scope}\nPayments", "H6": "Net Change\nin Principal",
        "J6": "Interest", "K6": "Late Charges", "L6": "Total\nInterest and Fees",
        "A14": "Totals", "A18": "Pending Items", "A19": "Loan", "B19": "Unisa\nAcct", "C19": "Project",
        "D19": "Unisa Ending\nBalance", "E19": "GL", "F19": "Variance",
        "G19": "Notes / Outstanding Items", "A27": "Totals", "D27": "Pending", "F27": "Pending",
        "A16": ("Beginning Balance = FY opening + 1621 debits - credits dated before this month. Activity covers this month only."
                if monthly else "Beginning Balance = FY opening + all uploaded 1621 debits - credits, including the reconciliation month."),
        "A17": "AP and AR balances are due plus paid through the report month. Review flagged AP journal lines. Prior-year activity is footnoted.",
        "A29": ("Blank beginning balances remain unknown; GL is the cumulative Loan Total through this month. Shaded blanks are review inputs."
                if monthly else "Blank beginning balances remain unknown; GL includes the available activity. Shaded blanks are review inputs."),
        "A31": "Reconciliation Dates", "A32": "Completed By:", "A33": "Completed Date:",
        "A34": "Reviewed By:", "A35": "Reviewed Date:",
    }
    for cell, label in labels.items():
        sheet[cell] = label
    for region in ("A1:Q1", "A2:G2", "H2:Q2", "A3:C3", "N4:O4", "P4:Q4", "A5:H5",
                   "J5:L5", "N5:N6", "O5:O6", "P5:P6", "Q5:Q6", "A14:C14",
                   "A16:Q16", "A17:Q17", "A18:L18", "G19:L19", "A27:C27", "A29:Q29", "A31:D31"):
        sheet.merge_cells(region)

    for row, project in enumerate(RECON_LOAN_ORDER, 7):
        loan_sheet = f"'{LOANS[project]} - {project}'"
        totals = subtotal_rows[project]
        sheet.cell(row, 1, LOANS[project].upper())
        sheet.cell(row, 2, RECON_UNISA_ACCOUNTS[project])
        sheet.cell(row, 3, project)
        # Payment, Loan Activity and Unclassified are the first three sections
        # and contain only 1621. Subtotal rows have no Debit/Credit marker.
        # Monthly openings stop before the report month; FY openings retain
        # every uploaded period. Both use raw amounts, independent of edits to H.
        opening = f"{loan_sheet}!F7"
        last_1621 = totals["1621"] - 1
        amounts = f"{loan_sheet}!F10:F{last_1621}"
        directions = f"{loan_sheet}!G10:G{last_1621}"
        before_month = f',{loan_sheet}!C10:C{last_1621},"<"&$D$3' if monthly else ""
        sheet.cell(row, 4, f'=IF({opening}="","",{opening}'
                          f'+SUMIFS({amounts},{directions},"Debit"{before_month})'
                          f'-SUMIFS({amounts},{directions},"Credit"{before_month}))')
        for column, section in ((5, "1621"), (6, "loan_activity"), (7, "payment"),
                                (10, "5909R"), (11, "8309R")):
            if not monthly:
                sheet.cell(row, column, f"={loan_sheet}!H{totals[section]}")
                continue
            first, last = detail_rows[project][section]
            if last < first:
                sheet.cell(row, column, 0)
            else:
                dates = f"{loan_sheet}!C{first}:C{last}"
                sheet.cell(row, column, f'=SUMIFS({loan_sheet}!H{first}:H{last},'
                                       f'{dates},">="&$D$3,{dates},"<"&EDATE($D$3,1))')
        # All three columns already carry the confirmed Adjusted Amount signs.
        sheet.cell(row, 8, f"=SUM(E{row}:G{row})")
        sheet.cell(row, 12, f"=SUM(J{row}:K{row})")
        due, paid = _foundation_payable_formulas(loan_sheet, totals, detail_rows[project], monthly=monthly)
        sheet.cell(row, 14, due)
        sheet.cell(row, 15, paid)
        first_ar, last_ar = detail_rows[project]["1382"]
        for column, direction in ((16, "Debit"), (17, "Credit")):
            if last_ar < first_ar:
                sheet.cell(row, column, 0)
                continue
            amounts = f"{loan_sheet}!H{first_ar}:H{last_ar}"
            directions = f"{loan_sheet}!G{first_ar}:G{last_ar}"
            # The monthly view includes both earlier FY bookings and receipts.
            cutoff = f',{loan_sheet}!C{first_ar}:C{last_ar},"<"&EDATE($D$3,1)' if monthly else ""
            sheet.cell(row, column, f'=ROUND(-SUMIFS({amounts},{directions},"{direction}"{cutoff}),2)')
        pending = row + 13
        sheet.merge_cells(f"G{pending}:L{pending}")
        sheet.cell(pending, 1, f"=A{row}")
        sheet.cell(pending, 2, f'=IF(B{row}="","",B{row})')
        sheet.cell(pending, 3, f"=C{row}")
        # GL is cumulative in both views, not just the month's activity. This
        # is the existing Loan Total, not an independent GL balance.
        sheet.cell(pending, 5, f"={loan_sheet}!H{totals['loan']}")
        sheet.cell(pending, 6, "Pending")

    for column in (5, 6, 7, 8, 10, 11, 12, 16, 17):
        letter = get_column_letter(column)
        sheet.cell(14, column, f"=SUM({letter}7:{letter}13)")
    # A partial opening-balance sum must not masquerade as a complete control.
    sheet["D14"] = '=IF(COUNT(D7:D13)=7,SUM(D7:D13),"Pending")'
    for column in ("N", "O"):
        cells = f"{column}7:{column}13"
        sheet[f"{column}14"] = f'=IF(COUNT({cells})=ROWS({cells}),SUM({cells}),"Review")'
    sheet["E27"] = "=SUM(E20:E26)"
    for row in range(32, 36):
        sheet.merge_cells(f"A{row}:B{row}")
        sheet.merge_cells(f"C{row}:D{row}")
    for cell in ("C33", "C35"):
        sheet[cell].number_format = "mm/dd/yyyy"

    apply_default_font(sheet)
    for row in sheet.iter_rows():
        for cell in row:
            cell.alignment = Alignment(vertical="center", wrap_text=True)
        sheet.row_dimensions[row[0].row].height = 27
    for column, width in {"A": 17, "B": 9, "C": 13, "D": 18, "E": 18, "F": 18,
                          "G": 18, "H": 18, "I": 3, "J": 18, "K": 18, "L": 18,
                          "M": 3, "N": 20, "O": 20, "P": 20, "Q": 20}.items():
        sheet.column_dimensions[column].width = width
    for first, last, columns in ((7, 14, (4, 5, 6, 7, 8, 10, 11, 12, 14, 15, 16, 17)),
                                 (20, 27, (4, 5, 6))):
        for row in range(first, last + 1):
            for column in columns:
                sheet.cell(row, column).number_format = CURRENCY_FORMAT
                sheet.cell(row, column).alignment = Alignment(horizontal="right", vertical="center")
    for region, color in (("A5:H5", "E2EFDA"), ("J5:L5", "DDEBF7"),
                          ("N5:O14", "D9D9D9"), ("P5:Q14", "FCE4D6"),
                          ("A18:L18", "FFF2CC"), ("A31:D31", "FFF2CC")):
        for row in sheet[region]:
            for cell in row:
                cell.fill = PatternFill("solid", fgColor=color)
    for row_number in (5, 6, 18, 19, 31):
        for cell in sheet[row_number]:
            if cell.value is not None:
                cell.font = Font(name="Aptos", size=12, bold=True)
                cell.alignment = Alignment(horizontal="center", vertical="center", wrap_text=True)
    for column in ("N", "P"):
        sheet[f"{column}4"].alignment = Alignment(horizontal="center", vertical="center")
    for row_number, columns in ((14, (1, 4, 5, 6, 7, 8, 10, 11, 12, 14, 15, 16, 17)),
                                (27, (1, 4, 5, 6))):
        for column in columns:
            cell = sheet.cell(row_number, column)
            cell.font = Font(name="Aptos", size=12, bold=True)
            cell.border = Border(bottom=Side(style="double", color="595959"))
    for region in ("D20:D26", "G20:L26", "C32:D35"):
        for row in sheet[region]:
            for cell in row:
                cell.fill = PatternFill("solid", fgColor="FFF2CC")
    for region in ("D20:F26", "A7:H13", "J7:L13"):
        for row in sheet[region]:
            for cell in row:
                cell.border = Border(bottom=Side(style="hair", color="BFBFBF"))
    for cell in ("A16", "A17", "A29"):
        sheet[cell].font = Font(name="Aptos", size=11, italic=True, color="595959")
    sheet["A1"].font = Font(name="Aptos", size=18, bold=True, color="21314D")
    sheet["A1"].alignment = Alignment(horizontal="center", vertical="center")
    sheet.row_dimensions[1].height = 34
    sheet.row_dimensions[2].height = max(30, 18 * ceil(len(sheet["H2"].value) / 75))
    sheet.row_dimensions[6].height = 64
    sheet.row_dimensions[19].height = 48
    sheet.print_area = "A1:Q35"
    sheet.sheet_properties.pageSetUpPr.fitToPage = True
    sheet.page_setup.orientation = "landscape"
    sheet.page_setup.paperSize = sheet.PAPERSIZE_A3
    sheet.page_setup.fitToWidth = 1
    sheet.page_setup.fitToHeight = 1


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
    book.active.title = "Current Month Recon"
    book.create_sheet("Current FY Recon")
    book.properties.title = "CSMF Loans — R1"
    book.properties.description = f"Mines Bursar Automation {app_version}; source-value review, not a completed reconciliation."
    opening = dict(balances.values)
    subtotal_rows = {}
    detail_rows = {}
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
        subtotal_rows[project] = {"opening": 8}
        detail_rows[project] = {}
        project_rows = [row for row in activity.rows if row.project == project and not row.prior_year_activity]
        footnote_rows = [row for row in activity.rows if row.project == project and row.prior_year_activity]
        receivable_transfers = _foundation_receivable_transfers(project_rows)
        payable_labels = _foundation_payable_labels(project_rows)
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
                label = "AR reclass — 2881" if row.source_row in receivable_transfers else row.label
                label = payable_labels.get(row.source_row, label)
                _append(sheet, [label, row.journal, row.day, row.source, row.description,
                                row.amount, row.direction, row.adjusted_amount])
            last = sheet.max_row
            detail_rows[project][section] = (first, last)
            total_label = "1382 Totals" if section == "1382" else f"{title} Total"
            total_row = _append(sheet, [total_label, None, None, None, None, None, None,
                                        0 if last < first else None])
            if last >= first:
                sheet.cell(total_row, 8, f"=SUM(H{first}:H{last})")
            totals.append(total_row)
            subtotal_rows[project][section] = total_row
            _append(sheet, [])
        loan_total = _append(sheet, ["Loan Total"])
        # Reference subtotals only so detail rows are not counted a second time.
        sheet.cell(loan_total, 8, f"=SUM({','.join(f'H{number}' for number in totals)})")
        totals.append(loan_total)
        subtotal_rows[project]["loan"] = loan_total
        footnote_headings = []
        for account, marker, caption in PRIOR_YEAR_FOOTNOTES:
            account_rows = [row for row in footnote_rows if row.account == account]
            if not account_rows:
                continue
            _append(sheet, [])
            footnote_headings.append(_append(sheet, [caption]))
            for row in account_rows:
                if cancellation:
                    cancellation.check()
                _append(sheet, [f"{row.label}{marker}", row.journal, row.day, row.source, row.description,
                                row.amount, row.direction, row.adjusted_amount])
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
        for footnote_heading in footnote_headings:
            sheet.merge_cells(start_row=footnote_heading, start_column=1, end_row=footnote_heading, end_column=8)
            sheet.cell(footnote_heading, 1).font = Font(name="Aptos", size=12, italic=True, color="595959")
            sheet.row_dimensions[footnote_heading].height = 28
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
    if cancellation:
        cancellation.check()
    _current_recon_sheet(book["Current Month Recon"], activity, subtotal_rows, detail_rows, monthly=True)
    _current_recon_sheet(book["Current FY Recon"], activity, subtotal_rows, detail_rows)
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
    book.active = 0
    return book
