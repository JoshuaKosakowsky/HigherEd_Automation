# Basic Navigation

from playwright.sync_api import Page


def open_form(page: Page, form: str, *, wait_selector: str | None = None) -> None:
    url = f"https://banner.cccs.edu/BannerAdmin/?form={form}"
    page.goto(url, wait_until="domcontentloaded")
    print(f"Opened Banner form {form}.")

    if wait_selector:
        page.wait_for_selector(wait_selector, timeout=120_000)


def next_section(page: Page) -> None:
    selectors = [
        "a[data-action='NEXT_BLOCK'][title*='Next Section']",
        "a[data-action='NEXT_BLOCK'][title*='Next Block']",
        "a[data-action='NEXT_BLOCK']",
        "button[data-action='NEXT_BLOCK']",
    ]

    for sel in selectors:
        try:
            btn = page.locator(sel).first
            btn.wait_for(state="visible", timeout=5_000)
            btn.click(force=True)
            page.wait_for_timeout(800)
            return
        except Exception:
            continue

    page.keyboard.down("Alt")
    page.keyboard.press("PageDown")
    page.keyboard.up("Alt")
    page.wait_for_timeout(800)


def start_over(page: Page) -> None:
    selectors = [
        "button[data-action='CLEAR-FORM']",
        "a[title='Start Over (F5)']",
        "button[title='Start Over (F5)']",
        "text=Start Over",
    ]

    for sel in selectors:
        try:
            btn = page.locator(sel).first
            if btn.count():
                btn.wait_for(state="visible", timeout=5_000)
                btn.click(force=True)
                page.wait_for_timeout(1_000)
                return
        except Exception:
            continue

    page.keyboard.press("F5")
    page.wait_for_timeout(1_000)