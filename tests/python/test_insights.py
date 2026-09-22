from __future__ import annotations

import json
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pandas as pd
import requests

from shared.insights.auth import (
    InsightsAuthenticationError,
    exchange_sso_jwt,
)
from shared.insights.client import InsightsAPIError, InsightsClient
from shared.insights.browser_auth import _extract_sso_jwt, capture_sso_jwt
from shared.insights.config import (
    InsightsConfigurationError,
    InsightsSettings,
)
from shared.insights.session_auth import build_authenticated_client, clear_cached_session
from shared.insights.session_cache import (
    CREDENTIAL_USERNAME,
    CachedInsightsSession,
    DailyInsightsSessionCache,
    InsightsCredentialError,
    SystemCredentialStore,
)


def make_response(status_code: int, payload: object) -> requests.Response:
    response = requests.Response()
    response.status_code = status_code
    response.headers["Content-Type"] = "application/json"
    response._content = json.dumps(payload).encode("utf-8")
    return response


class StubSession:
    def __init__(self, *responses: requests.Response) -> None:
        self.responses = list(responses)
        self.requests: list[dict[str, object]] = []

    def request(self, method: str, url: str, **kwargs: object) -> requests.Response:
        self.requests.append({"method": method, "url": url, **kwargs})
        return self.responses.pop(0)


class MemoryCredentialStore:
    def __init__(self) -> None:
        self.values: dict[tuple[str, str], str] = {}

    def get_password(self, service: str, username: str) -> str | None:
        return self.values.get((service, username))

    def set_password(self, service: str, username: str, password: str) -> None:
        self.values[(service, username)] = password

    def delete_password(self, service: str, username: str) -> None:
        self.values.pop((service, username), None)


class FakeInsightsClient:
    created: list[FakeInsightsClient] = []

    def __init__(
        self,
        base_url: str,
        database_id: int,
        *,
        api_key: str | None = None,
        session_token: str | None = None,
    ) -> None:
        self.base_url = base_url
        self.database_id = database_id
        self.api_key = api_key
        self.session_token = session_token
        self.closed = False
        self.logged_out = False
        self.__class__.created.append(self)

    def get_current_user(self) -> object:
        return SimpleNamespace(id=1519)

    def logout(self) -> None:
        self.logged_out = True

    def close(self) -> None:
        self.closed = True


class InsightsSettingsTests(unittest.TestCase):
    def test_portal_start_url_is_environment_specific_and_optional(self) -> None:
        values = {
            "INSIGHTS_ENV": "TEST",
            "INSIGHTS_TEST_BASE_URL": "https://test.example.edu",
            "INSIGHTS_TEST_DATABASE_ID": "2",
            "INSIGHTS_TEST_SSO_START_URL": "https://portal.example.edu/app/UserHome",
            "INSIGHTS_PROD_SSO_START_URL": "https://prod-portal.example.edu",
        }
        settings = InsightsSettings.from_environment(values)
        self.assertEqual(settings.sso_start_url, values["INSIGHTS_TEST_SSO_START_URL"])
        self.assertEqual(settings.base_url, values["INSIGHTS_TEST_BASE_URL"])
        del values["INSIGHTS_TEST_SSO_START_URL"]
        self.assertIsNone(InsightsSettings.from_environment(values).sso_start_url)

    def test_portal_start_rejects_credentials_and_redirect_parameters(self) -> None:
        for url in (
            "http://portal.example.edu", "https://user:secret@portal.example.edu",
            "https://portal.example.edu?jwt=synthetic", "https://portal.example.edu#secret",
            "https:///missing-host", "https://portal.example.edu:invalid",
        ):
            with self.subTest(url=url), self.assertRaises(InsightsConfigurationError):
                InsightsSettings.from_environment({
                    "INSIGHTS_TEST_BASE_URL": "https://test.example.edu",
                    "INSIGHTS_TEST_DATABASE_ID": "2",
                    "INSIGHTS_TEST_SSO_START_URL": url,
                })

    def test_loads_only_the_explicitly_selected_environment(self) -> None:
        settings = InsightsSettings.from_environment(
            {
                "INSIGHTS_ENV": "test",
                "INSIGHTS_TEST_BASE_URL": "https://test.example.edu/",
                "INSIGHTS_TEST_DATABASE_ID": "2",
                "INSIGHTS_TEST_API_KEY": " test-key ",
                "INSIGHTS_PROD_BASE_URL": "https://prod.example.edu",
                "INSIGHTS_PROD_DATABASE_ID": "9",
            }
        )

        self.assertEqual(settings.environment, "TEST")
        self.assertEqual(settings.base_url, "https://test.example.edu")
        self.assertEqual(settings.database_id, 2)
        self.assertEqual(settings.api_key, "test-key")
        self.assertNotIn("test-key", repr(settings))

    def test_rejects_unknown_environment(self) -> None:
        with self.assertRaisesRegex(
            InsightsConfigurationError,
            "either TEST or PROD",
        ):
            InsightsSettings.from_environment({"INSIGHTS_ENV": "staging"})

    def test_rejects_url_credentials(self) -> None:
        with self.assertRaisesRegex(
            InsightsConfigurationError,
            "without credentials",
        ):
            InsightsSettings.from_environment(
                {
                    "INSIGHTS_ENV": "TEST",
                    "INSIGHTS_TEST_BASE_URL": "https://secret@test.example.edu",
                    "INSIGHTS_TEST_DATABASE_ID": "2",
                }
            )


class InsightsAuthenticationTests(unittest.TestCase):
    def test_exchange_rejects_redirect_without_following_it(self) -> None:
        with patch("shared.insights.auth.requests.post", return_value=make_response(302, {})) as post:
            with self.assertRaises(InsightsAuthenticationError):
                exchange_sso_jwt("https://test.example.edu", "synthetic-token")
        self.assertFalse(post.call_args.kwargs["allow_redirects"])

    def test_authentication_error_does_not_include_response_body(self) -> None:
        response = make_response(
            401,
            {"error": "secret JWT or SSO URL should not be repeated"},
        )

        with patch("shared.insights.auth.requests.post", return_value=response):
            with self.assertRaises(InsightsAuthenticationError) as context:
                exchange_sso_jwt("https://test.example.edu", "secret-jwt")

        message = str(context.exception)
        self.assertIn("HTTP 401", message)
        self.assertNotIn("secret JWT", message)
        self.assertNotIn("secret-jwt", message)


class InsightsBrowserAuthenticationTests(unittest.TestCase):
    def test_portal_entry_keeps_capture_scoped_to_insights(self) -> None:
        # Fake the browser dependency: no live credentials or browser required.
        context = MagicMock()
        page = context.new_page.return_value
        context.pages = [page]
        playwright = MagicMock()
        playwright.chromium.launch_persistent_context.return_value = context
        manager = MagicMock()
        manager.__enter__.return_value = playwright
        module = SimpleNamespace(
            sync_playwright=lambda: manager, Error=RuntimeError, TimeoutError=TimeoutError,
        )
        def handoff(*args, **kwargs):
            callback = context.on.call_args.args[1]
            callback(SimpleNamespace(
                url="https://portal.example.edu/auth/sso?jwt=wrong-token", method="GET",
            ))
            callback(SimpleNamespace(
                url="https://test.example.edu/auth/sso?jwt=synthetic", method="GET",
            ))
        # Simulate the handoff from another tab after the starting page loads.
        context.wait_for_event.side_effect = handoff
        with tempfile.TemporaryDirectory() as directory:
            profile = SimpleNamespace(channel="chrome", profile_dir=Path(directory) / "profile")
            with (
                patch.dict("sys.modules", {"playwright.sync_api": module}),
                patch.dict("os.environ", {"DEBUG": "", "PWDEBUG": "", "SSLKEYLOGFILE": ""}),
                patch("shared.insights.browser_auth.get_automation_browser_profile", return_value=profile),
                patch("builtins.print"),
            ):
                token = capture_sso_jwt(
                    "https://test.example.edu", browser="chrome",
                    sso_start_url="https://portal.example.edu/app/UserHome",
                )
        self.assertEqual(token, "synthetic")
        launch = playwright.chromium.launch_persistent_context
        self.assertEqual(launch.call_args.kwargs["user_data_dir"], str(profile.profile_dir))
        self.assertEqual(launch.call_args.kwargs["channel"], "chrome")
        self.assertEqual(page.goto.call_args.args[0], "https://portal.example.edu/app/UserHome")
        page.get_by_text.assert_not_called()
        context.on.assert_called_once()
        context.close.assert_called_once()

    def test_extracts_post_handoff_and_rejects_ambiguous_tokens(self) -> None:
        base = "https://insights.example.edu"
        self.assertEqual(_extract_sso_jwt(base + "/auth/sso", base, "jwt=synthetic"), "synthetic")
        self.assertEqual(_extract_sso_jwt(base + "/auth/sso/to_session", base, '{"jwt":"synthetic"}'), "synthetic")
        for url, body in [
            (base + "/auth/sso?jwt=a&jwt=b", None),
            (base + "/auth/sso?jwt=a", "jwt=b"),
            (base + "/auth/sso", '{"jwt":123}'),
            (base + ":8443/auth/sso?jwt=a", None),
            ("http://insights.example.edu/auth/sso?jwt=a", None),
            ("https://user@insights.example.edu/auth/sso?jwt=a", None),
        ]:
            with self.subTest(url=url):
                self.assertIsNone(_extract_sso_jwt(url, base, body))

    def test_extracts_only_the_configured_sso_handoff(self) -> None:
        base_url = "https://insights.example.edu"

        self.assertEqual(
            _extract_sso_jwt(
                f"{base_url}/auth/sso?jwt=short-lived-token&return_to=%2F",
                base_url,
            ),
            "short-lived-token",
        )
        self.assertIsNone(
            _extract_sso_jwt(
                "https://attacker.example/auth/sso?jwt=secret",
                base_url,
            )
        )
        self.assertIsNone(
            _extract_sso_jwt(
                f"{base_url}/api/user/current?jwt=secret",
                base_url,
            )
        )


class InsightsSessionCacheTests(unittest.TestCase):
    def setUp(self) -> None:
        self.settings = InsightsSettings(
            environment="TEST",
            base_url="https://test.example.edu",
            database_id=2,
        )
        self.store = MemoryCredentialStore()
        self.cache = DailyInsightsSessionCache(
            self.settings,
            store=self.store,
        )
        self.now = datetime(
            2026,
            8,
            30,
            9,
            0,
            tzinfo=timezone(timedelta(hours=-6)),
        )

    def test_session_is_valid_only_on_its_local_calendar_day(self) -> None:
        session = CachedInsightsSession.create(
            self.settings,
            "daily-session-token",
            1519,
            now=self.now,
        )

        self.assertTrue(
            session.is_valid(now=self.now + timedelta(hours=10))
        )
        self.assertFalse(
            session.is_valid(now=self.now + timedelta(days=1))
        )
        self.assertNotIn("daily-session-token", repr(session))

    def test_round_trips_through_credential_store(self) -> None:
        session = CachedInsightsSession.create(
            self.settings,
            "daily-session-token",
            1519,
            now=self.now,
        )

        self.cache.save(session)
        loaded = self.cache.load()

        self.assertEqual(loaded, session)
        self.assertIn(
            (self.cache.service, CREDENTIAL_USERNAME),
            self.store.values,
        )

        self.cache.delete()
        self.assertIsNone(self.cache.load())

    def test_deletion_failure_is_not_silently_ignored(self) -> None:
        class DeleteError(Exception):
            pass

        keyring = SimpleNamespace(
            delete_password=MagicMock(side_effect=DeleteError("private details")),
            errors=SimpleNamespace(PasswordDeleteError=DeleteError, KeyringError=DeleteError),
        )
        with patch("shared.insights.session_cache._load_keyring", return_value=keyring):
            with patch.object(SystemCredentialStore, "get_password", return_value="synthetic"):
                with self.assertRaises(InsightsCredentialError) as error:
                    SystemCredentialStore().delete_password("service", "user")
        self.assertNotIn("private details", str(error.exception))


class InsightsSmokeTestTests(unittest.TestCase):
    def test_smoke_test_runs_only_connection_sql_and_never_exports(self) -> None:
        from workflows.insights_api_test import run_insights_test as workflow

        client = MagicMock()
        client.__enter__.return_value = client
        client.run_sql_file.return_value = pd.DataFrame([[1]], columns=["connection_ok"])
        settings = InsightsSettings("TEST", "https://test.example.edu", 2, "synthetic")
        with (
            patch("sys.argv", ["insights", "--smoke-test"]),
            patch.object(workflow, "load_dotenv"),
            patch.object(workflow.InsightsSettings, "from_environment", return_value=settings),
            patch.object(workflow, "build_authenticated_client", return_value=(client, "API key")),
            patch.object(workflow, "print_discovery") as discovery,
            patch.object(pd.DataFrame, "to_excel") as export,
            patch("builtins.print"),
        ):
            workflow.main()
        discovery.assert_not_called()
        export.assert_not_called()
        path = client.run_sql_file.call_args.args[0]
        self.assertEqual(path.name, "connection_check.sql")
        self.assertIn("SELECT 1 AS connection_ok", path.read_text())


class InsightsSessionAuthenticationTests(unittest.TestCase):
    def setUp(self) -> None:
        FakeInsightsClient.created.clear()
        self.settings = InsightsSettings(
            environment="TEST",
            base_url="https://test.example.edu",
            database_id=2,
        )
        self.store = MemoryCredentialStore()
        self.cache = DailyInsightsSessionCache(
            self.settings,
            store=self.store,
        )

    def test_acquires_validates_and_caches_a_new_session(self) -> None:
        with patch(
            "shared.insights.session_auth.InsightsClient",
            FakeInsightsClient,
        ):
            client, method = build_authenticated_client(
                self.settings,
                cache=self.cache,
                acquire_session=lambda: "new-session-token",
            )

        self.assertEqual(method, "new daily SSO session")
        self.assertEqual(client.session_token, "new-session-token")
        cached = self.cache.load()
        self.assertIsNotNone(cached)
        self.assertEqual(cached.principal_id, 1519)
        self.assertEqual(cached.session_token, "new-session-token")

    def test_api_key_does_not_access_session_vault(self) -> None:
        settings = InsightsSettings("TEST", "https://test.example.edu", 2, "synthetic-key")
        with patch("shared.insights.session_auth.DailyInsightsSessionCache") as cache:
            client, method = build_authenticated_client(settings)
        cache.assert_not_called()
        self.assertEqual(method, "API key")
        client.close()

    def test_logout_of_already_absent_session_deletes_cache(self) -> None:
        self.cache.save(CachedInsightsSession.create(self.settings, "synthetic", 1519))
        with patch("shared.insights.session_auth.InsightsClient", FakeInsightsClient):
            with patch.object(FakeInsightsClient, "logout", side_effect=InsightsAPIError("Absent", status_code=404)):
                self.assertTrue(clear_cached_session(self.settings, cache=self.cache))
        self.assertIsNone(self.cache.load())

    def test_unauthorized_cached_session_triggers_new_login(self) -> None:
        self.cache.save(CachedInsightsSession.create(self.settings, "old-synthetic", 1519))
        with patch("shared.insights.session_auth.InsightsClient", FakeInsightsClient):
            with patch.object(FakeInsightsClient, "get_current_user", side_effect=[
                InsightsAPIError("Expired", status_code=401), SimpleNamespace(id=1519),
            ]):
                client, method = build_authenticated_client(
                    self.settings, cache=self.cache, acquire_session=lambda: "new-synthetic",
                )
        self.assertEqual(method, "new daily SSO session")
        self.assertEqual(client.session_token, "new-synthetic")
        self.assertTrue(FakeInsightsClient.created[0].closed)

    def test_reuses_a_valid_cached_session_without_new_login(self) -> None:
        self.cache.save(
            CachedInsightsSession.create(
                self.settings,
                "cached-session-token",
                1519,
            )
        )

        def unexpected_login() -> str:
            self.fail("A valid daily session should not trigger login.")

        with patch(
            "shared.insights.session_auth.InsightsClient",
            FakeInsightsClient,
        ):
            client, method = build_authenticated_client(
                self.settings,
                cache=self.cache,
                acquire_session=unexpected_login,
            )

        self.assertEqual(method, "cached daily SSO session")
        self.assertEqual(client.session_token, "cached-session-token")

    def test_fresh_login_revokes_cached_session_before_replacing_it(self) -> None:
        self.cache.save(
            CachedInsightsSession.create(
                self.settings,
                "old-session-token",
                1519,
            )
        )

        with patch(
            "shared.insights.session_auth.InsightsClient",
            FakeInsightsClient,
        ):
            client, method = build_authenticated_client(
                self.settings,
                cache=self.cache,
                force_login=True,
                acquire_session=lambda: "replacement-session-token",
            )

        self.assertTrue(FakeInsightsClient.created[0].logged_out)
        self.assertTrue(FakeInsightsClient.created[0].closed)
        self.assertEqual(method, "new daily SSO session")
        self.assertEqual(client.session_token, "replacement-session-token")

    def test_expired_session_is_revoked_before_new_login(self) -> None:
        yesterday = datetime.now().astimezone() - timedelta(days=1)
        self.cache.save(
            CachedInsightsSession.create(
                self.settings,
                "expired-session-token",
                1519,
                now=yesterday,
            )
        )

        with patch(
            "shared.insights.session_auth.InsightsClient",
            FakeInsightsClient,
        ):
            client, method = build_authenticated_client(
                self.settings,
                cache=self.cache,
                acquire_session=lambda: "today-session-token",
            )

        self.assertTrue(FakeInsightsClient.created[0].logged_out)
        self.assertEqual(method, "new daily SSO session")
        self.assertEqual(client.session_token, "today-session-token")


class InsightsCleanupTaskContractTests(unittest.TestCase):
    def test_cleanup_task_revokes_daily_with_limited_user_permissions(self) -> None:
        project_root = Path(__file__).resolve().parents[2]
        script = (
            project_root
            / "powershell"
            / "setup_insights_session_cleanup.ps1"
        ).read_text(encoding="utf-8")

        self.assertIn("--logout", script)
        self.assertIn('-At "12:00 AM"', script)
        self.assertIn("-StartWhenAvailable", script)
        self.assertIn("-LogonType Interactive", script)
        self.assertIn("-RunLevel Limited", script)
        self.assertNotIn("API_KEY", script)
        self.assertNotIn("X-Metabase-Session", script)


class InsightsClientTests(unittest.TestCase):
    def test_metadata_discovery_does_not_require_or_infer_database_id(self) -> None:
        session = StubSession(make_response(200, {"data": [
            {"id": 7, "name": "Example Warehouse", "engine": "postgres"},
        ]}))
        client = InsightsClient(
            "https://test.example.edu", session_token="synthetic",
            http_session=session,
        )
        self.assertEqual(client.list_databases()[0].id, 7)
        with self.assertRaisesRegex(InsightsAPIError, "verified database ID"):
            client.run_sql("SELECT 1")
        self.assertEqual(len(session.requests), 1)

    def test_api_redirect_is_not_followed(self) -> None:
        session = StubSession(make_response(307, {}))
        client = InsightsClient("https://test.example.edu", 2, api_key="synthetic", http_session=session)
        with self.assertRaises(InsightsAPIError):
            client.get_current_user()
        self.assertFalse(session.requests[0]["allow_redirects"])

    def test_runs_native_sql_and_returns_dataframe(self) -> None:
        session = StubSession(
            make_response(
                200,
                {
                    "status": "completed",
                    "data": {
                        "rows": [["A001", "Ada"]],
                        "cols": [
                            {"display_name": "spriden_id"},
                            {"name": "spriden_first_name"},
                        ],
                    },
                },
            )
        )
        client = InsightsClient(
            "https://test.example.edu",
            2,
            api_key="api-key",
            http_session=session,  # type: ignore[arg-type]
        )

        result = client.run_sql("SELECT spriden_id FROM spriden LIMIT 1")

        expected = pd.DataFrame(
            [["A001", "Ada"]],
            columns=["spriden_id", "spriden_first_name"],
        )
        pd.testing.assert_frame_equal(result, expected)
        request = session.requests[0]
        self.assertEqual(request["method"], "POST")
        self.assertEqual(
            request["url"],
            "https://test.example.edu/api/dataset",
        )
        headers = request["headers"]
        self.assertEqual(headers["X-API-Key"], "api-key")  # type: ignore[index]
        self.assertNotIn("X-Metabase-Session", headers)
        payload = request["json"]
        self.assertEqual(payload["database"], 2)  # type: ignore[index]

    def test_http_error_does_not_include_response_body(self) -> None:
        session = StubSession(
            make_response(
                500,
                {"error": "SELECT secret_column FROM sensitive_table"},
            )
        )
        client = InsightsClient(
            "https://test.example.edu",
            2,
            session_token="session-token",
            http_session=session,  # type: ignore[arg-type]
        )

        with self.assertRaises(InsightsAPIError) as context:
            client.run_sql("SELECT secret_column FROM sensitive_table")

        message = str(context.exception)
        self.assertIn("HTTP 500", message)
        self.assertNotIn("secret_column", message)
        self.assertNotIn("session-token", message)

    def test_logout_revokes_session_without_expecting_json(self) -> None:
        session = StubSession(make_response(204, {}))
        client = InsightsClient(
            "https://test.example.edu",
            2,
            session_token="session-token",
            http_session=session,  # type: ignore[arg-type]
        )

        client.logout()

        self.assertEqual(session.requests[0]["method"], "DELETE")
        self.assertEqual(
            session.requests[0]["url"],
            "https://test.example.edu/api/session",
        )

    def test_discovers_only_allow_listed_metadata(self) -> None:
        session = StubSession(
            make_response(
                200,
                {
                    "id": 1519,
                    "first_name": "Test",
                    "last_name": "Analyst",
                    "email": "analyst@example.edu",
                    "is_superuser": False,
                    "private_field": "not retained",
                },
            ),
            make_response(
                200,
                {
                    "data": [
                        {
                            "id": 2,
                            "name": "TEST Warehouse",
                            "engine": "postgres",
                            "initial_sync_status": "complete",
                            "is_sample": False,
                            "details": {"password": "not retained"},
                        }
                    ]
                },
            ),
            make_response(
                200,
                {
                    "version": {
                        "tag": "v1.57.17",
                        "date": "2026-08-23",
                        "hash": "abc123",
                    },
                    "setup-token": "not retained",
                },
            ),
        )
        client = InsightsClient(
            "https://test.example.edu",
            2,
            api_key="api-key",
            http_session=session,  # type: ignore[arg-type]
        )

        user = client.get_current_user()
        databases = client.list_databases()
        server = client.get_server_info()

        self.assertEqual(user.id, 1519)
        self.assertFalse(user.is_superuser)
        self.assertEqual(databases[0].id, 2)
        self.assertEqual(databases[0].engine, "postgres")
        self.assertEqual(server.version_tag, "v1.57.17")
        self.assertFalse(hasattr(databases[0], "details"))
        self.assertFalse(hasattr(server, "setup_token"))


if __name__ == "__main__":
    unittest.main()
