# FGIGLAC specific navigation functions

from __future__ import annotations

import csv
import shutil
from datetime import datetime
from pathlib import Path

from openpyxl import Workbook
from playwright.sync_api import Page

from banner.actions import set_input_value
from banner.navigation import open_form

from data_processing.shared.dates import stamp_mmddyy
from data_processing.shared.excel import csv_to_xlsx
from data_processing.shared.files import ensure_dir

FORM = "FGIGLAC"


def destination_for(dest_root: Path, fund: str, acct: str) -> Path:
    mapping = {
        ("001010", "111010"): dest_root / "001010 111010 General Fund",
        ("011010", "113050"): dest_root / "011010 113050 Collections",
        ("011010", "221080"): dest_root / "011010 221080 BankMobile",
        ("011042", "113070"): dest_root / "011042 113070 Cashnet",
        ("011043", "113070"): dest_root / "011043 113070 WC-BCC",
    }

    return mapping.get((fund, acct), dest_root / "Y Batch" / f"{fund} {acct}")


def move_and_rename_as_xlsx(
    source_file: Path,
    destination_folder: Path,
    fund: str,
    acct: str,
) -> Path:
    ensure_dir(destination_folder)

    final_name = f"FGIGLAC_{fund}_{acct}_{stamp_mmddyy()}.xlsx"
    final_path = destination_folder / final_name
    temp_xlsx = source_file.with_suffix(".xlsx")

    if temp_xlsx.exists():
        temp_xlsx.unlink()

    if final_path.exists():
        final_path.unlink()

    csv_to_xlsx(source_file, temp_xlsx)

    try:
        source_file.unlink()
    except Exception:
        pass

    shutil.move(str(temp_xlsx), str(final_path))
    return final_path


def open_fgiglac(page: Page) -> None:
    open_form(
        page,
        FORM,
        wait_selector="id=inp:keyblck_block_keyblckFundCode",
    )

    page.wait_for_selector(
        "id=inp:keyblck_block_keyblckAcctCode",
        timeout=120_000,
    )

    print("FGIGLAC key block fields detected.")


def next_block(page: Page) -> None:
    page.keyboard.down("Alt")
    page.keyboard.press("PageDown")
    page.keyboard.up("Alt")
    page.wait_for_timeout(800)


def open_tools_menu(page: Page) -> None:
    for _ in range(3):
        try:
            page.get_by_role("link", name="Tools").click(timeout=10_000)
            page.wait_for_timeout(300)
            print("Opened Tools menu.")
            return
        except Exception:
            try:
                page.locator("a[title='Tools']").first.click(timeout=10_000)
                page.wait_for_timeout(300)
                print("Opened Tools menu.")
                return
            except Exception:
                page.wait_for_timeout(700)

    raise RuntimeError("Could not open Tools menu.")


def run_fgiglac_one(
    page: Page,
    *,
    fund: str,
    acct: str,
    download_dir: Path,
    dest_root: Path,
) -> Path:
    fund_sel = "id=inp:keyblck_block_keyblckFundCode"
    acct_sel = "id=inp:keyblck_block_keyblckAcctCode"

    keyblock_go_sel = "button[data-member='EXECUTE_BTN'][data-action='NEXT_BLOCK']"
    results_go_sel = "div.legendDown button.primary-button.ui-buttonGo"
    start_over_sel = "button[data-action='CLEAR-FORM']"

    set_input_value(page, fund_sel, fund, "Fund")
    set_input_value(page, acct_sel, acct, "Acct")

    try:
        page.locator(keyblock_go_sel).wait_for(state="visible", timeout=60_000)
        page.locator(keyblock_go_sel).click()
        print("Clicked Keyblock Go.")
    except Exception:
        print("Keyblock Go failed; using Alt+PageDown.")
        next_block(page)

    page.locator(results_go_sel).wait_for(state="visible", timeout=120_000)
    page.locator(results_go_sel).click()
    print("Clicked Results Go.")

    page.wait_for_timeout(2_000)

    open_tools_menu(page)

    export_locator = page.locator("a[title='Export']").first
    export_menuitem = page.get_by_role("menuitem", name="Export")
    continue_btn = page.get_by_role("button", name="Continue").first

    with page.expect_download(timeout=240_000) as download_info:
        try:
            export_locator.click(timeout=10_000)
        except Exception:
            export_menuitem.click(timeout=10_000)

        try:
            continue_btn.wait_for(state="visible", timeout=2_500)
            continue_btn.click(timeout=5_000)
            print("Export warning appeared; clicked Continue.")
        except Exception:
            pass

    download = download_info.value

    ensure_dir(download_dir)

    suggested_name = download.suggested_filename or "FGIGLAC.csv"
    temp_csv = download_dir / suggested_name
    download.save_as(str(temp_csv))

    destination_folder = destination_for(dest_root, fund, acct)

    final_path = move_and_rename_as_xlsx(
        temp_csv,
        destination_folder,
        fund,
        acct,
    )

    print(f"Saved FGIGLAC output: {final_path}")

    try:
        page.locator(start_over_sel).first.click(timeout=30_000)
        page.wait_for_timeout(1_000)
        print("Clicked Start Over.")
    except Exception:
        print("Start Over failed; reopening FGIGLAC.")
        open_fgiglac(page)

    return final_path


def run_fgiglac_batch(
    page: Page,
    *,
    fund_account_pairs: list[tuple[str, str]],
    download_dir: Path,
    dest_root: Path,
) -> list[Path]:
    open_fgiglac(page)

    outputs: list[Path] = []

    for fund, acct in fund_account_pairs:
        try:
            output = run_fgiglac_one(
                page,
                fund=fund,
                acct=acct,
                download_dir=download_dir,
                dest_root=dest_root,
            )
            outputs.append(output)
            print(f"SUCCESS {fund}/{acct}")
        except Exception as e:
            print(f"FAILED {fund}/{acct}: {e}")

    return outputs