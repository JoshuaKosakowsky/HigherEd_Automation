from __future__ import annotations

import json
import os
from time import monotonic
from urllib.parse import parse_qs, urlsplit

from mymines.credentials import MyMinesCredential, MyMinesCredentialStore
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
    experience_url: str | None = None,
    use_saved_mines_login: bool = False,
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
        experience_url=experience_url,
        saved_login=(MyMinesCredentialStore().load() if use_saved_mines_login else None),
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
    experience_url: str | None = None,
    saved_login: MyMinesCredential | None = None,
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
            submitted_username = False
            submitted_password = False
            opened_experience = False
            opened_reporting = False
            launched_insights = False
            try:
                stage = "loading the configured sign-in starting page"
                print("Opening the configured sign-in page. Complete any "
                      "remaining sign-in or MFA prompts in this browser window.",
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
                    for active_page in context.pages:
                        if captured:
                            break
                        if (
                            experience_url and not opened_experience
                            and _is_mines_dashboard(active_page)
                        ):
                            stage = "opening the selected Experience environment"
                            opened_experience = True
                            try:
                                active_page.goto(
                                    experience_url, wait_until="domcontentloaded",
                                    timeout=min(60_000, max(1, int((deadline - monotonic()) * 1000))),
                                )
                            except PlaywrightError:
                                print("Experience did not open automatically. Continue in the browser.", flush=True)
                            else:
                                print("MyMines sign-in complete. Opening the selected Experience environment.", flush=True)
                        if captured:
                            break
                        elif (
                            saved_login is not None and not opened_experience
                            and not submitted_username
                        ):
                            try:
                                submitted_username = _submit_mines_username(active_page, saved_login)
                            except PlaywrightError:
                                saved_login = None
                                print("Finish MyMines sign-in manually in the browser.", flush=True)
                        if (
                            saved_login is not None and not submitted_password
                            and not opened_experience
                        ):
                            try:
                                submitted_password = _submit_mines_password(
                                    active_page, saved_login,
                                    username_confirmed=submitted_username,
                                )
                            except PlaywrightError:
                                saved_login = None
                                print("Finish MyMines sign-in manually in the browser.", flush=True)
                        if (
                            opened_experience and not opened_reporting
                            and _is_experience_page(active_page, experience_url)
                        ):
                            reporting = active_page.get_by_role("tab", name="Reporting", exact=True)
                            if reporting.count() == 1 and reporting.is_visible():
                                opened_reporting = True
                                try:
                                    reporting.click(timeout=10_000)
                                except PlaywrightError:
                                    print("Select Reporting manually in Experience.", flush=True)
                        if (
                            opened_reporting and not launched_insights
                            and _is_experience_page(active_page, experience_url)
                        ):
                            launch = active_page.get_by_role("button", name="LAUNCH REPORTS", exact=True)
                            if launch.count() == 1 and launch.is_visible():
                                launched_insights = True
                                try:
                                    launch.click(timeout=10_000)
                                except PlaywrightError:
                                    print("Launch Insights manually in Experience.", flush=True)
                                else:
                                    stage = "waiting for the Insights SSO handoff"
                                    print("Launching Insights reporting.", flush=True)
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


def _is_mines_page(page) -> bool:
    try:
        url = urlsplit(page.url)
        return url.scheme == "https" and url.hostname == "my.mines.edu"
    except ValueError:
        return False


def _is_mines_dashboard(page) -> bool:
    return (
        _is_mines_page(page)
        and urlsplit(page.url).path.startswith("/app/UserHome")
        and page.get_by_role("link", name="My Apps", exact=True).is_visible()
    )


def _is_experience_page(page, experience_url: str) -> bool:
    try:
        actual = urlsplit(page.url)
        expected = urlsplit(experience_url)
        return (
            actual.scheme == expected.scheme == "https"
            and actual.hostname == expected.hostname
            and (actual.port or 443) == (expected.port or 443)
            and (
                actual.path.startswith(expected.path.rstrip("/") + "/")
                or actual.path.rstrip("/") == expected.path.rstrip("/")
            )
        )
    except ValueError:
        return False


def _submit_mines_username(page, credential: MyMinesCredential) -> bool:
    if not _is_mines_page(page):
        return False
    identifier = page.locator('input[name="identifier"]')
    next_button = page.get_by_role("button", name="Next", exact=True)
    if identifier.count() != 1 or next_button.count() != 1 or not identifier.is_visible():
        return False
    identifier.fill(credential.username)
    next_button.click(timeout=10_000)
    return True


def _submit_mines_password(
    page, credential: MyMinesCredential, *, username_confirmed: bool = False,
) -> bool:
    if not _is_mines_page(page):
        return False
    password = page.locator('input[type="password"]')
    verify = page.get_by_role("button", name="Verify", exact=True)
    prompt = page.get_by_role("heading", name="Verify with your password", exact=True)
    if (
        password.count() != 1 or verify.count() != 1 or prompt.count() != 1
        or not password.is_visible() or not prompt.is_visible()
    ):
        return False
    if not username_confirmed:
        # Okta may remember the username and resume directly at the password
        # step. Only fill in that case when the displayed account matches.
        account = page.get_by_text(credential.username, exact=True)
        if account.count() != 1 or not account.is_visible():
            return False
    password.fill(credential.password)
    verify.click(timeout=10_000)
    return True


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
