# Functions for login functionality only

import os
from playwright.sync_api import TimeoutError as PWTimeoutError, Page


def is_logged_in(page: Page) -> bool:
    try:
        return page.locator("input[name='search']").first.is_visible(timeout=2_000)
    except Exception:
        return False


def login_if_needed(page: Page, timeout_ms: int = 120_000) -> None:
    user = os.getenv("BANNER_USER")
    pw = os.getenv("BANNER_PASS")

    if not user or not pw:
        raise RuntimeError(
            "Missing env vars. Expected BANNER_USER and BANNER_PASS."
        )

    page.wait_for_load_state("domcontentloaded")
    page.wait_for_timeout(1_000)

    if is_logged_in(page):
        print("Already logged into Banner.")
        return

    print("Login needed; attempting credential login...")

    sid_input = page.locator(
        "input[type='text'], "
        "input[type='email'], "
        "input[name*='user' i], "
        "input[id*='user' i]"
    ).first

    pw_input = page.locator(
        "input[type='password'], "
        "input[name*='pass' i], "
        "input[id*='pass' i]"
    ).first

    try:
        page.wait_for_function(
            """() => {
                const hasSearch = document.querySelector("input[name='search']");
                const hasPass = document.querySelector(
                    "input[type='password'], input[name*='pass' i], input[id*='pass' i]"
                );
                return !!hasSearch || !!hasPass;
            }""",
            timeout=timeout_ms,
        )
    except PWTimeoutError:
        raise RuntimeError("Neither Banner search box nor login field appeared.")

    if is_logged_in(page):
        print("Session restored without login.")
        return

    pw_input.wait_for(state="visible", timeout=timeout_ms)

    if sid_input.count():
        try:
            sid_input.fill(user)
        except Exception:
            pass

    pw_input.fill(pw)
    page.keyboard.press("Enter")

    page.wait_for_selector("input[name='search']", timeout=timeout_ms)
    print("Banner login successful.")