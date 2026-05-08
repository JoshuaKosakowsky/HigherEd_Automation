"""
Download FGIGLAC reports via Playwright using a persistent browser profile (so 2FA persists).

PowerShell should set:
  $env:BANNER_USER
  $env:BANNER_PASS

This script:
- Opens Banner App Navigator
- Logs in only if needed (session might already exist)
- Opens FGIGLAC
- Loops through fund/acct pairs
- Runs report, exports CSV, saves download as FGIGLAC_{fund}_{acct}_{mm-dd-yy}.xlsx
"""


from __future__ import annotations

from pathlib import Path

from playwright.sync_api import sync_playwright

from banner.config import BANNER_URL
from banner.browser import launch_banner_context
from banner.login import login_if_needed
from banner.fgiglac import run_fgiglac_batch
from data_processing.shared.files import ensure_dir
from data_processing.shared.paths import DOWNLOAD_DIR, FGIGLAC_DIR


BROWSER = "edge"


FUND_ACCOUNT_PAIRS = [
    ("011042", "113070"),  # Cashnet
    ("011043", "113070"),  # WC - BCC
    ("026010", "113080"),
    ("026011", "113080"),
    ("026012", "113080"),
    ("001010", "111010"),  # Cash Log / Keyed
    ("011010", "113050"),  # Collections
    ("011010", "221080"),  # BankMobile
]


def main() -> int:
    ensure_dir(DOWNLOAD_DIR)
    ensure_dir(FGIGLAC_DIR)

    with sync_playwright() as p:
        context = launch_banner_context(
            p,
            browser=BROWSER,
            headless=False,
            accept_downloads=True,
            downloads_path=DOWNLOAD_DIR,
        )

        page = context.new_page()

        try:
            page.goto(BANNER_URL, wait_until="domcontentloaded")
            print("Opened Banner App Navigator.")

            login_if_needed(page)

            outputs = run_fgiglac_batch(
                page,
                fund_account_pairs=FUND_ACCOUNT_PAIRS,
                download_dir=DOWNLOAD_DIR,
                dest_root=FGIGLAC_DIR,
)

            print(
                f"Completed FGIGLAC downloads: "
                f"{len(outputs)}/{len(FUND_ACCOUNT_PAIRS)}"
            )

            return 0 if len(outputs) == len(FUND_ACCOUNT_PAIRS) else 2

        finally:
            context.close()


if __name__ == "__main__":
    raise SystemExit(main())