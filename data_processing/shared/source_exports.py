"""Header-based report imports and exact values shared by reconciliation workflows."""

from __future__ import annotations

import csv
import math
import re
from dataclasses import dataclass, field
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from pathlib import Path
from collections.abc import Mapping

import pandas as pd
from openpyxl import load_workbook
from openpyxl.utils.datetime import from_excel

from data_processing.shared.tgiaccd import clean_tgiaccd_header

ZERO = Decimal("0.00")
CENT = Decimal("0.01")


def header_key(value: object) -> str:
    return re.sub(r"[^a-z0-9]", "", clean_tgiaccd_header(value).casefold())


def text(value: object) -> str:
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return ""
    if isinstance(value, (float, Decimal)) and math.isfinite(value) and value == int(value):
        return str(int(value))
    return str(value).strip()


def fiscal_scope(day: date) -> tuple[int, str, str]:
    """Match shared/fiscal_period.ps1: July P01, June P12, ending-year FY."""
    year = day.year + (day.month >= 7)
    period = (day.month + 5) % 12 + 1
    return year, f"P{period:02d}", f"Q{(period - 1) // 3 + 1}"


def parse_date(value: object) -> date:
    if isinstance(value, datetime):
        return value.date()
    if type(value) is date:
        return value
    if isinstance(value, (float, int)) and not isinstance(value, bool):
        if not 1 <= value <= 2958465:
            raise ValueError("Invalid date")
        return from_excel(value).date()
    value = text(value)
    try:
        # Preserve the source calendar date rather than shifting time zones.
        return datetime.fromisoformat(value.replace("Z", "+00:00")).date()
    except ValueError:
        for pattern in ("%m/%d/%Y", "%m/%d/%y", "%m/%d/%Y %H:%M:%S", "%m/%d/%Y %I:%M:%S %p"):
            try:
                return datetime.strptime(value, pattern).date()
            except ValueError:
                continue
    raise ValueError("Invalid date")


def money(value: object, *, blank_zero: bool = False) -> Decimal:
    value = text(value)
    if not value and blank_zero:
        return ZERO
    if value.startswith("(") and value.endswith(")"):
        value = "-" + value[1:-1]
    try:
        amount = Decimal(value.replace(",", "").replace("$", ""))
        if not amount.is_finite() or amount != amount.quantize(CENT):
            raise ValueError("Amount must have cents precision")
        return amount.quantize(CENT)
    except (InvalidOperation, ValueError):
        raise ValueError("Invalid amount or cents precision") from None


@dataclass
class SourceData:
    source: str
    label: str
    headers: list[str]
    rows: list[tuple[int, list[object]]]
    columns: dict[str, int]
    dispositions: dict[int, str] = field(default_factory=dict)

    def value(self, row: list[object], name: str) -> object:
        col = self.columns.get(name)
        return row[col] if col is not None and col < len(row) else None


def match_columns(
    headers: list[object], source: str, aliases: Mapping[str, tuple[str, ...]],
    required: tuple[str, ...],
) -> dict[str, int] | None:
    keys = [header_key(value) for value in headers]
    columns = {}
    for name, choices in aliases.items():
        matches = [keys.index(header_key(choice)) for choice in choices if header_key(choice) in keys]
        if matches:
            # Two financial aliases in one source could mean pre-manipulated data.
            if name in required and len(set(matches)) > 1:
                raise ValueError(f"{source} has ambiguous columns for {choices[0]}.")
            columns[name] = matches[0]
    if not all(name in columns for name in required):
        return None
    populated = [key for key in keys if key]
    if len(populated) != len(set(populated)):
        raise ValueError(f"{source} has duplicate column headers.")
    return columns


def read_source_table(
    path: Path, source: str, aliases: Mapping[str, tuple[str, ...]], required: tuple[str, ...],
) -> SourceData:
    """Locate one matching source sheet, including exports with title rows."""
    candidates = []

    def inspect(name, values):
        iterator = iter(values)
        for row_number, row in enumerate(iterator, 1):
            if row_number > 30:
                break
            columns = match_columns(list(row), source, aliases, required)
            if columns is not None:
                headers = [text(value) for value in row]
                candidates.append(SourceData(source, f"{path.name} / {name}", headers,
                    [(number, list(values)) for number, values in enumerate(iterator, row_number + 1)], columns))
                break

    if path.suffix.lower() == ".csv":
        with path.open(encoding="utf-8-sig", newline="") as handle:
            inspect("CSV", csv.reader(handle))
    elif path.suffix.lower() in {".xlsx", ".xlsm"}:
        book = load_workbook(path, read_only=True, data_only=False)
        try:
            for sheet in book:
                # Some Workday exports declare A1 as the used range despite
                # containing a full report. Read actual cells, not that metadata.
                sheet.reset_dimensions()
                inspect(sheet.title, sheet.iter_rows(values_only=True))
        finally:
            book.close()
    else:
        raise ValueError(f"{source} must be an XLSX, XLSM, or CSV export.")
    if not candidates:
        needed = ", ".join(aliases[name][0] for name in required)
        raise ValueError(f"No {source} source sheet with the required headers: {needed}. Upload the original export.")
    if len(candidates) != 1:
        raise ValueError(f"Multiple {source} source sheets found. Upload a workbook with only one matching source sheet.")
    return candidates[0]


