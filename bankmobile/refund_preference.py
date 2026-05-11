from __future__ import annotations

import re
import time

from playwright.sync_api import Page, TimeoutError as PlaywrightTimeoutError

from bankmobile.config import CARD_SEARCH_URL
from data_processing.shared.logging import log


LOG_PREFIX = "Refund Preference"


def normalize_sid(value) -> str | None:
    if value is None:
        return None

    sid = str(value).strip().replace(".0", "")

    if not sid:
        return None

    if re.fullmatch(r"\d{8}", sid):
        sid = f"S{sid}"

    if re.fullmatch(r"S\d{8}", sid):
        return sid

    return None


def goto_card_search(page: Page) -> None:
    for attempt in range(1, 4):
        page.goto(CARD_SEARCH_URL, wait_until="domcontentloaded")

        if page.locator("#userNameInput").count() > 0:
            raise RuntimeError("Redirected to login when opening Card Search.")

        try:
            page.wait_for_selector("input[name='id1']", timeout=8_000)
            log("Card Search page loaded.", prefix=LOG_PREFIX)
            return
        except PlaywrightTimeoutError:
            page.wait_for_timeout(1_000 * attempt)

    raise RuntimeError("Could not reach Card Management search page.")


def safe_click(page: Page, selector: str, timeout: int = 15_000) -> None:
    page.wait_for_selector(selector, timeout=timeout)
    page.locator(selector).first.click()


def safe_fill(page: Page, selector: str, value: str, timeout: int = 15_000) -> None:
    page.wait_for_selector(selector, timeout=timeout)
    loc = page.locator(selector).first
    loc.click()
    loc.fill("")
    loc.fill(value)


def lookup_refund_preference_for_sid(page: Page, sid: str) -> dict:
    sid_input_selector = "input[name='id1']"
    submit_selector = "input[type='submit'][name='submit'][value='Submit']"
    results_table_selector = "table:has(td.formHead:text-is('Refund Preference'))"

    started = time.time()

    safe_fill(page, sid_input_selector, sid)
    safe_click(page, submit_selector)

    try:
        page.wait_for_selector(results_table_selector, timeout=20_000)
    except PlaywrightTimeoutError:
        return {
            "Status": "TIMEOUT",
            "BM_Name": None,
            "RefundPreference": None,
            "ElapsedSec": round(time.time() - started, 2),
        }

    table = page.locator(results_table_selector).first

    if table.locator("text=No matching results.").count() > 0:
        return {
            "Status": "NOT_FOUND",
            "BM_Name": None,
            "RefundPreference": None,
            "ElapsedSec": round(time.time() - started, 2),
        }

    row = table.locator("tr.rowOddBG, tr.rowEvenBG").first
    tds = row.locator("td")

    bm_name = tds.nth(1).inner_text().strip()
    refund_preference = tds.nth(tds.count() - 1).inner_text().strip()

    return {
        "Status": "OK",
        "BM_Name": bm_name,
        "RefundPreference": refund_preference,
        "ElapsedSec": round(time.time() - started, 2),
    }