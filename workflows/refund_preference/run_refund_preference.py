from __future__ import annotations

from datetime import datetime
from pathlib import Path

import pandas as pd
from playwright.sync_api import sync_playwright

from bankmobile.config import get_bankmobile_profile
from bankmobile.login import login_if_needed
from bankmobile.refund_preference import (
    goto_card_search,
    log,
    lookup_refund_preference_for_sid,
    normalize_sid,
)
from data_processing.shared.files import ensure_dir


PROJECT_ROOT = Path(__file__).resolve().parents[3]

INPUT_EXCEL = (
    Path.home()
    / "OneDrive - Colorado Community College System"
    / "Refunds"
    / "Auto and Manual Refunds"
    / "Reversals- DO NOT REFUND PA.xlsx"
)

OUTPUT_DIR = (
    Path.home()
    / "OneDrive - Colorado Community College System"
    / "Accounts Receivable-Refund Control - Documents"
    / "BM Files"
    / "Refund-Preference"
)


def load_sids_from_excel(path: Path) -> list[dict]:
    if not path.exists():
        raise FileNotFoundError(f"Input Excel not found: {path}")

    try:
        df = pd.read_excel(path, sheet_name="DNR List")
    except ValueError as e:
        raise ValueError(f"Worksheet 'DNR List' not found in {path}.") from e

    required = {"SID", "Name"}
    missing = required - set(df.columns)

    if missing:
        raise ValueError(f"Input Excel missing required columns: {sorted(missing)}")

    rows = []

    for _, row in df.iterrows():
        sid = normalize_sid(row["SID"])
        name = str(row["Name"]).strip() if pd.notna(row["Name"]) else None

        if sid:
            rows.append(
                {
                    "SID": sid,
                    "DNR_Name": name,
                }
            )

    seen = set()
    deduped = []

    for row in rows:
        if row["SID"] not in seen:
            seen.add(row["SID"])
            deduped.append(row)

    return deduped


def main() -> int:
    ensure_dir(OUTPUT_DIR)

    profile = get_bankmobile_profile("chrome")
    ensure_dir(profile.profile_dir)

    records = load_sids_from_excel(INPUT_EXCEL)

    if not records:
        log("No valid SIDs found. Exiting.")
        return 0

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    output_file = OUTPUT_DIR / f"RefundPreference_{timestamp}.xlsx"

    log(f"Loaded {len(records)} SIDs.")
    log(f"Output file: {output_file}")

    results = []

    with sync_playwright() as p:
        context = p.chromium.launch_persistent_context(
            user_data_dir=str(profile.profile_dir),
            channel=profile.channel,
            headless=False,
            accept_downloads=True,
        )

        try:
            page = context.new_page()

            login_if_needed(page)
            goto_card_search(page)

            for idx, record in enumerate(records, start=1):
                sid = record["SID"]
                dnr_name = record["DNR_Name"]

                log(f"[{idx}/{len(records)}] Looking up SID: {sid}")

                try:
                    result = lookup_refund_preference_for_sid(page, sid)
                except Exception as e:
                    result = {
                        "Status": "ERROR",
                        "BM_Name": None,
                        "RefundPreference": None,
                        "ElapsedSec": None,
                        "Error": repr(e),
                    }

                results.append(
                    {
                        "SID": sid,
                        "DNR_Name": dnr_name,
                        "BM_Name": result.get("BM_Name"),
                        "RefundPreference": result.get("RefundPreference"),
                        "Status": result.get("Status"),
                        "ElapsedSec": result.get("ElapsedSec"),
                        "Error": result.get("Error"),
                    }
                )

                page.wait_for_timeout(350)

        finally:
            context.close()

    pd.DataFrame(results).to_excel(output_file, index=False)

    log(f"Wrote output: {output_file}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())