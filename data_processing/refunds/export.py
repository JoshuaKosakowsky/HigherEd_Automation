from __future__ import annotations

from collections import defaultdict
from copy import copy
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from pathlib import Path
import re

from openpyxl import Workbook
from openpyxl.styles import Alignment
from openpyxl.utils import get_column_letter
import pandas as pd

from data_processing.shared.xlsx_output_format import (
    CURRENCY_FORMAT,
    apply_default_font,
    format_table_columns,
    style_header_row,
)

from shared.cancellation import CancellationToken
from shared.progress import ProgressReporter
from .allocation import CARD_PAYMENT_CODES, REPORT_COLUMNS, STUDENT_CHECK_MINIMUM


REFUND_SHEETS = (
    "ACH or CC Refunds", "Refund by Check", "Refund to Parent", "Direct Deposit",
    "Manual Reviews", "Check Refund < 25", "Check Address Review", "Third Party Reviews",
    "Refund Holds", "Future Term", "Payment Clearing", "ACH Clearing", "ACH Reviews",
    "Mines Park Reviews",
)
REFUND_TAB_COLORS = {
    "Direct Deposit": "BDD7EE",  # Light blue
    "ACH or CC Refunds": "FFF2CC",  # Light yellow
    "Refund by Check": "E2EFDA",  # Light green
    "Refund to Parent": "FCE4D6",  # Light orange
}
WORKBOOK_LEADING_COLUMNS = [
    "cwid", "last_name", "first_name",
    "tab_delivery", "tab_refund_amount", "tab_review_note",
    "full_account_balance", "total_refund_amount", "title_iv_balance_due_note",
    "proposed_student_delivery", "student_refund_amount",
    "raw_delinquency_code", "active_ed_ind", "ed_activity_date", "plus_to_student_status",
]
# Staff-selected leading columns leave the allocator's report order unchanged.
WORKBOOK_COLUMNS = WORKBOOK_LEADING_COLUMNS + [
    column for column in REPORT_COLUMNS if column not in WORKBOOK_LEADING_COLUMNS
]
# Display changes leave allocation fields intact.
WORKBOOK_HEADERS = {
    "cwid": "CWID",
    "last_name": "Last_Name",
    "first_name": "First_Name",
    "tab_delivery": "Detail_Code_Delivery",
    "tab_refund_amount": "Detail_Code_Refund_Amt",
    "tab_review_note": "Detail_Code_Note",
    "full_account_balance": "Current_Total_Balance",
    "total_refund_amount": "Total_Owed_to_Student",
    "title_iv_balance_due_note": "Title IV Refund Leaves Balance Due",
    "student_refund_available_amount": "Student Available Now",
    "parent_refund_available_amount": "Parent Available Now",
    "student_clearing_reserve_amount": "Student Clearing Reserve",
    "parent_clearing_reserve_amount": "Parent Clearing Reserve",
    "clearing_payment_amount": "Uncleared Payment Principal",
    "clearing_insurance_amount": "Student Insurance Reserve",
    "clearing_payment_count": "Uncleared Payment Count",
    "clearing_next_eligible_date": "Next Clearing Date",
    "clearing_final_eligible_date": "Final Clearing Date",
    "student_address_type": "Student Address Type",
    "student_address_line1": "Student Address Line 1",
    "student_address_line2": "Student Address Line 2",
    "student_address_line3": "Student Address Line 3",
    "student_address_city": "Student Address City",
    "student_address_state": "Student Address State",
    "student_address_zip": "Student Address ZIP",
    "student_address_nation": "Student Address Nation",
    "student_check_address_flag": "Student Check Address Flag",
    "proposed_student_delivery": "Proposed_DetailCode&Amt",
    "raw_delinquency_code": "Active RH",
    "active_ed_ind": "Active ED",
    "ed_activity_date": "ED Start",
    "plus_to_student_status": "PPL to Student",
    "sponsor_names": "Sponsor(s)",
    "sponsor_ids": "Sponsor ID(s)",
    "contract_numbers": "Contract Number(s)",
    "third_party_current_term": "Current Term",
    "current_term_tppy_total": "TPPY Current Term Total",
    "current_term_z0le_total": "Z0LE Current Term Total",
    "z0le_activity_last_7_days": "Z0LE Activity_Last 7 Days",
}
WORKBOOK_OMITTED_COLUMNS = {
    "original_payment_row_count", "deceased_ind", "deceased_date",
    "confidential_ind", "ambiguous_source_pool_count", "last_ar_activity_date",
    "account_control_activity_date",
}
THIRD_PARTY_COLUMNS = {
    "sponsor_names", "sponsor_ids", "contract_numbers", "third_party_current_term",
    "current_term_tppy_total", "current_term_z0le_total", "z0le_activity_last_7_days",
}
DELIVERY_SHEETS = {
    "AFRD (Transact)": "ACH or CC Refunds",
    **{f"{code} (Transact)": "ACH or CC Refunds" for code in CARD_PAYMENT_CODES},
    "RFND (CHECK)": "Refund by Check",
    "ARFD (System)": "Direct Deposit",
    "Refund Hold - Student": "Refund Holds",
    "AFRD (Transact) - May Be Too Old": "ACH Reviews",
    "ACHK Date Review": "ACH Reviews",
}
COMPONENT_AMOUNT = re.compile(r"^(.*?)\s+(\d+\.\d{2})$")
ACH_WAIT = re.compile(r"^ACHK Clearing Wait until \d{2}/\d{2}/\d{4}$")
CHECK_WAIT_REASON = re.compile(
    r"(?:^|; )CHCK_CLEARING_WAIT_UNTIL_(\d{2}/\d{2}/\d{4})_AMOUNT_(\d+\.\d{2})(?:;|$)"
)


@dataclass(frozen=True)
class RefundPortion:
    sheet: str
    delivery: str
    amount: Decimal


def _amount(value: object) -> Decimal | None:
    if value is None or pd.isna(value):
        return None
    try:
        amount = Decimal(str(value))
    except InvalidOperation:
        return None
    return amount if amount.is_finite() else None


def _workbook_value(column: str, value: object) -> object:
    if pd.isna(value):
        return None
    if column == "z0le_activity_last_7_days":
        return {"Y": "Yes", "N": "No"}.get(value, value)
    if column in {"tab_delivery", "proposed_student_delivery"} and isinstance(value, str):
        return value.replace("ARFD (System)", "ARFD (Direct Deposit)")
    return value


def _student_portions(delivery: str, amount: Decimal) -> list[RefundPortion]:
    """Read the allocator's delivery display; reject unknown or unreconciled parts.

    Single-method displays omit amounts; mixed displays explicitly include them.
    Never guess a mixed allocation or send an unfamiliar code to a payment tab.
    """
    parts = delivery.split("; ")
    portions = []
    for part in parts:
        label = part
        portion_amount = amount
        if len(parts) > 1:
            match = COMPONENT_AMOUNT.fullmatch(part)
            if match is None:
                raise ValueError("Unrecognized mixed student delivery amounts.")
            label, raw_amount = match.groups()
            label = label.removesuffix(" /")
            portion_amount = Decimal(raw_amount)
        sheet = "ACH Clearing" if ACH_WAIT.fullmatch(label) else DELIVERY_SHEETS.get(label)
        if sheet is None or portion_amount <= 0:
            raise ValueError("Unrecognized student delivery; verify the recipient and method.")
        # Apply the check minimum to this delivery portion, not the whole account
        # or other recipients. ACH/card, ED and Parent PLUS retain their routes.
        if label == "RFND (CHECK)" and portion_amount < STUDENT_CHECK_MINIMUM:
            sheet = "Check Refund < 25"
        portions.append(RefundPortion(sheet, label, portion_amount))
    if sum((part.amount for part in portions), Decimal(0)) != amount:
        raise ValueError("Student delivery components do not equal the student refund amount.")
    return portions


def _tab_rows(row: dict[str, object]) -> list[tuple[str, dict[str, object]]]:
    """Partition one account's refund without changing any allocation fields."""
    total = _amount(row["total_refund_amount"])
    check_wait = CHECK_WAIT_REASON.search(str(row["review_reasons"] or ""))
    check_wait_note = (
        f"CHCK clearing wait: {check_wait.group(2)} becomes eligible "
        f"on {check_wait.group(1)}."
        if check_wait else None
    )

    def review(sheet: str, note: str) -> list[tuple[str, dict[str, object]]]:
        if check_wait_note:
            note = f"{note} {check_wait_note}"
        return [(sheet, {**row, "tab_delivery": "REVIEW REQUIRED",
                         "tab_refund_amount": total, "tab_review_note": note})]

    # RH is an account-level instruction to issue no refund. Keep every recipient
    # portion together on the hold tab even when another review reason also applies.
    if row["refund_hold_ind"] == "Y":
        return review("Refund Holds", "RH account hold: do not issue any refund.")

    if "FUTURE_TERM_CREDIT" in str(row["review_reasons"] or "").split("; "):
        return review("Future Term", "Future term credit: do not issue any refund.")

    # Other account-level reviews stay together rather than appearing in payment queues.
    if row["third_party_review_required_ind"] == "Y":
        return review("Third Party Reviews", "Resolve third-party ownership before issuing refunds.")
    if "Mines Park Charge - Review" in str(row["review_reasons"]):
        return review("Mines Park Reviews", "Review housing charges before issuing refunds.")

    student = _amount(row["student_refund_amount"])
    parent = _amount(row["parent_refund_amount"])
    if (student is None or parent is None or total is None
            or min(student, parent) < 0 or student + parent != total or total <= 0):
        return review("Manual Reviews", "Recipient amounts are undetermined or do not reconcile.")

    student_available = _amount(row["student_refund_available_amount"])
    parent_available = _amount(row["parent_refund_available_amount"])
    student_reserved = _amount(row["student_clearing_reserve_amount"])
    parent_reserved = _amount(row["parent_clearing_reserve_amount"])
    if (any(value is None or value < 0 for value in (
            student_available, parent_available, student_reserved, parent_reserved))
            or student_available + student_reserved != student
            or parent_available + parent_reserved != parent):
        return review("Manual Reviews", "Available and reserved amounts do not reconcile to recipient amounts.")

    portions = []
    if student_available > 0:
        try:
            portions.extend(_student_portions(str(row["proposed_student_delivery"]), student_available))
        except ValueError as error:
            return review("Manual Reviews", str(error))
    if parent_available > 0:
        if row["proposed_parent_delivery"] != "RFDP":
            return review("Manual Reviews", "Parent refund delivery requires review.")
        portions.append(RefundPortion("Refund to Parent", "RFDP", parent_available))
    if student_reserved > 0:
        portions.append(RefundPortion("Payment Clearing", "Student clearing reserve", student_reserved))
    if parent_reserved > 0:
        portions.append(RefundPortion("Payment Clearing", "Parent clearing reserve", parent_reserved))

    by_sheet: dict[str, list[RefundPortion]] = defaultdict(list)
    for portion in portions:
        sheet = portion.sheet
        if portion.delivery == "RFND (CHECK)" and row["student_check_address_flag"]:
            sheet = "Check Address Review"
        by_sheet[sheet].append(portion)
    rows = []
    for sheet, parts in by_sheet.items():
        note = check_wait_note if sheet != "Refund to Parent" else None
        if sheet == "Payment Clearing":
            note = "Do not issue these reserved amounts. Recalculate on the next clearing date."
        elif sheet == "Check Refund < 25":
            note = "Student check refund is below $25.00; do not issue a check."
            if check_wait_note:
                note += f" {check_wait_note}"
        elif sheet == "Check Address Review":
            note = (
                "Update and verify the student address in Workday before issuing this check."
                if row["student_check_address_flag"] == "UPDATE WORKDAY"
                else "Withhold this student check; no confirmed U.S. address is available."
            )
            if sum((part.amount for part in parts), Decimal(0)) < STUDENT_CHECK_MINIMUM:
                note += " Student check is also below $25.00; do not issue a check."
        rows.append((sheet, {
            **row,
            "tab_delivery": "; ".join(f"{part.delivery} {part.amount:.2f}" for part in parts),
            "tab_refund_amount": sum((part.amount for part in parts), Decimal(0)),
            "tab_review_note": note,
        }))
    return rows


CURRENCY_COLUMNS = {
    "tab_refund_amount",
    "full_account_balance",
    "total_refund_amount",
    "student_refund_amount",
    "parent_refund_amount",
    "student_refund_available_amount",
    "parent_refund_available_amount",
    "student_clearing_reserve_amount",
    "parent_clearing_reserve_amount",
    "clearing_payment_amount",
    "clearing_insurance_amount",
    "current_term_tppy_total",
    "current_term_z0le_total",
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
    "clearing_payment_count",
    "fdpl_row_count",
    "original_payment_row_count",
    "plus_auth_row_count",
    "negative_source_count",
    "ambiguous_source_pool_count",
}


def export_refund_report(
    report: pd.DataFrame, output_file: Path, *, cancellation: CancellationToken | None = None,
    progress_reporter: ProgressReporter | None = None, standalone_term: str | None = None,
) -> Path:
    """Write plain worksheets by refund method, keeping account totals as context."""
    if cancellation:
        cancellation.check()
    missing = [column for column in REPORT_COLUMNS if column not in report.columns]
    if missing:
        raise ValueError(f"Refund report is missing columns: {', '.join(missing)}")

    workbook = Workbook()
    workbook.remove(workbook.active)
    grouped: dict[str, list[dict[str, object]]] = defaultdict(list)
    if progress_reporter:
        progress_reporter.report("Grouping refund delivery and review tabs", completed=0, total=len(report))
    for completed, row in enumerate(report[REPORT_COLUMNS].to_dict("records"), 1):
        if cancellation:
            cancellation.check()
        portions = _tab_rows(row)
        if standalone_term is not None:
            routed = sum(part["tab_refund_amount"] for _, part in portions)
            if routed != row["total_refund_amount"]:
                raise ValueError("Workbook portions do not reconcile to the standalone account refund total.")
        for sheet, tab_row in portions:
            if standalone_term is not None and sheet == "Third Party Reviews":
                tab_row["tab_review_note"] += " Refunds.sql omits sponsor, contract and term activity details."
            grouped[sheet].append(tab_row)
        if progress_reporter and (completed % 100 == 0 or completed == len(report)):
            progress_reporter.report("Grouping refund delivery and review tabs", completed=completed, total=len(report))

    for sheet in REFUND_SHEETS:
        if cancellation:
            cancellation.check()
        worksheet = workbook.create_sheet(sheet)
        if sheet in REFUND_TAB_COLORS:
            worksheet.sheet_properties.tabColor = REFUND_TAB_COLORS[sheet]
        worksheet.freeze_panes = "A2"
        columns = [
            column for column in WORKBOOK_COLUMNS
            if column not in WORKBOOK_OMITTED_COLUMNS
            and (sheet == "Third Party Reviews" or column not in THIRD_PARTY_COLUMNS)
        ]
        header_names = WORKBOOK_HEADERS
        headers = [header_names.get(column, column) for column in columns]
        worksheet.append(headers)
        if progress_reporter:
            progress_reporter.report(f"Writing {sheet} worksheet", completed=0, total=len(grouped[sheet]))
        for completed, row in enumerate(grouped[sheet], 1):
            if cancellation:
                cancellation.check()
            worksheet.append([
                _workbook_value(column, row[column]) for column in columns
            ])
            if progress_reporter and (completed % 100 == 0 or completed == len(grouped[sheet])):
                progress_reporter.report(f"Writing {sheet} worksheet", completed=completed, total=len(grouped[sheet]))
        if progress_reporter:
            progress_reporter.report(f"Formatting {sheet} worksheet")
        apply_default_font(worksheet)
        style_header_row(worksheet)
        format_table_columns(
            worksheet, headers=headers,
            currency_headers={header_names.get(column, column) for column in CURRENCY_COLUMNS},
            count_headers={header_names.get(column, column) for column in COUNT_COLUMNS},
        )
        for cell in worksheet[1]:
            cell.alignment = Alignment(horizontal="center", vertical="center", wrap_text=True)
        worksheet.row_dimensions[1].height = 48
        worksheet.column_dimensions["D"].width = 60
        balance_flag_column = columns.index("title_iv_balance_due_note") + 1
        worksheet.column_dimensions[get_column_letter(balance_flag_column)].width = 26
        for (cell,) in worksheet.iter_rows(min_row=2, min_col=balance_flag_column,
                                          max_col=balance_flag_column):
            cell.alignment = Alignment(horizontal="center", vertical="center")
        address_flag_column = columns.index("student_check_address_flag") + 1
        worksheet.column_dimensions[get_column_letter(address_flag_column)].width = 28
        for (cell,) in worksheet.iter_rows(min_row=2, min_col=address_flag_column,
                                          max_col=address_flag_column):
            if cell.value:
                font = copy(cell.font)
                font.color = "FF0000"
                cell.font = font
                cell.alignment = Alignment(vertical="center", wrap_text=True)
        worksheet.auto_filter.ref = worksheet.dimensions
        for header in (
            "deceased_date", "last_ar_activity_date", "account_control_activity_date",
            "ed_activity_date", "plus_auth_activity_date", "clearing_next_eligible_date",
            "clearing_final_eligible_date",
        ):
            if header not in columns:
                continue
            column_number = columns.index(header) + 1
            for cells in worksheet.iter_cols(min_col=column_number, max_col=column_number, min_row=2):
                for cell in cells:
                    cell.number_format = (
                        "mm/dd/yyyy" if header in {"deceased_date", "clearing_next_eligible_date", "clearing_final_eligible_date"}
                        else "mm/dd/yyyy h:mm AM/PM"
                    )

    if standalone_term is not None:
        notes = workbook.create_sheet("Run Details")
        notes.append(["Report source", "Standalone Refund Review SQL (PROD)"])
        notes.append(["Banner target term", standalone_term])
        notes.append(["Accounts returned by Insights", len(report)])
        notes.append(["Total refund under review", sum(report["total_refund_amount"], Decimal(0))])
        notes["B4"].number_format = CURRENCY_FORMAT
        notes.append(["Third Party Reviews", "Verify sponsor names and IDs, contract numbers, sponsor term, "
                      "TPPY and Z0LE term totals, and recent Z0LE activity separately. "
                      "Refunds.sql does not supply these fields."])
        notes.append(["Population check", "The account count covers the rows returned by Insights. "
                      "Refunds.sql supplies no independent count of qualifying accounts."])
        notes.column_dimensions["A"].width = 29
        notes.column_dimensions["B"].width = 76
        notes["B5"].alignment = Alignment(wrap_text=True, vertical="center")
        notes.row_dimensions[5].height = 65
        notes["B6"].alignment = Alignment(wrap_text=True, vertical="center")
        notes.row_dimensions[6].height = 45
        apply_default_font(notes)
        style_header_row(notes)

    output_file.parent.mkdir(parents=True, exist_ok=True)
    if cancellation:
        cancellation.check()
    try:
        if progress_reporter:
            progress_reporter.report("Saving refund workbook")
        workbook.save(output_file)
    finally:
        workbook.close()
    return output_file
