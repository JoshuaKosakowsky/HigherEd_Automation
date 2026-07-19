from __future__ import annotations

import json
from pathlib import Path

from data_processing.shared.tgiaccd import (
    fiscal_year_from_filename,
)


def discover_tgiaccd_files(
    input_dir: Path,
    *,
    file_pattern: str,
) -> list[Path]:
    """
    Find and sort all fiscal-year TGIACCD workbooks.
    """
    if not input_dir.exists():
        raise FileNotFoundError(
            f"Input directory not found: {input_dir}"
        )

    files = sorted(
        input_dir.glob(file_pattern),
        key=fiscal_year_from_filename,
    )

    if not files:
        raise FileNotFoundError(
            "No TGIACCD workbooks matched "
            f"{file_pattern!r} in {input_dir}."
        )

    years = [
        fiscal_year_from_filename(path)
        for path in files
    ]

    duplicate_years = {
        year
        for year in years
        if years.count(year) > 1
    }

    if duplicate_years:
        raise ValueError(
            "More than one workbook was found for fiscal "
            f"year(s): {sorted(duplicate_years)}"
        )

    return files


def read_detail_codes(
    path: Path,
) -> dict[str, dict[str, object]]:
    """
    Load Banner detail-code accounting metadata.
    """
    if not path.exists():
        raise FileNotFoundError(
            f"Detail-code reference not found: {path}"
        )

    with path.open(
        "r",
        encoding="utf-8",
    ) as source:
        raw_detail_codes = json.load(source)

    return {
        str(code).strip().upper(): metadata
        for code, metadata in raw_detail_codes.items()
    }