"""Tests for the machine-local browser profile shared by Playwright callers."""

from __future__ import annotations

import unittest
from pathlib import Path
from unittest.mock import patch

from banner.config import get_banner_profile
from mymines.config import get_mines_profile
from shared.browser_profile import get_automation_browser_profile


class AutomationBrowserProfileTests(unittest.TestCase):
    def test_chrome_is_the_default_browser_channel(self) -> None:
        profile = get_automation_browser_profile(
            environment={}, platform="win32", home=Path("C:/Users/Example")
        )
        self.assertEqual(profile.channel, "chrome")
        self.assertEqual(profile.profile_dir.name, "Shared_Chrome")

    def test_windows_profile_uses_local_app_data(self) -> None:
        profile = get_automation_browser_profile(
            "edge",
            environment={"LOCALAPPDATA": r"C:\Users\Example\AppData\Local"},
            platform="win32",
            home=Path("/unused"),
        )
        self.assertEqual(profile.channel, "msedge")
        self.assertEqual(
            profile.profile_dir,
            Path(r"C:\Users\Example\AppData\Local")
            / "HigherEdAutomation" / "Playwright" / "Shared_Edge",
        )

    def test_macos_profile_is_outside_the_repository(self) -> None:
        profile = get_automation_browser_profile(
            "chrome", environment={}, platform="darwin", home=Path("/Users/example")
        )
        self.assertEqual(profile.channel, "chrome")
        self.assertEqual(
            profile.profile_dir,
            Path("/Users/example/Library/Application Support/")
            / "HigherEdAutomation" / "Playwright" / "Shared_Chrome",
        )

    def test_banner_and_mymines_resolve_the_same_channel_profile(self) -> None:
        expected = get_automation_browser_profile(
            "edge", environment={}, platform="win32", home=Path("C:/Users/Example")
        )
        with patch(
            "banner.config.get_automation_browser_profile", return_value=expected
        ), patch(
            "mymines.config.get_automation_browser_profile", return_value=expected
        ):
            self.assertEqual(get_banner_profile("edge"), expected)
            self.assertEqual(get_mines_profile("edge"), expected)

    def test_browser_channels_use_separate_profiles(self) -> None:
        arguments = {"environment": {}, "platform": "darwin", "home": Path("/Users/example")}
        edge = get_automation_browser_profile("edge", **arguments)
        chrome = get_automation_browser_profile("chrome", **arguments)
        self.assertNotEqual(edge.profile_dir, chrome.profile_dir)

    def test_rejects_unknown_browser(self) -> None:
        with self.assertRaisesRegex(ValueError, "edge.*chrome"):
            get_automation_browser_profile("firefox")
