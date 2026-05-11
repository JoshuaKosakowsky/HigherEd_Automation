from __future__ import annotations

from pathlib import Path

from playwright.sync_api import sync_playwright

from bankmobile.config import get_bankmobile_profile
from bankmobile.login import login_if_needed
from bankmobile.timeout_reversal import (
    archive_job_file,
    download_timeout_reversal_excel,
    get_latest_batch_job,
    goto_tandr_start,
    log,
    open_batch_detail,
    set_last_90_days_and_submit,
)
from data_processing.shared.files import ensure_dir
from data_processing.shared.logging import log

LOG_PREFIX = "Timeout/Reversal"


PROJECT_ROOT = Path(__file__).resolve().parents[2]

JOBS_DIR = PROJECT_ROOT / "data" / "timeout_reversal"

OUTPUT_DIR = (
    Path.home()
    / "OneDrive - Colorado Community College System"
    / "Accounts Receivable-Refund Control - Documents"
    / "BM Files"
    / "Timeout and Reversals"
)


def main() -> int:
    ensure_dir(JOBS_DIR)
    ensure_dir(OUTPUT_DIR)

    batch_id, job_file = get_latest_batch_job(JOBS_DIR)

    if not batch_id or not job_file:
        log(f"No new batch jobs found in {JOBS_DIR}. Exiting quietly.", prefix=LOG_PREFIX)
        return 0

    log(f"Found batch job: {batch_id}", prefix=LOG_PREFIX)
    log(f"Job file: {job_file}", prefix=LOG_PREFIX)

    profile = get_bankmobile_profile("chrome")
    ensure_dir(profile.profile_dir)

    with sync_playwright() as p:
        context = p.chromium.launch_persistent_context(
            user_data_dir=str(profile.profile_dir),
            channel=profile.channel,
            headless=False,
            accept_downloads=True,
        )

        try:
            page = context.new_page()

            login_if_needed(page)
            goto_tandr_start(page)
            set_last_90_days_and_submit(page)
            open_batch_detail(page, batch_id)

            output_file = download_timeout_reversal_excel(
                page,
                batch_id=batch_id,
                output_dir=OUTPUT_DIR,
            )

            log(f"Completed timeout/reversal download: {output_file}", prefix=LOG_PREFIX)

        finally:
            context.close()

    archive_job_file(job_file, JOBS_DIR)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())