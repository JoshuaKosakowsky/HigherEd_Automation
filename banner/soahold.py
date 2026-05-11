from __future__ import annotations

from playwright.sync_api import Page

from banner.actions import banner_save, set_input_value
from banner.modes import RunMode
from banner.navigation import (
    click_insert,
    click_keyblock_go,
    click_no_on_save_warning,
    close_banner_notification,
    open_form,
    start_over,
    wait_for_save_success,
)
from data_processing.shared.logging import log


LOG_PREFIX = "SOAHOLD"
FORM = "SOAHOLD"

def open_form_soahold(page: Page) -> None:
    open_form(page, FORM, wait_selector="[id='inp:key_block_id']")
    log("SOAHOLD key block field detected.", prefix=LOG_PREFIX)


def set_keyblock_id(page: Page, sid: str) -> None:
    set_input_value(
        page=page,
        selector="[id='inp:key_block_id']",
        value=sid,
        label="SOAHOLD ID",
    )


def get_insert_row_number(page: Page) -> str:
    inp = page.locator("#grdSprhold .slick-row.active input[type='text']").first
    inp.wait_for(state="visible", timeout=30_000)

    row_num = inp.get_attribute("row")
    if not row_num:
        raise RuntimeError("Could not determine inserted row number from Hold Type input.")

    log(f"Inserted row number detected: {row_num}", prefix=LOG_PREFIX)
    return row_num


def set_hold_type(page: Page, row_num: str, hold_type: str) -> None:
    hold_type = "" if hold_type is None else str(hold_type).strip()

    inp = page.locator(f"#grdSprhold input[type='text'][row='{row_num}']").first
    inp.wait_for(state="visible", timeout=30_000)
    inp.click(force=True)
    page.wait_for_timeout(150)

    try:
        inp.fill("")
    except Exception:
        pass

    if hold_type:
        inp.press_sequentially(hold_type, delay=80)

    page.keyboard.press("Tab")
    page.wait_for_timeout(600)

    log(f"Entered Hold Type: {hold_type}", prefix=LOG_PREFIX)


def fill_active_editor_input(page: Page, row_num: str, value: str, label: str) -> None:
    value = "" if value is None else str(value).strip()

    editor = page.locator(f"#grdSprhold input.editor-text[row='{row_num}']").first
    editor.wait_for(state="visible", timeout=30_000)
    editor.click(force=True)
    page.wait_for_timeout(150)

    try:
        editor.fill("")
    except Exception:
        page.keyboard.press("Control+A")
        page.keyboard.press("Backspace")

    if value:
        editor.press_sequentially(value, delay=80)

    page.keyboard.press("Tab")
    page.wait_for_timeout(500)

    log(f"{label} set OK: {value}", prefix=LOG_PREFIX)


def fill_origination_code_input(page: Page, row_num: str, value: str) -> None:
    value = "" if value is None else str(value).strip()

    cell_sel = f"#grdSprhold_col8_{row_num}_row"
    input_sel = f"{cell_sel} input[row='{row_num}']"

    cell = page.locator(cell_sel).first
    cell.wait_for(state="visible", timeout=30_000)
    cell.click(force=True)
    page.wait_for_timeout(200)

    lov_input = page.locator(input_sel).first
    lov_input.wait_for(state="visible", timeout=10_000)
    lov_input.click(force=True)
    page.wait_for_timeout(150)

    try:
        lov_input.fill("")
    except Exception:
        page.keyboard.press("Control+A")
        page.keyboard.press("Backspace")

    if value:
        lov_input.press_sequentially(value, delay=80)

    page.keyboard.press("Tab")
    page.wait_for_timeout(600)

    log(f"Origination Code set OK: {value}", prefix=LOG_PREFIX)


def enter_hold_details(
    page: Page,
    hold_type: str,
    reason: str,
    amount: str,
    orig_code: str,
) -> None:
    row_num = get_insert_row_number(page)

    set_hold_type(page, row_num, hold_type)
    fill_active_editor_input(page, row_num, reason, "Reason")
    fill_active_editor_input(page, row_num, amount, "Amount")
    fill_origination_code_input(page, row_num, orig_code)

    log("Completed hold detail entry.", prefix=LOG_PREFIX)


def finalize_student_entry(page: Page, *, mode: RunMode) -> None:
    if mode == RunMode.TEST:
        log("TEST MODE: discarding changes via Start Over -> No.", prefix=LOG_PREFIX)
        start_over(page)
        click_no_on_save_warning(page)
        return

    banner_save(page, mode=mode)
    wait_for_save_success(page)
    close_banner_notification(page)
    start_over(page)


def apply_hold_to_student(
    page: Page,
    *,
    sid: str,
    hold_type: str,
    reason: str,
    amount: str,
    orig_code: str,
    mode: RunMode,
) -> None:
    set_keyblock_id(page, sid)
    click_keyblock_go(page)
    click_insert(page)

    enter_hold_details(
        page=page,
        hold_type=hold_type,
        reason=reason,
        amount=amount,
        orig_code=orig_code,
    )

    finalize_student_entry(page, mode=mode)