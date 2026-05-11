from __future__ import annotations

import os
import time
from pathlib import Path

import pandas as pd
from playwright.sync_api import sync_playwright

from banner.config import BANNER_URL, get_banner_profile
from banner.login import login_if_needed
from banner.modes import RunMode
from banner.soahold import (
    apply_hold_to_student,
    open_form_soahold,
)
from banner.navigation import (
    click_no_on_save_warning,
    close_banner_notification,
    start_over,
)
from data_processing.shared.dates import compute_current_term_code
from data_processing.shared.files import ensure_dir
from data_processing.shared.logging import log


LOG_PREFIX = "SOAHOLD"


PROJECT_ROOT = Path(__file__).resolve().parents[2]
HOLDS_DIR = PROJECT_ROOT / "data" / "holds"

REQUIRED_COLUMNS = {
    "ID",
    "HOLD",
    "REASON",
    "ACADEMIC_PERIOD",
    "AMOUNT",
    "ORIGINATION CODE",
}


def format_eta(seconds: float) -> str:
    seconds = max(0, int(seconds))
    minutes, sec = divmod(seconds, 60)
    hours, minutes = divmod(minutes, 60)

    if hours > 0:
        return f"{hours}h {minutes}m"
    if minutes > 0:
        return f"{minutes}m {sec}s"
    return f"{sec}s"


def parse_run_mode(value: str) -> RunMode:
    value = value.strip().lower()

    if value == "test":
        return RunMode.TEST
    if value == "prod":
        return RunMode.PROD
    if value == "debug":
        return RunMode.DEBUG

    raise ValueError("Mode must be one of: test, prod, debug")


def get_holds_input_file() -> Path:
    term_code = compute_current_term_code()
    return HOLDS_DIR / f"{term_code}_holds.xlsx"


def load_holds_file(path: Path) -> pd.DataFrame:
    if not path.exists():
        raise FileNotFoundError(f"Holds input file not found: {path}")

    df = pd.read_excel(path)
    df.columns = df.columns.str.strip().str.upper()

    missing = REQUIRED_COLUMNS - set(df.columns)
    if missing:
        raise ValueError(f"Missing required columns in Excel: {sorted(missing)}")

    for col in REQUIRED_COLUMNS:
        df[col] = df[col].astype(str).str.strip()

    return df


def recover_soahold_state(page, *, mode: RunMode) -> None:
    try:
        start_over(page)

        if mode == RunMode.TEST:
            try:
                click_no_on_save_warning(page)
            except Exception:
                pass

        return

    except Exception:
        pass

    try:
        close_banner_notification(page)
    except Exception:
        pass

    try:
        open_form_soahold(page)
    except Exception:
        pass


def main() -> int:
    mode = parse_run_mode(os.environ.get("SOAHOLD_RUN_MODE", "test"))
    input_file = get_holds_input_file()
    browser_profile = get_banner_profile("edge")

    ensure_dir(browser_profile.profile_dir)
    ensure_dir(HOLDS_DIR)

    if mode == RunMode.TEST:
        log("TEST MODE ENABLED - HOLDS WILL NOT BE SAVED.", prefix=LOG_PREFIX)
    elif mode == RunMode.DEBUG:
        log("DEBUG MODE ENABLED - HOLDS WILL BE SAVED WITH EXTRA LOGGING.", prefix=LOG_PREFIX)
    else:
        log("PRODUCTION MODE ENABLED - HOLDS WILL BE SAVED.", prefix=LOG_PREFIX)

    log(f"Using holds input file: {input_file}", prefix=LOG_PREFIX)

    df = load_holds_file(input_file)
    total_rows = len(df)

    log(f"Loaded {total_rows} hold records.", prefix=LOG_PREFIX)

    processed = 0
    failed = 0
    run_start = time.perf_counter()

    with sync_playwright() as p:
        context = p.chromium.launch_persistent_context(
            user_data_dir=str(browser_profile.profile_dir),
            channel=browser_profile.channel,
            headless=False,
            viewport={"width": 1600, "height": 720},
            accept_downloads=True,
        )

        page = context.new_page()

        try:
            page.goto(BANNER_URL, wait_until="domcontentloaded")
            log("Opened Banner App Navigator.", prefix=LOG_PREFIX)

            login_if_needed(page)
            open_form_soahold(page)

            for idx, row in df.iterrows():
                sid = str(row["ID"]).strip()
                hold_type = str(row["HOLD"]).strip()
                reason = str(row["REASON"]).strip()
                amount = str(row["AMOUNT"]).strip()
                orig_code = str(row["ORIGINATION CODE"]).strip()

                log(f"Starting row {idx + 1}/{total_rows} for SID {sid}", prefix=LOG_PREFIX)

                try:
                    apply_hold_to_student(
                        page=page,
                        sid=sid,
                        hold_type=hold_type,
                        reason=reason,
                        amount=amount,
                        orig_code=orig_code,
                        mode=mode,
                    )

                    processed += 1

                    if mode == RunMode.TEST:
                        log(
                            f"SUCCESS row {idx + 1}/{total_rows} | SID {sid} | "
                            "TEST MODE discarded changes.", prefix=LOG_PREFIX
                        )
                    else:
                        log(
                            f"SUCCESS row {idx + 1}/{total_rows} | SID {sid} | "
                            "Changes saved.", prefix=LOG_PREFIX
                        )

                except Exception as e:
                    failed += 1
                    log(f"FAILED row {idx + 1}/{total_rows} | SID {sid} | {e}", prefix=LOG_PREFIX)
                    recover_soahold_state(page, mode=mode)

                completed = processed + failed
                elapsed = time.perf_counter() - run_start
                avg_per_row = elapsed / completed if completed else 0
                remaining = total_rows - completed
                eta_seconds = avg_per_row * remaining
                pct = (completed / total_rows * 100) if total_rows else 100

                log(
                    f"Progress: {completed}/{total_rows} ({pct:.1f}%) | "
                    f"Successes: {processed} | Failures: {failed} | "
                    f"ETA: {format_eta(eta_seconds)}", prefix=LOG_PREFIX
                )

                page.wait_for_timeout(400)

            total_elapsed = time.perf_counter() - run_start

            log(
                f"Run complete. Successes: {processed} | Failures: {failed} | "
                f"Total: {total_rows} | Elapsed: {format_eta(total_elapsed)}", prefix=LOG_PREFIX
            )

            return 0 if failed == 0 else 2

        finally:
            context.close()


if __name__ == "__main__":
    raise SystemExit(main())