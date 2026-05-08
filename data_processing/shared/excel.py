from openpyxl import Workbook
from pathlib import Path

import pandas as pd
import csv

def read_excel_sheet(path: Path, sheet: str) -> pd.DataFrame:
    """
    Read an Excel sheet and return a DataFrame.
    """
    if not path.exists():
        raise FileNotFoundError(f"Excel file not found: {path}")

    return pd.read_excel(path, sheet_name=sheet)


def validate_required_columns(
    df: pd.DataFrame,
    required_cols: set[str],
    source_name: str = "Excel file"
) -> None:
    """
    Ensure the DataFrame contains all required columns.
    """
    missing = required_cols - set(df.columns)

    if missing:
        raise ValueError(
            f"{source_name} missing required columns: {sorted(missing)}"
        )


def clean_text(val) -> str:
    """
    Convert Excel/pandas values into clean strings.
    """
    if pd.isna(val):
        return ""

    return str(val).strip()


def clean_optional_amount(val) -> float | None:
    """
    Convert amount-like Excel values into float or None.
    """
    if pd.isna(val):
        return None

    return float(val)

def csv_to_xlsx(csv_path: Path, xlsx_path: Path, sheet_name: str = "Sheet1") -> None:
    wb = Workbook()
    ws = wb.active
    ws.title = sheet_name

    with csv_path.open("r", encoding="utf-8-sig", newline="") as f:
        reader = csv.reader(f, delimiter=",", quotechar='"')
        for row in reader:
            ws.append(row)

    wb.save(xlsx_path)