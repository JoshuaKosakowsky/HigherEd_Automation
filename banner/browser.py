# Setup browser to use and profile/session

from pathlib import Path
from playwright.sync_api import sync_playwright

from banner.config import BANNER_URL, get_banner_profile


def ensure_dir(path: Path) -> None:
    path.mkdir(parents=True, exist_ok=True)


def cleanup_profile_locks(profile_dir: Path) -> None:
    for name in ("SingletonLock", "SingletonCookie", "SingletonSocket"):
        lock_file = profile_dir / name
        if lock_file.exists():
            lock_file.unlink()


def launch_banner_context(
    playwright,
    browser: str = "edge",
    *,
    headless: bool = False,
    accept_downloads: bool = True,
    downloads_path: Path | None = None,
):
    profile = get_banner_profile(browser)
    ensure_dir(profile.profile_dir)

    return playwright.chromium.launch_persistent_context(
        user_data_dir=str(profile.profile_dir),
        channel=profile.channel,
        headless=headless,
        accept_downloads=accept_downloads,
        downloads_path=str(downloads_path) if downloads_path else None,
        viewport={"width": 1600, "height": 720},
    )