"""Synthetic connection setup, action and Qt checks; no live authentication."""

import json
import os
import queue
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pandas as pd

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from PySide6.QtWidgets import QApplication, QMessageBox

from app.gui.models import WorkflowContext, WorkflowMode, WorkflowResult
from app.gui.pages.connections import ConnectionsPage
from app.gui.services.insights import run_insights_connection
from shared.insights.config import (
    InsightsConfigurationError, InsightsDepartmentProfile, InsightsSettings,
    load_department_profiles,
)


def profiles():
    return {"TEST": InsightsDepartmentProfile(
        InsightsSettings("TEST", "https://test.example.edu", 2,
                         sso_start_url="https://portal.example.edu"),
        "https://experience.example.edu/test",
    ), "PROD": None}


def production_profile():
    return InsightsDepartmentProfile(
        InsightsSettings("PROD", "https://prod.example.edu", 7,
                         sso_start_url="https://portal.example.edu"),
        "https://experience.example.edu/prod",
    )


class DepartmentInsightsTests(unittest.TestCase):
    def test_department_profiles_ignore_local_environment_and_keep_hosts_separate(self):
        with patch.dict(os.environ, {"INSIGHTS_ENV": "PROD", "INSIGHTS_TEST_API_KEY": "synthetic"}):
            result = load_department_profiles()
        self.assertEqual(result["TEST"].settings.environment, "TEST")
        self.assertIsNone(result["TEST"].settings.api_key)
        self.assertEqual(result["PROD"].settings.environment, "PROD")
        self.assertIsNone(result["PROD"].settings.api_key)
        self.assertNotEqual(result["TEST"].settings.base_url, result["PROD"].settings.base_url)
        self.assertEqual(result["PROD"].settings.base_url, "https://minessis-insights.50115.elluciancloud.com")
        self.assertEqual(result["PROD"].settings.database_id, 2)

    def test_rejects_secret_fields_and_invalid_profiles(self):
        valid = {"schemaVersion": 1, "environments": {"TEST": {
            "base_url": "https://test.example.edu", "database_id": 2,
            "sso_start_url": "https://portal.example.edu",
            "experience_url": "https://experience.example.edu/test",
        }, "PROD": None}}
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "profiles.json"
            for key, value in (("api_key", "synthetic-secret"), ("database_id", True),
                               ("experience_url", "https://example.edu?jwt=synthetic")):
                payload = json.loads(json.dumps(valid))
                payload["environments"]["TEST"][key] = value
                path.write_text(json.dumps(payload))
                with self.subTest(key=key), self.assertRaises(InsightsConfigurationError):
                    load_department_profiles(path)


class InsightsConnectionServiceTests(unittest.TestCase):
    def setUp(self):
        self.profile_patch = patch("app.gui.services.insights.load_department_profiles", return_value=profiles())
        self.profile_patch.start()
        self.addCleanup(self.profile_patch.stop)

    def run_action(self, action, mode=WorkflowMode.TEST):
        return run_insights_connection(WorkflowContext("insights_connection", {"action": action}, mode))

    def test_unconfigured_prod_never_authenticates(self):
        with patch("app.gui.services.insights.build_authenticated_client") as build:
            result = self.run_action("connect", WorkflowMode.PRODUCTION)
        self.assertFalse(result.success)
        build.assert_not_called()

    def test_check_without_session_never_opens_browser(self):
        with patch("app.gui.services.insights.DailyInsightsSessionCache") as cache:
            cache.return_value.load.return_value = None
            with patch("app.gui.services.insights.build_authenticated_client") as build:
                result = self.run_action("check")
        self.assertFalse(result.success)
        self.assertIn("Sign-in", result.message)
        build.assert_not_called()

    def test_connect_reuses_builder_and_only_runs_smoke_sql(self):
        client = MagicMock()
        client.__enter__.return_value = client
        client.get_current_user.return_value = SimpleNamespace(id=123)
        client.run_sql_file.return_value = pd.DataFrame([[1]])
        with patch("app.gui.services.insights.build_authenticated_client", return_value=(client, "cached session")) as build:
            result = self.run_action("connect")
        self.assertTrue(result.success)
        self.assertEqual(build.call_args.args[0].environment, "TEST")
        self.assertFalse(build.call_args.kwargs["force_login"])
        self.assertEqual(client.run_sql_file.call_args.args[0].name, "connection_check.sql")
        client.__exit__.assert_called_once()

    def test_logout_only_clears_selected_session(self):
        with patch("app.gui.services.insights.clear_cached_session", return_value=True) as clear:
            result = self.run_action("logout")
        self.assertTrue(result.success)
        self.assertEqual(clear.call_args.args[0].environment, "TEST")

    def test_prod_uses_only_its_own_department_settings(self):
        configured = profiles()
        configured["PROD"] = production_profile()
        client = MagicMock()
        client.__enter__.return_value = client
        client.get_current_user.return_value = SimpleNamespace(id=456)
        client.run_sql_file.return_value = pd.DataFrame([[1]])
        with (
            patch("app.gui.services.insights.load_department_profiles", return_value=configured),
            patch("app.gui.services.insights.build_authenticated_client", return_value=(client, "cached session")) as build,
        ):
            result = self.run_action("connect", WorkflowMode.PRODUCTION)
        self.assertTrue(result.success)
        selected = build.call_args.args[0]
        self.assertEqual(selected.environment, "PROD")
        self.assertEqual(selected.base_url, "https://prod.example.edu")
        self.assertEqual(selected.database_id, 7)
        self.assertIn("PROD verified", result.message)

    def test_unexpected_error_never_reaches_general_logger(self):
        with patch("app.gui.services.insights.build_authenticated_client", side_effect=RuntimeError("synthetic-secret")):
            result = self.run_action("connect")
        self.assertFalse(result.success)
        self.assertNotIn("synthetic-secret", result.message)


class ConnectionsPageTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.qt = QApplication.instance() or QApplication([])

    def setUp(self):
        self.executor = MagicMock()
        self.executor.is_running = False
        self.results = queue.Queue()
        self.executor.run_async.return_value = self.results
        with patch("app.gui.pages.connections.load_department_profiles", return_value=profiles()):
            self.page = ConnectionsPage(None, self.executor, lambda: True)
        self.addCleanup(self.page.deleteLater)

    def test_initial_test_and_unconfigured_prod(self):
        self.assertEqual(self.page.mode.currentData(), "TEST")
        self.assertTrue(self.page.actions["connect"].isEnabled())
        self.executor.run_async.assert_not_called()
        self.page.mode.setCurrentIndex(1)
        self.assertTrue(all(not item.isEnabled() for item in self.page.actions.values()))

    def test_busy_state_and_environment_result_separation(self):
        self.page._run("connect")
        self.assertFalse(self.page.mode.isEnabled())
        context = self.executor.run_async.call_args.args[1]
        self.assertEqual(context.mode, WorkflowMode.TEST)
        self.results.put(WorkflowResult(True, "TEST verified"))
        self.page._poll()
        self.assertTrue(self.page.mode.isEnabled())
        self.assertIn("TEST verified", self.page.status_label.text())
        self.page.mode.setCurrentIndex(1)
        self.assertNotIn("TEST verified", self.page.status_label.text())

    def test_action_rechecks_authorization(self):
        self.page.authorize = lambda: False
        self.page._run("connect")
        self.executor.run_async.assert_not_called()

    def test_configured_prod_requires_confirmation(self):
        self.page.profiles["PROD"] = production_profile()
        self.page.mode.setCurrentIndex(1)
        with patch.object(QMessageBox, "question", return_value=QMessageBox.StandardButton.No) as ask:
            self.page._run("connect")
        ask.assert_called_once()
        self.executor.run_async.assert_not_called()

    def test_confirmed_prod_action_keeps_prod_context(self):
        self.page.profiles["PROD"] = production_profile()
        self.page.mode.setCurrentIndex(1)
        with patch.object(QMessageBox, "question", return_value=QMessageBox.StandardButton.Yes):
            self.page._run("connect")
        context = self.executor.run_async.call_args.args[1]
        self.assertEqual(context.mode, WorkflowMode.PRODUCTION)
        self.results.put(WorkflowResult(True, "PROD verified"))
        self.page._poll()
        self.page.mode.setCurrentIndex(0)
        self.assertNotIn("PROD verified", self.page.status_label.text())
