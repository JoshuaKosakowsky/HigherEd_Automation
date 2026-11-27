"""Resolve institution-managed local paths without workstation-specific names."""

from __future__ import annotations

import ctypes
import os
import sys
from collections.abc import Mapping
from datetime import date
from pathlib import Path


ONEDRIVE_ENVIRONMENT_VARIABLE = "OneDriveCommercial"
ONEDRIVE_FALLBACK_DIRECTORY = "OneDrive - Colorado School of Mines"
BURSAR_RELATIVE_DIRECTORY = Path(
    "GRP-Bursar Office - General",
    "Y-Brswork",
)
GUI_ACCESS_RELATIVE_DIRECTORY = BURSAR_RELATIVE_DIRECTORY / "Staff Folders" / ".highered_automation"
GUI_ACCESS_FILENAME = "gui_access.json"
GRADUATE_CONTRACT_RECON_FOLDER = "1305 - Grad Contract (1323)"
_MONTH_NAMES = (
    "January", "February", "March", "April", "May", "June",
    "July", "August", "September", "October", "November", "December",
)
WINDOWS_HIDDEN_ATTRIBUTE = 0x2
INVALID_WINDOWS_ATTRIBUTES = 0xFFFFFFFF


class MinesPathError(RuntimeError):
    """Raised when a required Mines-managed local path cannot be resolved."""


def get_mines_onedrive_root(
    environment: Mapping[str, str] | None = None,
) -> Path:
    """Return the locally synchronized Mines OneDrive root."""
    values = os.environ if environment is None else environment
    configured = values.get(ONEDRIVE_ENVIRONMENT_VARIABLE, "").strip()
    if configured:
        return Path(configured)

    user_profile = values.get("USERPROFILE", "").strip()
    if user_profile:
        return Path(user_profile) / ONEDRIVE_FALLBACK_DIRECTORY

    raise MinesPathError(
        "The Mines OneDrive location could not be resolved. Confirm OneDrive "
        "is signed in and OneDriveCommercial is available."
    )


def get_shared_gui_access_path(
    environment: Mapping[str, str] | None = None,
) -> Path:
    """Return the shared Bursar GUI access-policy path."""
    return (
        get_mines_onedrive_root(environment)
        / GUI_ACCESS_RELATIVE_DIRECTORY
        / GUI_ACCESS_FILENAME
    )


def get_shared_detail_codes_path(
    environment: Mapping[str, str] | None = None,
) -> Path:
    """Return the centrally maintained Banner reference beside GUI permissions."""
    return get_shared_gui_access_path(environment).with_name("detail_codes.json")


def get_shared_csmf_balances_directory(
    environment: Mapping[str, str] | None = None,
) -> Path:
    """Return the shared, fiscal-year-specific CSMF opening-balance location."""
    return get_shared_gui_access_path(environment).parent / "csmf_opening_balances"


def get_shared_reconciliations_directory(
    environment: Mapping[str, str] | None = None,
) -> Path:
    return get_mines_onedrive_root(environment) / BURSAR_RELATIVE_DIRECTORY / "Reconciliations"


def _fiscal_folder_names(day: date) -> tuple[str, str]:
    # Keep workbook imports out of the app's startup path.
    from data_processing.shared.source_exports import fiscal_scope

    fiscal_year, period, _ = fiscal_scope(day)
    month = _MONTH_NAMES[day.month - 1]
    return f"FY{fiscal_year % 100:02d}", f"{period} - {month} {day.year}"


def get_graduate_contract_recon_directory(
    day: date, environment: Mapping[str, str] | None = None,
) -> Path:
    """Build the shared 1305 filing directory for the workstation's run date."""
    fiscal_year, period = _fiscal_folder_names(day)
    return (get_shared_reconciliations_directory(environment) / fiscal_year
            / GRADUATE_CONTRACT_RECON_FOLDER / period)


def get_papercut_scan_directory(environment: Mapping[str, str] | None = None) -> Path:
    return get_mines_onedrive_root(environment) / "Apps" / "Scans for PaperCut MF"


def get_cashnet_copies_directory(day: date, environment: Mapping[str, str] | None = None) -> Path:
    fiscal_year, _ = _fiscal_folder_names(day)
    return (get_mines_onedrive_root(environment) / "GRP-Office of the Controller - Documents"
            / "Accounting" / "Accounting (Shared)" / "CASHIER" / "CASHNet Copies" / fiscal_year)


def get_refund_review_directory(
    day: date, environment: Mapping[str, str] | None = None,
) -> Path:
    """Build the fiscal filing path under the synced Bursar RFND folder."""
    base = get_mines_onedrive_root(environment) / BURSAR_RELATIVE_DIRECTORY / "Refund" / "RFND"
    if not base.is_dir():
        raise MinesPathError(
            f"The shared OneDrive refund folder is unavailable: {base}. "
            "Check that the Bursar library is synced."
        )
    fiscal_year, period = _fiscal_folder_names(day)
    return base / fiscal_year / "Daily Pending Refunds" / period


def get_shared_csmf_foundation_directory(
    environment: Mapping[str, str] | None = None,
) -> Path:
    return (get_mines_onedrive_root(environment) / BURSAR_RELATIVE_DIRECTORY
            / "External Partners" / "CSM Foundation")


def get_csmf_foundation_filing_directory(
    day: date, environment: Mapping[str, str] | None = None,
) -> Path:
    """Build the fiscal filing path beneath the synced CSM Foundation folder."""
    base = get_shared_csmf_foundation_directory(environment)
    if not base.is_dir():
        raise MinesPathError(
            f"The shared OneDrive CSM Foundation folder is unavailable: {base}. "
            "Check that the Bursar library is synced."
        )
    fiscal_year, period = _fiscal_folder_names(day)
    return base / fiscal_year / period


def get_shared_wf_quarterly_recon_directory(
    environment: Mapping[str, str] | None = None,
) -> Path:
    return (get_mines_onedrive_root(environment) / BURSAR_RELATIVE_DIRECTORY
            / "Collections" / "W&F" / "Quarterly Recon")


def get_wf_recon_filing_directory(
    day: date, environment: Mapping[str, str] | None = None,
) -> Path:
    """Build the fiscal filing path beneath the synced W&F Quarterly Recon folder."""
    base = get_shared_wf_quarterly_recon_directory(environment)
    if not base.is_dir():
        raise MinesPathError(
            f"The shared OneDrive W&F Quarterly Recon folder is unavailable: {base}. "
            "Check that the Bursar library is synced."
        )
    fiscal_year, period = _fiscal_folder_names(day)
    return base / fiscal_year / period


def ensure_hidden_directory(
    directory: Path,
    *,
    platform: str = sys.platform,
) -> None:
    """Create a directory and apply Windows' cosmetic Hidden attribute."""
    directory.mkdir(parents=True, exist_ok=True)
    if platform != "win32":
        return

    kernel32 = ctypes.windll.kernel32
    attributes = kernel32.GetFileAttributesW(str(directory))
    if attributes == INVALID_WINDOWS_ATTRIBUTES:
        raise MinesPathError(f"Windows could not inspect the folder: {directory}")
    if not kernel32.SetFileAttributesW(
        str(directory), attributes | WINDOWS_HIDDEN_ATTRIBUTE
    ):
        raise MinesPathError(f"Windows could not hide the folder: {directory}")
