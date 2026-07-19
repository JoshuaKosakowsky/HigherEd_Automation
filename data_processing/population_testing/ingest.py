from pathlib import Path

import pandas as pd


def read_population_workbook(
    input_file: Path,
    *,
    sheet_name: str | int = 0,
) -> pd.DataFrame:
    """
    Read the source population worksheet without
    altering the original workbook.
    """
    if not input_file.exists():
        raise FileNotFoundError(
            f"Population workbook not found: {input_file}"
        )

    if input_file.suffix.lower() not in {".xlsx", ".xlsm"}:
        raise ValueError(
            "Population input must be an .xlsx or .xlsm workbook."
        )

    return pd.read_excel(
        input_file,
        sheet_name=sheet_name,
        dtype={
            "CWID": "string",
        },
    )