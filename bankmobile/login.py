from __future__ import annotations

import os

from playwright.sync_api import Page

from bankmobile.config import LOGIN_URL
from data_processing.shared.logging import log


LOG_PREFIX = "BankMobile"


def login_if_needed(page: Page) -> None:
    user = os.environ.get("BM_USER")
    pw = os.environ.get("BM_PASS")

    if not user or not pw:
        raise RuntimeError("Missing BM_USER/BM_PASS environment variables.")

    page.goto(LOGIN_URL, wait_until="domcontentloaded")
    page.wait_for_timeout(500)

    if page.locator("#userNameInput").count() == 0:
        log("Already logged in or session restored.", prefix=LOG_PREFIX)
        return

    log("Login required. Entering credentials.", prefix=LOG_PREFIX)

    page.fill("#userNameInput", user)
    page.fill("#passwordInput", pw)

    with page.expect_navigation(wait_until="domcontentloaded"):
        page.click("button[type='submit'].btn-login")

    page.wait_for_timeout(500)

    if page.locator("#userNameInput").count() > 0:
        raise RuntimeError("BankMobile login appears to have failed.")

    log("Login successful.", prefix=LOG_PREFIX)