"""Plain review worksheets using the repository's existing Excel formatting."""

from __future__ import annotations

import shutil
import tempfile
from math import ceil
from datetime import date, datetime, timezone
from decimal import Decimal
from pathlib import Path

from openpyxl import Workbook
from openpyxl.styles import Alignment, Font

from data_processing.shared.xlsx_output_format import apply_default_font, format_table_columns
from shared.cancellation import CancellationToken
from .reconciliation import COMBINED_HEADERS, CWID_HEADERS, DOC_HEADERS, PERIOD_HEADERS, Reconciliation


EXCEL_MAX_ROWS = 1_048_576


def validate_output(path: Path, inputs: tuple[Path, ...] = ()) -> None:
    if path.suffix.lower() != ".xlsx" or not path.is_absolute():
        raise ValueError("Choose an absolute .xlsx output path.")
    if not path.parent.is_dir():
        raise ValueError("The output folder does not exist.")
    if path.exists() or path.resolve() in {source.resolve() for source in inputs}:
        raise ValueError("Output already exists or is a source file. Choose a new filename.")


def export_reconciliation(
    review: Reconciliation, output: Path, *, app_version: str,
    banner_source: str, cancellation: CancellationToken | None = None,
) -> None:
    validate_output(output)
    book = Workbook()
    book.remove(book.active)

    def sheet(name, headers, rows):
        ws = book.create_sheet(name)
        if len(rows) + 1 > EXCEL_MAX_ROWS:
            raise ValueError("A reconciliation sheet exceeds Excel's row limit. Select a shorter range.")
        ws.append(headers)
        for number, row in enumerate(rows, 2):
            if cancellation and number % 500 == 0:
                cancellation.check()
            ws.append([float(value) if isinstance(value, Decimal) else value for value in row])
            # Preserve source text literally, including text starting with '='.
            for cell in ws[number]:
                if isinstance(cell.value, str):
                    cell.data_type = "s"
                elif isinstance(cell.value, (date, datetime)):
                    cell.number_format = "yyyy-mm-dd"
        apply_default_font(ws)
        for cell in ws[1]:
            cell.font = Font(name="Aptos", size=12, bold=True)
            cell.alignment = Alignment(wrap_text=True, vertical="top")
        ws.row_dimensions[1].height = 44
        # This helper sets widths and number formats; no Excel Table is added.
        currency = {header for header in headers if any(word in header for word in ("Debit", "Credit", "Difference", "Activity"))
                    and header not in {"Included in Activity"}}
        currency |= {"Amount", "Balance", "'Amount'", "'Balance'"}
        format_table_columns(ws, headers=headers, currency_headers=currency,
                             count_headers={header for header in headers if "Count" in header})
        ws.freeze_panes = "A2"
        ws.auto_filter.ref = ws.dimensions
        return ws

    try:
        sheet("1305 Combined", COMBINED_HEADERS, review.combined)
        sheet("1305 Doc Recon", DOC_HEADERS, review.documents)
        sheet("1305 CWID Recon", CWID_HEADERS, review.students)
        sheet("1305 Period Totals", PERIOD_HEADERS, review.periods)
        for name in ("1305 Combined", "1305 Doc Recon", "1305 CWID Recon"):
            book[name].freeze_panes = "E2"
        book["1305 Period Totals"].freeze_panes = "D2"
        metadata = review.verification + [["Application version", app_version], ["Banner input method", banner_source],
            ["Run at (UTC)", datetime.now(timezone.utc).replace(tzinfo=None)]]
        verification = sheet("1305 Verification", ["Control / metadata", "Value"], metadata)
        verification.column_dimensions["A"].width = 62
        verification.column_dimensions["B"].width = 105
        for cells in verification.iter_rows(min_row=2):
            cells[1].alignment = Alignment(wrap_text=True, vertical="top")
            if isinstance(cells[1].value, float):
                cells[1].number_format = '#,##0.00;[Red](#,##0.00)'
            if isinstance(cells[1].value, str) and len(cells[1].value) > 95:
                verification.row_dimensions[cells[1].row].height = 45
        sheet("1305 Exceptions", ["Source", "Source Row", "Issue"],
              [[issue.source, issue.row, issue.issue] for issue in review.issues])
        book["1305 Exceptions"].column_dimensions["C"].width = 85
        for source in review.sources:
            if any(len(values) > len(source.headers) for _, values in source.rows):
                raise ValueError(f"{source.source} has source rows wider than the headers.")
            sheet(f"{source.source} Data", ["Source Row", *source.headers, "Selection Status"],
                [[number, *values, *([None] * (len(source.headers) - len(values))),
                  source.dispositions.get(number, "")] for number, values in source.rows])
        wrap_headers = {"Notes", "Notes / Explanation", "Description / Original Memo",
                        "Status", "Memo / Feed Document", "Issue"}
        for ws in book:
            for cell in ws[1]:
                if cell.value in {"Notes", "Notes / Explanation", "Status", "Review Status"}:
                    ws.column_dimensions[cell.column_letter].width = 45
            for row in ws.iter_rows(min_row=2):
                lines = 1
                for cell in row:
                    header = ws.cell(1, cell.column).value
                    if header in wrap_headers:
                        cell.alignment = Alignment(wrap_text=True, vertical="top")
                        width = max(1, ws.column_dimensions[cell.column_letter].width - 2)
                        lines = max(lines, ceil(len(str(cell.value or "")) / width))
                if lines > 1:
                    ws.row_dimensions[row[0].row].height = min(409, lines * 18)

        with tempfile.TemporaryDirectory(prefix=".1305-recon-", dir=output.parent) as directory:
            staging = Path(directory) / "reconciliation.xlsx"
            book.save(staging)

            def publish():
                created = False
                try:
                    with output.open("xb") as destination:
                        created = True
                        with staging.open("rb") as source:
                            shutil.copyfileobj(source, destination)
                except Exception:
                    if created:
                        output.unlink(missing_ok=True)
                    raise

            if cancellation:
                cancellation.publish(publish)
            else:
                publish()
    finally:
        book.close()
