from dataclasses import dataclass
from pathlib import Path


BANNER_URL = "https://banner.cccs.edu/applicationNavigator/seamless"


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