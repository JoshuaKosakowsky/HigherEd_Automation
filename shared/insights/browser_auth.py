from __future__ import annotations

import json
import os
from time import monotonic
from urllib.parse import parse_qs, urlsplit

from shared.browser_profile import get_automation_browser_profile
from shared.insights.auth import exchange_sso_jwt
from shared.insights.config import InsightsSettings


class InsightsBrowserAuthenticationError(RuntimeError):
    """Raised when the interactive SSO handoff cannot be completed."""


def login_and_exchange_sso(
    settings: InsightsSettings,
    *,
    browser: str = "chrome",
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
        sso_start_url=settings.sso_start_url,
    )

    try:
        return exchange_sso_jwt(settings.base_url, jwt_token)
    finally:
        jwt_token = ""


def capture_sso_jwt(
    base_url: str,
    *,
    browser: str = "chrome",
    timeout_seconds: int = 300,
    sso_start_url: str | None = None,
) -> str:
    browser = browser.strip().lower()

    profile = get_automation_browser_profile(browser)

    if timeout_seconds <= 0:
        raise ValueError("timeout_seconds must be positive")

    if any(os.environ.get(name) for name in ("DEBUG", "PWDEBUG", "SSLKEYLOGFILE")):
        raise InsightsBrowserAuthenticationError(
            "Disable DEBUG, PWDEBUG, and SSLKEYLOGFILE before SSO login; "
            "debug output could expose credentials."
        )

    captured: list[str] = []
    profile.profile_dir.mkdir(parents=True, exist_ok=True)

    try:
        from playwright.sync_api import Error as PlaywrightError
        from playwright.sync_api import TimeoutError as PlaywrightTimeoutError
        from playwright.sync_api import sync_playwright
    except ImportError:
        raise InsightsBrowserAuthenticationError(
            "Playwright is not installed in the active Python environment. "
            "Run setup.ps1 before using browser SSO."
        ) from None

    stage = "opening Chrome/Edge"
    try:
        with sync_playwright() as playwright:
            context = playwright.chromium.launch_persistent_context(
                user_data_dir=str(profile.profile_dir),
                channel=profile.channel,
                headless=False,
                args=["--window-position=40,40", "--window-size=1200,850"],
                env={k: v for k, v in os.environ.items()
                     if k not in {"DEBUG", "PWDEBUG", "SSLKEYLOGFILE"}},
                accept_downloads=False,
                service_workers="block",
            )

            def capture_request(request) -> None:
                # Request events include redirect hops that route handlers miss.
                # Inspect a POST body only after its destination is verified.
                if not _is_sso_destination(request.url, base_url):
                    return
                token = _extract_sso_jwt(
                    request.url, base_url,
                    request.post_data if request.method == "POST" else None,
                )

                if token and not captured:
                    captured.append(token)
                    print("SSO handoff captured in memory.", flush=True)

            context.on("request", capture_request)
            page = context.new_page()
            page.bring_to_front()
            deadline = monotonic() + timeout_seconds
            try:
                stage = "loading the configured sign-in starting page"
                print("Opening the configured sign-in page. Complete sign-in "
                      "and MFA, then open Insights in this same browser window.",
                      flush=True)
                page.goto(
                    sso_start_url or f"{base_url.rstrip('/')}/auth/login",
                    wait_until="domcontentloaded",
                    timeout=min(timeout_seconds * 1000, 60_000),
                )
                stage = "waiting for interactive SSO sign-in"
                print("Starting page loaded. Waiting for the Insights SSO handoff.", flush=True)
                # Portal-first tenants need their normal application launch
                # path; do not click a generic SSO control on the portal.
                if not captured and not sso_start_url:
                    try:
                        page.get_by_text("Sign in with SSO", exact=True).click(
                            timeout=10_000,
                        )
                    except PlaywrightTimeoutError:
                        print("Use the browser to open Insights through your "
                              "normal school SSO entry point. Waiting for sign-in...",
                              flush=True)
                while not captured and monotonic() < deadline:
                    if not context.pages:
                        break
                    try:
                        # Listen across tabs/popups even if the portal closes
                        # its original tab while launching Insights.
                        context.wait_for_event("request", timeout=250)
                    except PlaywrightTimeoutError:
                        pass
            finally:
                context.close()
    except PlaywrightError:
        if not captured:
            raise InsightsBrowserAuthenticationError(
                f"The browser stopped while {stage}. No SSO JWT "
                "was cached by the automation. Close any other automation "
                "browser window in case the shared profile is already in use."
            ) from None

    if not captured:
        raise InsightsBrowserAuthenticationError(
            "Timed out waiting for the Insights SSO handoff."
        )

    return captured[0]


def _extract_sso_jwt(
    request_url: str, base_url: str, post_data: str | None = None,
) -> str | None:
    if not _is_sso_destination(request_url, base_url):
        return None
    values = parse_qs(urlsplit(request_url).query).get("jwt", [])
    if post_data:
        try:
            body = json.loads(post_data)
        except ValueError:
            body = None
        if isinstance(body, dict) and "jwt" in body:
            values.append(body["jwt"])
        elif body is None:
            values.extend(parse_qs(post_data).get("jwt", []))
    if len(values) != 1:
        return None
    if not isinstance(values[0], str):
        return None
    token = values[0].strip()
    return token or None


def _is_sso_destination(request_url: str, base_url: str) -> bool:
    try:
        request = urlsplit(request_url)
        configured = urlsplit(base_url)
        return (
            request.scheme == configured.scheme == "https"
            and request.hostname == configured.hostname
            and (request.port or 443) == (configured.port or 443)
            and not request.username and not request.password
            and request.path.rstrip("/") in {
                "/auth/sso", "/auth/sso/to_session",
            }
        )
    except ValueError:
        return False
