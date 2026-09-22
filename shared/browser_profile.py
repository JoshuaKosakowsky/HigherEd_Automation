"""One local persistent browser profile for repository Playwright automation."""

from __future__ import annotations

import os
import sys
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class AutomationBrowserProfile:
    channel: str
    profile_dir: Path


def get_automation_browser_profile(
    browser: str = "chrome",
    *,
    environment: Mapping[str, str] | None = None,
    platform: str | None = None,
    home: Path | None = None,
) -> AutomationBrowserProfile:
    """Return the per-user, machine-local profile for a browser channel.

    TEST, PROD, Banner, MyMines, and future callers of this shared resolver use
    the same profile when they use the same browser channel. Edge and Chrome
    remain separate because sharing one Chromium data directory across browser
    products is unsupported and can corrupt the profile.
    """
    browser = browser.strip().lower()
    try:
        channel = {"edge": "msedge", "chrome": "chrome"}[browser]
    except KeyError as error:
        raise ValueError("browser must be 'edge' or 'chrome'") from error

    values = os.environ if environment is None else environment
    current_platform = sys.platform if platform is None else platform
    user_home = Path.home() if home is None else Path(home)

    if current_platform == "win32":
        configured_root = values.get("LOCALAPPDATA", "").strip()
        local_root = (
            Path(configured_root)
            if configured_root
            else user_home / "AppData" / "Local"
        )
    elif current_platform == "darwin":
        local_root = user_home / "Library" / "Application Support"
    else:
        configured_root = values.get("XDG_DATA_HOME", "").strip()
        local_root = (
            Path(configured_root)
            if configured_root
            else user_home / ".local" / "share"
        )

    return AutomationBrowserProfile(
        channel=channel,
        profile_dir=(
            local_root
            / "HigherEdAutomation"
            / "Playwright"
            / f"Shared_{browser.title()}"
        ),
    )
