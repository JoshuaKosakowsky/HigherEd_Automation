from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


LOGIN_URL = "https://www.bankmobileadminsupport.com/adminsite/login/finish.do"
CARD_SEARCH_URL = "https://www.bankmobileadminsupport.com/cardmanagement/initSearch"
TANDR_URL = "https://www.bankmobileadminsupport.com/refund/admin/tandr/start.do"


@dataclass(frozen=True)
class BankMobileProfile:
    channel: str
    profile_dir: Path


def get_bankmobile_profile(browser: str = "chrome") -> BankMobileProfile:
    browser = browser.lower().strip()

    profile_root = (
        Path.home()
        / "AppData"
        / "Local"
        / "Playwright_Profiles"
    )

    if browser == "chrome":
        return BankMobileProfile(
            channel="chrome",
            profile_dir=profile_root / "BankMobile_Chrome",
        )

    if browser == "edge":
        return BankMobileProfile(
            channel="msedge",
            profile_dir=profile_root / "BankMobile_Edge",
        )

    raise ValueError("browser must be either 'chrome' or 'edge'")