"""Review workbook using the application's established Excel output helpers."""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from pathlib import Path

import pandas as pd
from openpyxl import Workbook
from openpyxl.styles import Alignment, Font

from data_processing.shared.xlsx_output_format import write_table_sheet
from .calculation import TuitionReview


def _cell(value: object, header: str = "") -> object:
    if value is None or pd.isna(value):
        return None
    if isinstance(value, Decimal):
        return float(value)
    if isinstance(value, (date, datetime)):
        return value
    if header.endswith("_date"):
        try:
            timestamp = pd.to_datetime(value, utc=True)
            if not pd.isna(timestamp):
                return timestamp.tz_localize(None).to_pydatetime()
        except (TypeError, ValueError, OverflowError):
            pass  # Keep invalid source dates visible for review.
    if header in {"credit_hours", "billable_hours", "payment_year"}:
        try:
            return float(value)
        except (TypeError, ValueError):
            pass
    # Source text is data, even if it begins with an Excel formula character.
    if isinstance(value, str) and value.startswith(("=", "+", "-", "@")):
        return "'" + value
    return value


def export_review(review: TuitionReview, frames: dict[str, pd.DataFrame], manifest: dict, path: Path) -> Path:
    """Save exclusively; leave financial calculations in the tested domain layer."""
    workbook = Workbook()
    workbook.remove(workbook.active)
    rate = manifest["exchange_rate"]
    identity = frames["identity"].iloc[0]
    summary = [
        ["Tax year", manifest["tax_year"]], ["Environment", manifest["environment"]],
        ["CWID", identity.get("cwid", identity.get("student_id", identity.get("id", "")))],
        ["Student", " ".join(str(identity.get(key, "")) for key in ("first_name", "last_name"))],
        ["Paid amount (USD)", review.paid_usd], ["Converted amount (CAD)", review.paid_cad],
        ["Amount status", "Calculated for administrator review" if review.paid_cad is not None else "Review required; see Checks"],
        ["Certificate status", manifest["certificate_status"]],
        ["Annual rate (CAD per USD)", Decimal(rate["cad_per_usd"]) if rate.get("cad_per_usd") else None],
        ["Rate year", rate.get("rate_year")], ["Rate method", rate.get("method")],
        ["Fee policy", "Exclude FEIT/CFEE; retain other charge codes under report owner policy"],
        ["Minimum course duration", "21 consecutive scheduled days, including start/end; Summer included"],
        ["Attendance review", "Complete confirmation columns on Sessions before certifying"],
        ["Rounding", "Total USD × annual rate; round final CAD to cents, half up"],
        ["Source extracted (UTC)", manifest.get("extracted_at_utc")],
        ["Output application version", manifest["app_version"]],
    ]
    write_table_sheet(workbook, sheet_name="Summary", table_name="TL11ASummary",
                      headers=["Item", "Value"], rows=[[_cell(v) for v in row] for row in summary])
    sheet = workbook["Summary"]
    sheet.column_dimensions["A"].width = 32
    sheet.column_dimensions["B"].width = 95
    for row in sheet.iter_rows(min_row=2):
        row[1].alignment = Alignment(vertical="top", wrap_text=True)
        sheet.row_dimensions[row[0].row].height = 32
    for row in (6, 7):
        sheet.cell(row, 2).number_format = '"USD "#,##0.00' if row == 6 else '"CAD "#,##0.00'
        sheet.cell(row, 2).font = Font(name="Aptos", size=14, bold=True, color="1F4E78")
    sheet.cell(10, 2).number_format = "0.0000"

    # Order shows the usable output first, then allocation build and source evidence.
    tables = [
        ("Sessions", review.sessions),
        ("Tuition Charges", review.charges.drop(columns=["pidm", "extract_row_count", "extract_tax_year"], errors="ignore")),
        ("Applications", review.applications.drop(columns=["pidm", "extract_row_count", "extract_tax_year"], errors="ignore")),
        ("Courses", frames["enrollment_prepared"].drop(columns=["pidm", "extract_row_count", "extract_tax_year"], errors="ignore")),
        ("Programs", frames["programs"].drop(columns=["pidm", "extract_row_count", "extract_tax_year"], errors="ignore")),
        ("Rate and Policy", pd.DataFrame([
            {"Item": key, "Value": json_value} for key, json_value in rate.items()
        ] + [{"Item": "Source package", "Value": manifest.get("source_package", "Current Insights extracts")},
             {"Item": "Query/policy audit", "Value": "See accompanying manifest.json and complete raw CSVs"}])),
        ("Reconciliation", review.reconciliation), ("Checks", review.checks),
    ]
    for index, (name, frame) in enumerate(tables, 1):
        headers = list(frame.columns)
        write_table_sheet(workbook, sheet_name=name, table_name=f"TL11ATable{index}", headers=headers,
            rows=([_cell(value, header) for header, value in zip(headers, row)] for row in frame.itertuples(index=False, name=None)),
            currency_headers={col for col in headers if col.endswith("_usd")},
            count_headers={"course_count", "issue_count", "scheduled_duration_days"})
        ws = workbook[name]
        ws.row_dimensions[1].height = 48
        for cell in ws[1]:
            cell.alignment = Alignment(wrap_text=True, vertical="center")
        for col, header in enumerate(headers, 1):
            if header in {"session_start", "session_end"} or header.endswith("_date"):
                for cells in ws.iter_cols(min_col=col, max_col=col, min_row=2):
                    for cell in cells:
                        cell.number_format = "mm/dd/yyyy"
            if header in {"detail", "Value"}:
                ws.column_dimensions[ws.cell(1, col).column_letter].width = 110
                for cells in ws.iter_cols(min_col=col, max_col=col, min_row=2):
                    for cell in cells:
                        cell.alignment = Alignment(wrap_text=True, vertical="top")
                        ws.row_dimensions[cell.row].height = 48
            if header.endswith("_confirmation"):
                for cells in ws.iter_cols(min_col=col, max_col=col, min_row=2):
                    for cell in cells:
                        cell.font = Font(name="Aptos", size=12, color="0000FF")
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        with path.open("xb") as handle:
            try:
                workbook.save(handle)
            except Exception:
                path.unlink(missing_ok=True)
                raise
    finally:
        workbook.close()
    return path
