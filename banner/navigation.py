# Basic Navigation

from playwright.sync_api import Page

from banner.actions import click_first_available
from banner.config import BANNER_URL


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
        "a[data-action='CLEAR-FORM']",
        "text=Start Over",
    ]

    try:
        click_first_available(page, selectors, label="Start Over")
        print("Clicked Start Over.", flush=True)
        return
    except Exception:
        pass

    page.keyboard.press("F5")
    page.wait_for_timeout(1_000)
    print("Pressed F5 for Start Over.", flush=True)
    

def click_keyblock_go(page: Page) -> None:
    selectors = [
        "button[data-member='EXECUTE_BTN'][data-action='NEXT_BLOCK']",
        "button[aria-label='Go']",
        "button[data-action='NEXT_BLOCK']",
        "button:has-text('Go')",
    ]

    try:
        click_first_available(page, selectors, label="Go")
        print("Clicked Go.", flush=True)
    except Exception:
        print("Go button not found/clickable; falling back to Enter.", flush=True)
        page.keyboard.press("Enter")
        page.wait_for_timeout(800)


def click_insert(page: Page) -> None:
    selectors = [
        "a[title='Insert (F6)']",
        "button[title='Insert (F6)']",
        "text=Insert",
    ]

    click_first_available(page, selectors, label="Insert")
    print("Clicked Insert (F6).", flush=True)


def click_no_on_save_warning(page: Page) -> None:
    selectors = [
        "button:has-text('No')",
        "[role='button']:has-text('No')",
        "text=No",
    ]

    click_first_available(page, selectors, label="No on save warning")
    print("Clicked 'No' on save-changes warning.", flush=True)


def close_banner_notification(page: Page) -> None:
    try:
        bell = page.locator("#notifications a.notification-toggle").first
        if bell.count():
            bell.click()
            page.wait_for_timeout(400)
            print("Closed Banner notification bell.", flush=True)
    except Exception:
        pass


def wait_for_save_success(page: Page) -> None:
    selectors = [
        "text=Saved successfully",
        "#notifications-menu text=Saved successfully",
        "li.notification-success",
    ]

    for sel in selectors:
        try:
            page.locator(sel).first.wait_for(state="visible", timeout=5_000)
            print("Confirmed save success notification.", flush=True)
            return
        except Exception:
            continue

    raise RuntimeError("Save was clicked, but Banner success notification was not detected.")