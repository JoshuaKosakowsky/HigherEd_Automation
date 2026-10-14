from __future__ import annotations

import csv
import json
from collections.abc import Iterator
from pathlib import Path

from shared.cancellation import CancellationToken

from data_processing.shared.tgiaccd import (
    fiscal_year_from_filename,
    iter_tgiaccd_rows,
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

    return validate_annual_files(files)


def validate_annual_files(files: list[Path]) -> list[Path]:
    """Validate and sort explicit annual uploads as well as discovered sources."""
    if not files:
        raise ValueError("Select at least one annual TGIACCD file.")
    for path in files:
        if path.suffix.lower() not in {".xlsx", ".csv"}:
            raise ValueError("Annual TGIACCD files must be .xlsx or .csv.")
        if not path.is_file():
            raise FileNotFoundError("An annual TGIACCD source file could not be found.")
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

    return sorted(files, key=fiscal_year_from_filename)


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


def iter_trends_rows(
    path: Path, *, required_columns: tuple[str, ...],
    cancellation: CancellationToken | None = None,
) -> Iterator[dict[str, object]]:
    """Stream both historical Excel exports and checked annual SQL CSVs."""
    if path.suffix.lower() == ".csv":
        with path.open(encoding="utf-8", newline="") as source:
            reader = csv.DictReader(source)
            if set(required_columns) - set(reader.fieldnames or ()):
                raise ValueError("Annual trends CSV is missing required columns.")
            for row in reader:
                if cancellation:
                    cancellation.check()
                yield row
    else:
        for row in iter_tgiaccd_rows(path, required_columns=required_columns):
            if cancellation:
                cancellation.check()
            yield row
