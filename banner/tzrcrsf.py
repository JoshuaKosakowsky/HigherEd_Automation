from __future__ import annotations

from datetime import date
from pathlib import Path

from playwright.sync_api import TimeoutError as PWTimeoutError

from banner.login import login_if_needed
from data_processing.shared.files import ensure_dir
from data_processing.shared.dates import stamp_yyyymmdd, compute_term_code


FORM = "TZRCRSF"
EXPECTED_HEADER_PREFIX = "SSBSECT_VPDI_CODE,SSBSECT_TERM_CODE,"

BANNER_UI_GARBAGE_MARKERS = [
    "Saved Output Review GJIREVO",
    "Show Document (Save and Print File)",
    "danger: You have selected to Show File",
    "Ellucian. All rights reserved.",
    "GUROUTP.OUTPUT_LINE",
]


def open_tzrcrsf(page) -> None:
    url = f"https://banner.cccs.edu/BannerAdmin/?form={FORM}"
    page.goto(url, wait_until="domcontentloaded")
    print(f"Opened form {FORM}.")

    process_sel = "id=inp:key_block_keyblckJob"
    page.wait_for_selector(process_sel, timeout=120_000)
    print("Process key block detected.")


def set_process_and_go(page) -> None:
    process_sel = "id=inp:key_block_keyblckJob"
    go_btn_sel = "button[data-action='NEXT_BLOCK'][data-member='EXECUTE_BTN']"

    proc = page.locator(process_sel).first
    proc.wait_for(state="visible", timeout=60_000)

    proc.click(force=True)
    page.keyboard.press("Control+A")
    page.keyboard.press("Backspace")
    page.wait_for_timeout(200)

    proc.press_sequentially(FORM, delay=80)
    page.wait_for_timeout(300)

    val = proc.input_value()
    if val.strip() != FORM:
        raise RuntimeError(f"Process field failed to set. Saw '{val}'.")

    print(f"Process set to {FORM}")

    try:
        page.locator(go_btn_sel).wait_for(state="visible", timeout=60_000)
        page.locator(go_btn_sel).click()
        print("Clicked Go.")
    except Exception:
        print("Go button not clickable; using Alt+PageDown.")
        page.keyboard.down("Alt")
        page.keyboard.press("PageDown")
        page.keyboard.up("Alt")

    page.wait_for_timeout(1_500)


def wait_for_gjapctl_params(page) -> None:
    page.wait_for_url("**/BannerAdmin/?form=GJAPCTL", timeout=120_000)
    page.wait_for_selector("div.grid-canvas div.slick-row", timeout=120_000)
    print("GJAPCTL parameter grid ready.")


def _set_gjapctl_param_by_row(page, row_index: int, value: str, label: str) -> None:
    cell = page.locator(f"#grdGjbprun_col2_{row_index}_row").first
    cell.wait_for(state="visible", timeout=60_000)
    cell.scroll_into_view_if_needed()

    text_div = cell.locator("div.ui-text[data-member='GJBPRUN_VALUE']").first

    def read_cell_text() -> str:
        try:
            if text_div.count():
                return (text_div.inner_text() or "").strip()
        except Exception:
            pass

        try:
            return (cell.inner_text() or "").strip()
        except Exception:
            return ""

    for attempt in range(1, 8):
        try:
            cell.click(force=True, timeout=5_000)

            box = cell.bounding_box()
            if box:
                x = box["x"] + box["width"] / 2
                y = box["y"] + box["height"] / 2

                page.mouse.click(x, y)
                page.wait_for_timeout(120)
                page.mouse.dblclick(x, y)
                page.wait_for_timeout(180)

            page.keyboard.press("F2")
            page.wait_for_timeout(150)

            page.keyboard.press("Control+A")
            page.wait_for_timeout(50)
            page.keyboard.press("Backspace")
            page.wait_for_timeout(80)

            page.keyboard.type(value, delay=80)
            page.wait_for_timeout(120)

            page.keyboard.press("Tab")
            page.wait_for_timeout(450)

            shown = read_cell_text()
            if value in shown:
                print(f"{label} set to {value}")
                return

            page.wait_for_timeout(400)
            shown = read_cell_text()
            if value in shown:
                print(f"{label} set to {value}")
                return

            raise RuntimeError(f"After commit, saw '{shown}'")

        except Exception as e:
            print(f"Attempt {attempt} to set {label} failed: {e}")
            page.wait_for_timeout(500)

    raise RuntimeError(f"Could not set {label} after multiple attempts.")


def set_gjapctl_params(page, term_code: str, vpdi: str = "FRCC") -> None:
    _set_gjapctl_param_by_row(page, 0, term_code, "TERM CODE")
    _set_gjapctl_param_by_row(page, 1, vpdi, "VPDI CODE")


def next_section(page) -> None:
    next_btn = page.locator("a[data-action='NEXT_BLOCK'][title*='Next Section']").first

    try:
        next_btn.wait_for(state="visible", timeout=20_000)
        next_btn.scroll_into_view_if_needed()
        next_btn.click(force=True, timeout=5_000)
        print("Clicked Next Section.")
    except Exception:
        print("Next Section click failed; using Alt+PageDown.")
        page.keyboard.down("Alt")
        page.keyboard.press("PageDown")
        page.keyboard.up("Alt")

    page.wait_for_timeout(800)


def wait_for_submit_block(page) -> None:
    page.locator("div[data-member='DISPLAY_SAVE_DEFAULTS']").first.wait_for(
        state="visible",
        timeout=30_000,
    )


def click_save_parameter_set_as(page) -> None:
    btn = page.locator("#inp\\:submit_blk_displaySaveDefaults_btn").first
    btn.wait_for(state="visible", timeout=60_000)

    for _ in range(1, 6):
        btn.scroll_into_view_if_needed()
        page.wait_for_timeout(150)

        aria = (btn.get_attribute("aria-checked") or "").lower()
        if aria == "true":
            print("Save Parameter Set as already checked.")
            return

        btn.click(force=True, timeout=5_000)
        page.wait_for_timeout(250)

        aria = (btn.get_attribute("aria-checked") or "").lower()
        if aria == "true":
            print("Checked 'Save Parameter Set as'.")
            return

    raise RuntimeError("Could not check 'Save Parameter Set as' after retries.")


def click_save(page) -> None:
    save_btn = page.locator("a[data-action='SAVE']").first
    save_btn.wait_for(state="visible", timeout=30_000)
    save_btn.scroll_into_view_if_needed()
    save_btn.click(force=True, timeout=10_000)

    page.wait_for_timeout(2_000)
    print("Clicked Save.")


def open_related_menu(page) -> None:
    related_toggle = page.locator("#related-toggle a[aria-label='Related']").first

    try:
        related_toggle.wait_for(state="visible", timeout=20_000)
        related_toggle.click(force=True, timeout=5_000)
        page.wait_for_timeout(400)
    except Exception:
        pass

    if page.locator("#menu-related").count() == 0 or not page.locator("#menu-related").first.is_visible():
        page.keyboard.down("Alt")
        page.keyboard.down("Shift")
        page.keyboard.press("R")
        page.keyboard.up("Shift")
        page.keyboard.up("Alt")
        page.wait_for_timeout(600)

    page.locator("#menu-related").first.wait_for(state="visible", timeout=10_000)
    print("Opened Related menu.")


def click_review_output(page) -> None:
    menu = page.locator("#menu-related").first
    menu.wait_for(state="visible", timeout=10_000)

    candidates = [
        menu.locator("a", has_text="Review Output"),
        menu.locator("a", has_text="GJIREVO"),
        menu.get_by_role("menuitem", name="Review Output"),
    ]

    for loc in candidates:
        try:
            if loc.count():
                loc.first.scroll_into_view_if_needed()
                loc.first.click(force=True, timeout=5_000)
                print("Clicked Review Output.")
                page.wait_for_timeout(800)
                return
        except Exception:
            pass

    raise RuntimeError("Could not find Review Output / GJIREVO under Related menu.")


def wait_for_output_processing(page, seconds: int = 30) -> None:
    print(f"Waiting {seconds}s for Banner output to generate...")
    page.wait_for_timeout(seconds * 1000)


def open_filename_lov(page) -> None:
    lov_btn = page.locator("#KEY_BLOCK_CANVAS_keyblckFileNameLbt").first
    lov_btn.wait_for(state="visible", timeout=60_000)
    lov_btn.scroll_into_view_if_needed()
    lov_btn.click(force=True, timeout=10_000)
    print("Opened File Name LOV.")


def select_most_recent_lis(page) -> str:
    page.wait_for_timeout(700)

    lis_candidate = page.locator("text=.lis").first

    try:
        lis_candidate.wait_for(state="visible", timeout=30_000)
    except PWTimeoutError:
        raise RuntimeError("LOV opened, but no .lis entry was found.")

    lis_candidate.click(force=True, timeout=10_000)
    page.wait_for_timeout(500)

    for btn_name in ("OK", "Select"):
        btn = page.get_by_role("button", name=btn_name)
        if btn.count():
            try:
                btn.first.click(timeout=3_000)
                page.wait_for_timeout(500)
                break
            except Exception:
                pass

    selected_text = (lis_candidate.inner_text() or "").strip()
    print(f"Selected LIS file: {selected_text}")
    return selected_text


def open_tools_menu(page) -> None:
    for _ in range(3):
        try:
            page.get_by_role("link", name="Tools").click(timeout=5_000)
            page.wait_for_timeout(300)
            print("Opened Tools menu.")
            return
        except Exception:
            try:
                page.locator("a[title='Tools']").first.click(timeout=5_000)
                page.wait_for_timeout(300)
                print("Opened Tools menu.")
                return
            except Exception:
                page.wait_for_timeout(400)

    raise RuntimeError("Could not open Tools menu.")


def click_yes_on_show_file_prompt(page) -> None:
    page.wait_for_timeout(400)

    yes_btn = page.get_by_role("button", name="Yes")
    if yes_btn.count():
        yes_btn.first.click(timeout=10_000)
        page.wait_for_timeout(500)
        print("Clicked Yes on Show File prompt.")
        return

    try:
        page.locator("button:has-text('Yes'), input[type='button'][value='Yes']").first.click(timeout=10_000)
        page.wait_for_timeout(500)
        print("Clicked Yes on Show File prompt.")
        return
    except Exception:
        pass

    print("No Show File confirmation prompt detected.")


def wait_for_raw_output(doc_page, timeout_ms: int = 30_000) -> None:
    doc_page.wait_for_function(
        f"""() => {{
            const t = (document.body && document.body.textContent) ? document.body.textContent : "";
            return t.includes({EXPECTED_HEADER_PREFIX!r}) || t.trimStart().startsWith("\\f");
        }}""",
        timeout=timeout_ms,
    )


def click_show_document(page, context):
    show_doc = page.locator("a[data-action='SAVE_AND_PRINT']").first
    show_doc.wait_for(state="visible", timeout=20_000)

    try:
        with context.expect_page(timeout=12_000) as pinfo:
            try:
                show_doc.click(force=True, timeout=15_000)
            except Exception:
                show_doc.dispatch_event("click")

            click_yes_on_show_file_prompt(page)

        doc_page = pinfo.value
        doc_page.wait_for_load_state("domcontentloaded", timeout=30_000)
        doc_page.bring_to_front()
        print("Document opened in a new tab.")
    except Exception:
        print("Document opened in the same tab.")
        doc_page = page

    wait_for_raw_output(doc_page, timeout_ms=30_000)

    return doc_page


def _looks_like_banner_ui(text: str) -> bool:
    return any(marker in text for marker in BANNER_UI_GARBAGE_MARKERS)


def _looks_like_real_cfl(text: str) -> bool:
    if not text:
        return False

    t = text.lstrip()

    return (
        EXPECTED_HEADER_PREFIX in t
        or t.startswith("FRCC,")
        or t.startswith("\f")
    )


def save_displayed_document_as_csv(doc_page, out_path: Path) -> None:
    ensure_dir(out_path.parent)

    doc_page.wait_for_load_state("domcontentloaded")
    doc_page.wait_for_timeout(250)

    try:
        text = doc_page.evaluate("() => document.body ? document.body.textContent : ''") or ""
    except Exception:
        text = ""

    text = text.replace("\r\n", "\n")

    if _looks_like_banner_ui(text) or not _looks_like_real_cfl(text):
        snippet = text[:500].replace("\n", "\\n")
        raise RuntimeError(
            f"Show Document did not contain raw CFL output. Refusing to write. "
            f"First 500 chars: {snippet}"
        )

    out_path.write_text(text, encoding="utf-8", errors="replace")
    print(f"Saved document to: {out_path}")


def run_tzrcrsf(
    page,
    context,
    *,
    rate_table_dir: Path,
    vpdi: str = "FRCC",
) -> Path:
    login_if_needed(page)
    open_tzrcrsf(page)
    set_process_and_go(page)
    wait_for_gjapctl_params(page)

    term_code = compute_term_code()
    run_stamp = stamp_yyyymmdd()

    print("Computed TERM CODE:", term_code)

    set_gjapctl_params(page, term_code, vpdi=vpdi)
    next_section(page)
    wait_for_submit_block(page)
    click_save_parameter_set_as(page)
    click_save(page)

    open_related_menu(page)
    click_review_output(page)

    wait_for_output_processing(page, seconds=35)

    open_filename_lov(page)
    select_most_recent_lis(page)

    open_tools_menu(page)

    doc_page = click_show_document(page, context)

    wait_for_output_processing(doc_page, seconds=30)

    output_dir = rate_table_dir / term_code / run_stamp
    output_file = output_dir / f"gokoutp_{run_stamp}.csv"

    save_displayed_document_as_csv(doc_page, output_file)

    print(f"OUTPUT_FILE={output_file}")
    print("TZRCRSF workflow completed.")

    return output_file