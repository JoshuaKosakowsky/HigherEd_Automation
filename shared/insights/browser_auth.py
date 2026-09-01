from __future__ import annotations

import os
from pathlib import Path
from time import monotonic
from urllib.parse import parse_qs, urlsplit

from shared.insights.auth import exchange_sso_jwt
from shared.insights.config import InsightsSettings


class InsightsBrowserAuthenticationError(RuntimeError):
    """Raised when the interactive SSO handoff cannot be completed."""


def login_and_exchange_sso(
    settings: InsightsSettings,
    *,
    browser: str = "edge",
    timeout_seconds: int = 300,
) -> str:
    """Capture the approved SSO handoff and return a Metabase session.

    The browser JWT is matched only on the configured Insights origin and is
    kept in memory just long enough to exchange it. Browser cookies and local
    storage are never read.
    """

    jwt_token = capture_sso_jwt(
        settings.base_url,
        browser=browser,
        timeout_seconds=timeout_seconds,
    )

    try:
        return exchange_sso_jwt(settings.base_url, jwt_token)
    finally:
        jwt_token = ""


def capture_sso_jwt(
    base_url: str,
    *,
    browser: str = "edge",
    timeout_seconds: int = 300,
) -> str:
    browser = browser.strip().lower()

    try:
        channel = {"edge": "msedge", "chrome": "chrome"}[browser]
    except KeyError as error:
        raise ValueError("browser must be 'edge' or 'chrome'") from error

    if timeout_seconds <= 0:
        raise ValueError("timeout_seconds must be positive")

    profile_dir = _insights_profile_dir(browser)
    profile_dir.mkdir(parents=True, exist_ok=True)
    captured: list[str] = []

    try:
        from playwright.sync_api import Error as PlaywrightError
        from playwright.sync_api import sync_playwright
    except ImportError:
        raise InsightsBrowserAuthenticationError(
            "Playwright is not installed in the active Python environment. "
            "Run setup.ps1 before using browser SSO."
        ) from None

    try:
        with sync_playwright() as playwright:
            context = playwright.chromium.launch_persistent_context(
                user_data_dir=str(profile_dir),
                channel=channel,
                headless=False,
                accept_downloads=False,
            )

            def capture_route(route: object, request: object) -> None:
                request_url = getattr(request, "url", "")
                token = _extract_sso_jwt(request_url, base_url)

                if token and not captured:
                    captured.append(token)
                    getattr(route, "abort")()
                    return

                getattr(route, "continue_")()

            context.route("**/*", capture_route)
            page = context.new_page()
            deadline = monotonic() + timeout_seconds

            page.goto(
                f"{base_url.rstrip('/')}/auth/login",
                wait_until="domcontentloaded",
                timeout=min(timeout_seconds * 1000, 60_000),
            )

            sso_link = page.get_by_text("Sign in with SSO", exact=True)
            sso_link.wait_for(state="visible", timeout=30_000)

            try:
                sso_link.click(timeout=30_000)
            except PlaywrightError:
                if not captured:
                    raise

            while not captured and monotonic() < deadline:
                page.wait_for_timeout(250)

            context.close()
    except PlaywrightError:
        raise InsightsBrowserAuthenticationError(
            "The Insights SSO browser handoff did not complete. No SSO JWT "
            "was cached by the automation."
        ) from None

    if not captured:
        raise InsightsBrowserAuthenticationError(
            "Timed out waiting for the Insights SSO handoff."
        )

    return captured[0]


def _extract_sso_jwt(request_url: str, base_url: str) -> str | None:
    request = urlsplit(request_url)
    configured = urlsplit(base_url)

    if (
        request.scheme != configured.scheme
        or request.netloc != configured.netloc
        or request.path.rstrip("/") != "/auth/sso"
    ):
        return None

    values = parse_qs(request.query).get("jwt", [])

    if len(values) != 1:
        return None

    token = values[0].strip()
    return token or None


def _insights_profile_dir(browser: str) -> Path:
    local_app_data = os.getenv("LOCALAPPDATA", "").strip()

    if local_app_data:
        root = Path(local_app_data)
    else:
        root = Path.home() / ".highered_automation"

    return root / "Playwright_Profiles" / f"Insights_{browser.title()}"
