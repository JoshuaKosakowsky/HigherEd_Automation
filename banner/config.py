from dataclasses import dataclass
from pathlib import Path

BANNER_URL = "https://appnav-prod.mines.elluciancloud.com:8101/applicationNavigator"
BANNER_ADMIN_URL = "https://banneradmin-prod.mines.elluciancloud.com:8104/BannerAdmin/?form="

@dataclass(frozen=True)
class BrowserProfile:
    channel: str
    profile_dir: Path


def get_banner_profile(browser: str = "edge") -> BrowserProfile:
    browser = browser.lower().strip()

    if browser == "edge":
        return BrowserProfile(
            channel="msedge",
            profile_dir=Path.home()
            / "AppData"
            / "Local"
            / "Playwright_Profiles"
            / "Banner_Edge",
        )

    if browser == "chrome":
        return BrowserProfile(
            channel="chrome",
            profile_dir=Path.home()
            / "AppData"
            / "Local"
            / "Playwright_Profiles"
            / "Banner_Chrome",
        )

    raise ValueError("browser must be 'edge' or 'chrome'")