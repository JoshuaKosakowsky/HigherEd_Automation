# Click/Save/Input functions

from playwright.sync_api import Page

from banner.modes import RunMode


def set_input_value(
    page: Page,
    selector: str,
    value: str,
    label: str = "Field",
    attempts: int = 3,
) -> None:
    loc = page.locator(selector).first
    loc.wait_for(state="visible", timeout=60_000)

    for attempt in range(1, attempts + 1):
        loc.click(force=True)
        page.keyboard.press("Control+A")
        page.keyboard.press("Backspace")
        page.wait_for_timeout(200)

        try:
            loc.fill("")
        except Exception:
            pass

        loc.click(force=True)
        loc.press_sequentially(str(value), delay=80)
        page.wait_for_timeout(300)

        current = loc.input_value(timeout=2_000).strip()

        if current == str(value).strip():
            print(f"{label} set OK: {value}")
            return

        print(f"{label} attempt {attempt} failed. Saw: {current!r}")

    raise RuntimeError(f"Could not set {label} to {value!r}.")


def click_first_available(page: Page, selectors: list[str], label: str = "button") -> None:
    last_error = None

    for sel in selectors:
        try:
            loc = page.locator(sel).first
            loc.wait_for(state="visible", timeout=5_000)
            loc.click(force=True)
            page.wait_for_timeout(500)
            return
        except Exception as e:
            last_error = e

    raise RuntimeError(f"Could not click {label}. Last error: {last_error}")


def banner_save(page: Page, *, mode: RunMode = RunMode.PROD) -> None:
    """
    TEST  = skip save
    PROD  = save normally
    DEBUG = save normally with extra logging
    """
    if mode == RunMode.TEST:
        print("[TEST MODE] Skipping Banner Save.")
        return

    if mode == RunMode.DEBUG:
        print("[DEBUG MODE] Attempting Banner Save...")

    save_selectors = [
        "li[data-member='SAVE_BT'] a[data-action='SAVE']",
        "li#save-bt a[data-action='SAVE']",
        "a[title='Save (F10)']",
        "a[aria-label='Save']",
        "a[data-action='SAVE']",
    ]

    try:
        click_first_available(page, save_selectors, label="Save")
        print("Clicked Save.")
    except Exception as e:
        if mode == RunMode.DEBUG:
            print(f"[DEBUG MODE] Save selector failed: {e}")
            print("[DEBUG MODE] Falling back to F10.")

        page.keyboard.press("F10")
        print("Pressed F10 to Save.")

    page.wait_for_timeout(800)

    if mode == RunMode.DEBUG:
        print("[DEBUG MODE] Banner Save attempt completed.")