from dataclasses import dataclass
from pathlib import Path

import pandas as pd

from data_processing.shared.cwid import normalize_sid
from data_processing.shared.excel import (
    read_excel_sheet,
    validate_required_columns,
    clean_text,
    clean_optional_amount,
)


@dataclass
class DNRRecord:
    sid: str
    name: str
    semester: str
    amount: float | None


def load_dnrs(path: Path, sheet: str) -> dict[str, DNRRecord]:
    """
    Load the DNR file into a dictionary keyed by SID.

    Returns:
        {
            "S12345678": DNRRecord(...)
        }
    """
    df = read_excel_sheet(path, sheet)

    required_cols = {"SID", "Name", "Semester"}
    validate_required_columns(df, required_cols, source_name="DNR Excel file")

    out: dict[str, DNRRecord] = {}

    for _, row in df.iterrows():
        sid = normalize_sid(row.get("SID"))

        if not sid:
            continue

        if sid in out:
            raise ValueError(f"Duplicate SID found in DNR file: {sid}")

        out[sid] = DNRRecord(
            sid=sid,
            name=clean_text(row.get("Name")),
            semester=clean_text(row.get("Semester")),
            amount=clean_optional_amount(row.get("Amount")),
        )

    return out


def dnrs_for_term(dnrs: dict[str, DNRRecord], term: str) -> set[str]:
    """
    Return only DNR SIDs for a specific semester/term.
    """
    term = str(term).strip()

    return {
        sid
        for sid, record in dnrs.items()
        if record.semester == term
    }


def is_dnr_sid(dnrs: dict[str, DNRRecord], sid: str) -> bool:
    """
    Check whether a SID exists in the DNR list.
    """
    normalized_sid = normalize_sid(sid)

    if not normalized_sid:
        return False

    return normalized_sid in dnrs


def get_dnr_record(
    dnrs: dict[str, DNRRecord],
    sid: str
) -> DNRRecord | None:
    """
    Return the full DNR record for a SID, if found.
    """
    normalized_sid = normalize_sid(sid)

    if not normalized_sid:
        return None

    return dnrs.get(normalized_sid)