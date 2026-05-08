from __future__ import annotations

from pathlib import Path

from playwright.sync_api import sync_playwright

from banner.config import BANNER_URL, get_banner_profile
from banner.tzrcrsf import run_tzrcrsf
from data_processing.course_fees.pipeline import run_course_fees_pipeline
from data_processing.shared.dates import compute_term_code
from data_processing.shared.files import ensure_dir


BROWSER_PROFILE = get_banner_profile("edge")

ONEDRIVE_ROOT = Path.home() / "OneDrive - Colorado Community College System"

COURSE_FEES_DIR = (
    ONEDRIVE_ROOT
    / "Accounts Receivable-Bursar - Documents"
    / "Rate Table"
)

THIRD_PARTY_DIR = (
    ONEDRIVE_ROOT
    / "FRCC Fiscal - 3rd Party"
)


def main() -> int:
    ensure_dir(BROWSER_PROFILE.profile_dir)

    with sync_playwright() as p:
        context = p.chromium.launch_persistent_context(
            user_data_dir=str(BROWSER_PROFILE.profile_dir),
            channel=BROWSER_PROFILE.channel,
            headless=False,
            viewport={"width": 1600, "height": 720},
            accept_downloads=True,
        )

        page = context.new_page()

        try:
            page.goto(BANNER_URL, wait_until="domcontentloaded")
            print("Opened Banner App Navigator.")

            raw_course_fees_file = run_tzrcrsf(
                page,
                context,
                rate_table_dir=COURSE_FEES_DIR,
                vpdi="FRCC",
            )

            print(f"Completed TZRCRSF raw output: {raw_course_fees_file}")

            term_code = compute_term_code()
            fiscal_year = term_code[2:4]

            csf_file = (
                COURSE_FEES_DIR
                / "CSF_FY"
                / f"FY{fiscal_year} Course Specific Fees.xlsx"
            )

            final_course_fees_file = run_course_fees_pipeline(
                banner_cfl_file=raw_course_fees_file,
                csf_file=csf_file,
                output_dir=raw_course_fees_file.parent,
                third_party_dir=THIRD_PARTY_DIR,
                write_debug_outputs=False,
            )

            print(f"Completed Course Fees output: {final_course_fees_file}")

            return 0

        finally:
            context.close()


if __name__ == "__main__":
    raise SystemExit(main())