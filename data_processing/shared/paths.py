from pathlib import Path


HOME = Path.home()

DOWNLOAD_DIR = HOME / "Downloads"

ONEDRIVE_ROOT = HOME / "OneDrive - Colorado Community College System"

AR_REPORTS_ROOT = (
    ONEDRIVE_ROOT
    / "Accounts Receivable - AR Supervisors - AR Supervisors"
    / "Daily Reports"
)

DNR_EXCEL = (
    ONEDRIVE_ROOT
    / "Refunds"
    / "Auto and Manual Refunds"
    / "Reversals- DO NOT REFUND PA.xlsx"
)

FGIGLAC_DIR = AR_REPORTS_ROOT / "FGIGLAC"