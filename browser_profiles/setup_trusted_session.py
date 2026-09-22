from __future__ import annotations

import argparse
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Protocol

from playwright.sync_api import TimeoutError as PlaywrightTimeoutError
from playwright.sync_api import sync_playwright

from banner.config import BANNER_URL, get_banner_profile
from mymines.config import MINES_URL, get_mines_profile


NAV_TIMEOUT_MS = 180_000
SESSION_TIMEOUT_SECONDS = 300


class BrowserProfile(Protocol):
    channel: str
    profile_dir: Path


@dataclass(frozen=True)
class TrustedSessionSystem:
    login_url: str
    profile_factory: Callable[[str], BrowserProfile]


# Add new trusted-session websites here. Profile factories must delegate to the
# shared resolver so all automation using one browser channel shares one profile.
TRUSTED_SESSION_SYSTEMS: dict[str, TrustedSessionSystem] = {
    "Mines": TrustedSessionSystem(
        login_url=MINES_URL,
        profile_factory=get_mines_profile,
    ),
    "Banner": TrustedSessionSystem(
        login_url=BANNER_URL,
        profile_factory=get_banner_profile,
    ),
}


@dataclass(frozen=True)
class TrustedSessionConfig:
    system_name: str
    login_url: str
    browser_profile: BrowserProfile


def get_trusted_session_config(
    system_name: str,
    browser: str,
) -> TrustedSessionConfig:
    system_name = system_name.strip()

    try:
        system = TRUSTED_SESSION_SYSTEMS[system_name]
    except KeyError as error:
        supported_systems = ", ".join(TRUSTED_SESSION_SYSTEMS)
        raise ValueError(
            f"Unsupported system: {system_name}. "
            f"Supported systems: {supported_systems}."
        ) from error

    return TrustedSessionConfig(
        system_name=system_name,
        login_url=system.login_url,
        browser_profile=system.profile_factory(browser),
    )


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Open a Playwright browser profile so the user can "
            "complete login/2FA."
        )
    )

    parser.add_argument(
        "--system",
        required=True,
        choices=tuple(TRUSTED_SESSION_SYSTEMS),
        help="System to log into.",
    )

    parser.add_argument(
        "--browser",
        default="chrome",
        choices=["edge", "chrome"],
        help="Browser profile to use.",
    )

    return parser.parse_args()


def main() -> int:
    args = parse_args()

    try:
        config = get_trusted_session_config(args.system, args.browser)
    except ValueError as error:
        print(error)
        return 1

    print(f"SYSTEM:      {config.system_name}")
    print(f"BROWSER:     {args.browser}")
    print(f"CHANNEL:     {config.browser_profile.channel}")
    print(f"PROFILE DIR: {config.browser_profile.profile_dir}")
    print(f"LOGIN URL:   {config.login_url}")
    print()

    done = threading.Event()

    def wait_for_enter() -> None:
        try:
            input(
                "When fully logged in, press Enter to close and "
                "save the session..."
            )
        except EOFError:
            pass
        done.set()

    threading.Thread(target=wait_for_enter, daemon=True).start()

    with sync_playwright() as p:
        context = p.chromium.launch_persistent_context(
            user_data_dir=str(config.browser_profile.profile_dir),
            channel=config.browser_profile.channel,
            headless=False,
            accept_downloads=True,
        )

        context.set_default_navigation_timeout(NAV_TIMEOUT_MS)
        context.set_default_timeout(NAV_TIMEOUT_MS)

        page = context.new_page()

        print("Opening login page...")

        try:
            page.goto(config.login_url, wait_until="commit")
        except PlaywrightTimeoutError:
            print("Initial navigation timed out. Trying fallback load...")

            try:
                page.goto(config.login_url, wait_until="load")
            except PlaywrightTimeoutError:
                print("Navigation failed.")
                print(f"Current URL: {page.url}")
                context.close()
                return 1

        print()
        print("Log in manually and complete 2FA.")
        print("Select 'remember this device' if prompted.")
        timeout_minutes = SESSION_TIMEOUT_SECONDS // 60
        print(
            "This window will auto-close after "
            f"{timeout_minutes} minutes."
        )
        print()

        start = time.time()

        while not done.is_set():
            if time.time() - start >= SESSION_TIMEOUT_SECONDS:
                print("Timeout reached. Closing browser.")
                break

            time.sleep(1)

        context.close()

    print()
    print(f"Saved trusted session for {config.system_name}:")
    print(config.browser_profile.profile_dir)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
