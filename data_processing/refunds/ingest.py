from __future__ import annotations

from pathlib import Path

import pandas as pd

from .extract import _validate_complete_result


SUPPORTED_DOWNLOAD_SUFFIXES = {".csv", ".xlsx", ".xlsm"}


def read_refund_download(
    path: Path,
    *,
    label: str,
    expected_target_term: str,
) -> pd.DataFrame:
    """Read and validate one complete manual Insights download."""
    if not path.is_file():
        raise FileNotFoundError(f"{label} download was not found: {path}")
    suffix = path.suffix.lower()
    if suffix not in SUPPORTED_DOWNLOAD_SUFFIXES:
        raise ValueError(
            f"{label} download must be CSV, XLSX, or XLSM: {path}"
        )
    if suffix == ".csv":
        frame = pd.read_csv(path, dtype="object")
    else:
        frame = pd.read_excel(path, dtype="object")

    result = _validate_complete_result(frame, label, None)
    if "extract_target_term" not in result.columns:
        raise ValueError(
            f"{label} download is missing extract_target_term. Run the provided "
            "manual export SQL rather than the allocation report."
        )
    terms = {
        str(value).strip()
        for value in result["extract_target_term"].dropna().tolist()
        if str(value).strip()
    }
    if result.empty:
        terms = {expected_target_term}
    if terms != {expected_target_term}:
        displayed = ", ".join(sorted(terms)) or "[blank]"
        raise ValueError(
            f"{label} download contains target term {displayed}, but this run "
            f"expects {expected_target_term}."
        )
    return result.drop(columns=["extract_target_term"])
