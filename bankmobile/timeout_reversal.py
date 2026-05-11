from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

from playwright.sync_api import Page, TimeoutError as PlaywrightTimeoutError

from bankmobile.config import TANDR_URL
from data_processing.shared.logging import log


LOG_PREFIX = "Timeout Reversal"


def get_latest_batch_job(jobs_dir: Path) -> tuple[str | None, Path | None]:
    job_files = sorted(
        jobs_dir.glob("batch_*.json"),
        key=lambda p: p.stat().st_mtime,
        reverse=True,
    )

    if not job_files:
        return None, None

    latest = job_files[0]
    data = json.loads(latest.read_text(encoding="utf-8"))

    batch_id = str(data["batch_id"]).strip()
    return batch_id, latest


def archive_job_file(job_file: Path, jobs_dir: Path) -> None:
    processed_dir = jobs_dir / "processed"
    processed_dir.mkdir(parents=True, exist_ok=True)

    target = processed_dir / job_file.name
    job_file.rename(target)

    log(f"Archived job file to {target}", prefix=LOG_PREFIX)


def goto_tandr_start(page: Page) -> None:
    for attempt in range(1, 4):
        page.goto(TANDR_URL, wait_until="domcontentloaded")

        try:
            page.wait_for_selector("#dateRangeOption", timeout=8_000)
            log("Timeouts and Reversals page loaded.", prefix=LOG_PREFIX)
            return
        except PlaywrightTimeoutError:
            if page.locator("#userNameInput").count() > 0:
                raise RuntimeError("Redirected back to login when navigating to T&R page.")

            page.wait_for_timeout(1_000 * attempt)

    raise RuntimeError("Could not reach T&R page after retries.")


def set_last_90_days_and_submit(page: Page) -> None:
    page.wait_for_selector("#dateRangeOption", timeout=20_000)
    page.select_option("#dateRangeOption", value="last90Days")

    page.click("input[type='submit'][name='submit'][value='Submit']")

    try:
        page.wait_for_load_state("domcontentloaded", timeout=20_000)
    except PlaywrightTimeoutError:
        pass

    log("Selected Last 90 Days and submitted search.", prefix=LOG_PREFIX)


def open_batch_detail(page: Page, batch_id: str) -> None:
    page.wait_for_selector("a[href*='results.do?revbatchid=']", timeout=20_000)

    detail_link = page.locator(
        f"a[href*='results.do?revbatchid={batch_id}']"
    ).first

    if detail_link.count() == 0:
        raise RuntimeError(
            f"Could not find Detail link for batch_id={batch_id}. "
            f"Current URL: {page.url}"
        )

    with page.expect_navigation(wait_until="domcontentloaded"):
        detail_link.click()

    log(f"Opened detail page for batch {batch_id}.", prefix=LOG_PREFIX)


def download_timeout_reversal_excel(
    page: Page,
    *,
    batch_id: str,
    output_dir: Path,
) -> Path:
    output_dir.mkdir(parents=True, exist_ok=True)

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    output_file = output_dir / f"TimeoutReversal_{batch_id}_{timestamp}.xls"

    with page.expect_download() as download_info:
        page.click("input[type='submit'][name='submit'][value='Download to Excel']")

    download = download_info.value
    download.save_as(output_file)

    log(f"Downloaded Excel file: {output_file}", prefix=LOG_PREFIX)
    print(f"DOWNLOADED_FILE={output_file}", flush=True)

    return output_file