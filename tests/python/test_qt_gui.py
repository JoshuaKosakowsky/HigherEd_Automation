"""Headless Qt interaction tests; no production inputs or shared policy writes."""

from __future__ import annotations

import json
import logging
import os
import tempfile
import sys
import time
import unittest
from dataclasses import replace
from pathlib import Path
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QMimeData, QPointF, Qt, QUrl, QTimer
from PySide6.QtGui import QDropEvent
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QCheckBox, QComboBox, QDialogButtonBox, QLineEdit, QMessageBox

from app.gui.main import AutomationApplication
from app.gui.models import ParameterDefinition, ParameterKind, WorkflowDefinition, WorkflowMode, WorkflowResult
from app.gui.pages.access_management import ProfileDialog
from app.gui.pages.workflow_detail import WorkflowDetailPage
from app.gui.services.access import load_access_configuration
from app.gui.services.drag_drop import FileInput
from app.gui.services.execution import WorkflowExecutor
from app.gui.services.parameters import parse_parameters
from app.gui.theme import apply_theme
from app.gui.workflow_registry import get_workflow


class QtGuiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.qt = QApplication.instance() or QApplication([])
        apply_theme(cls.qt)

    def setUp(self):
        self.callback_errors = []
        original_hook = sys.excepthook
        sys.excepthook = lambda *error: self.callback_errors.append(error)
        self.addCleanup(setattr, sys, "excepthook", original_hook)
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.policy = self.root / "policy.json"
        self.payload = {
            "schemaVersion": 3,
            "metadata": {"ownerLogin": "OWNER"},
            "ownerProtection": None,
            "users": {
                "OWNER": {"displayName": "Example Owner", "jobTitle": "Manager", "view": "administrator"},
                "STAFF": {"displayName": "Example Staff", "jobTitle": "Analyst", "view": "analyst"},
            },
            "views": {"administrator": {"workflows": ["*"]}, "analyst": {"workflows": []},
                      "cashier": {"workflows": []}},
        }
        self.write_policy()
        self.window = None

    def tearDown(self):
        if self.window:
            self.window.close()
            self.window.deleteLater()
        self.qt.processEvents()
        self.assertEqual(self.callback_errors, [], "An exception escaped a Qt signal callback")

    def write_policy(self):
        self.policy.write_text(json.dumps(self.payload), encoding="utf-8")

    def open_app(self, login="OWNER"):
        self.window = AutomationApplication(user_login_override=login, access_config_path=self.policy)
        self.window.show()
        self.qt.processEvents()
        return self.window

    def test_admin_navigation_and_every_registered_form_render(self):
        window = self.open_app()
        self.assertFalse(window.access_button.isHidden())
        for workflow in window.visible_workflows:
            window.show_workflow(workflow)
            self.qt.processEvents()
            self.assertEqual(set(window.current_page.inputs), {p.key for p in workflow.parameters})
        window.show_access_management()
        self.assertEqual(window.current_page.table.rowCount(), 2)
        window.show_home()
        window.current_page.search.setText("Refund")
        self.assertEqual(sum(not card.isHidden() for card, _ in window.current_page.cards), 1)

    def test_staff_view_and_missing_policy_fail_closed(self):
        window = self.open_app("STAFF")
        self.assertTrue(window.access_button.isHidden())
        self.assertEqual(window.visible_workflows, ())
        window.show_access_management()
        self.assertTrue(window.access_button.isHidden())
        self.policy.unlink()
        window.show_home()
        self.assertEqual(window.visible_workflows, ())
        self.assertIsNotNone(window.access_error)

    def test_revocation_is_checked_before_opening_workflow(self):
        window = self.open_app()
        self.payload["users"]["OWNER"]["active"] = False
        self.payload["users"]["STAFF"]["view"] = "administrator"
        self.write_policy()
        with patch.object(QMessageBox, "warning"):
            window.show_workflow(get_workflow("refund_review"))
        self.assertEqual(window.visible_workflows, ())
        self.assertTrue(window.access_button.isHidden())

    def test_profile_form_requires_explicit_view_and_preserves_login(self):
        configuration = load_access_configuration(self.policy)
        dialog = ProfileDialog(None, configuration)
        dialog.login.setText("NEW")
        dialog.name.setText("New Person")
        dialog.title.setText("Cashier")
        dialog._validate()
        self.assertIsNone(dialog.result_profile)
        dialog.view.setCurrentIndex(dialog.view.findData("cashier"))
        dialog._validate()
        self.assertEqual(dialog.result_profile.view, "cashier")
        edit = ProfileDialog(None, configuration, configuration.profile_for_login("OWNER"))
        self.assertTrue(edit.login.isReadOnly())
        dialog.close()
        edit.close()

    def test_admin_save_and_revoke_use_existing_policy_service(self):
        window = self.open_app()
        window.show_access_management()
        page = window.current_page
        users = dict(page.configuration.users)
        users["staff"] = replace(users["staff"], view="cashier", active=False)
        self.assertTrue(page._save(replace(page.configuration, users=users)))
        saved = load_access_configuration(self.policy)
        self.assertIsNone(saved.profile_for_login("STAFF"))
        self.assertEqual(saved.raw_profile_for_login("STAFF").view, "cashier")
        self.assertTrue(self.policy.with_name(".policy.backup.json").exists())

    def test_permissions_dialog_changes_only_selected_view(self):
        window = self.open_app()
        window.show_access_management()
        page = window.current_page

        def edit():
            dialog = QApplication.activeModalWidget()
            combo = dialog.findChild(QComboBox)
            combo.setCurrentIndex(combo.findData("analyst"))
            dialog.findChildren(QCheckBox)[0].setChecked(True)
            controls = dialog.findChild(QDialogButtonBox)
            controls.button(QDialogButtonBox.StandardButton.Save).click()

        QTimer.singleShot(0, edit)
        page._edit_view()
        saved = load_access_configuration(self.policy)
        self.assertEqual(saved.workflows_by_view["analyst"], frozenset({"population_testing"}))
        self.assertEqual(saved.workflows_by_view["cashier"], frozenset())
        self.assertEqual(saved.workflows_by_view["administrator"], frozenset({"*"}))

    def test_owner_password_dialog_writes_verifier_and_blocks_unapproved_edits(self):
        window = self.open_app()
        window.show_access_management()
        page = window.current_page

        def set_password():
            dialog = QApplication.activeModalWidget()
            fields = dialog.findChildren(QLineEdit)
            # With no current password, only new/confirm fields are in the dialog.
            for field in fields:
                field.setText("synthetic-owner-secret")
            dialog.findChild(QDialogButtonBox).button(QDialogButtonBox.StandardButton.Save).click()

        QTimer.singleShot(0, set_password)
        page._set_owner_password()
        self.assertIsNotNone(load_access_configuration(self.policy).owner_protection)
        self.assertNotIn("synthetic-owner-secret", self.policy.read_text())
        users = dict(page.configuration.users)
        users["owner"] = replace(users["owner"], job_title="Updated title")
        with patch.object(QMessageBox, "warning"):
            self.assertFalse(page._save(replace(page.configuration, users=users)))
        self.assertEqual(load_access_configuration(self.policy).users["owner"].job_title, "Manager")

    def test_native_drop_with_spaces_accumulates_without_duplicates(self):
        source = self.root / "file with spaces.csv"
        source.touch()
        field = FileInput(ParameterDefinition("files", "Files", ParameterKind.MULTI_INPUT_FILE))
        mime = QMimeData()
        mime.setUrls([QUrl.fromLocalFile(str(source))])
        event = QDropEvent(QPointF(10, 10), Qt.DropAction.CopyAction, mime,
                           Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier)
        field.dropEvent(event)
        self.assertTrue(event.isAccepted())
        field.accept_paths((source,))
        self.assertEqual(field.text(), str(source))
        self.assertFalse(field.accept_paths((self.root,)))
        self.assertEqual(field.text(), str(source))
        single = FileInput(ParameterDefinition("file", "File", ParameterKind.INPUT_FILE))
        self.assertFalse(single.accept_paths((source, source)))
        self.assertEqual(single.text(), "")
        field.close()
        single.close()

    def test_existing_parameter_validation_preserved(self):
        percent = ParameterDefinition("p", "Percent", ParameterKind.PERCENT, minimum=1, maximum=100)
        names = ParameterDefinition("n", "Names", ParameterKind.NAME_LIST)
        self.assertEqual(parse_parameters((percent, names), {"p": "25", "n": "One, Two\nThree"}),
                         {"p": 25.0, "n": ("One", "Two", "Three")})
        for value in ("nan", "inf", "101", "0"):
            with self.assertRaises(ValueError):
                parse_parameters((percent,), {"p": value})
        with self.assertRaises(ValueError):
            parse_parameters((names,), {"n": "One\nOne"})

    def test_actual_textbook_workflow_runs_and_exposes_output_actions(self):
        source = self.root / "finaid_example.csv"
        source.write_text("ignored,ignored,900000001,BKFA,ignored,125.50\n", encoding="utf-8")
        output = self.root / "TSPLOAD.csv"
        window = self.open_app()
        window.show_workflow(get_workflow("textbook_brokers"))
        page = window.current_page
        page.inputs["source_files"].setText(str(source))
        page.inputs["output_file"].setText(str(output))
        with patch.object(page, "_confirm", return_value=True):
            page._run()
        self.assertFalse(window.home_button.isEnabled())
        deadline = time.monotonic() + 5
        while page.result_queue is not None and time.monotonic() < deadline:
            QTest.qWait(20)
        self.assertIsNone(page.result_queue)
        self.assertTrue(output.exists())
        self.assertFalse(page.output_button.isHidden())
        self.assertTrue(window.home_button.isEnabled())
        self.assertTrue(page.form.isEnabled())

    def test_production_defaults_to_test_and_cancel_does_not_run(self):
        definition = WorkflowDefinition("modes", "Modes", "Example", "Testing",
                                        lambda _: WorkflowResult(True, "Done"),
                                        supported_modes=(WorkflowMode.PRODUCTION, WorkflowMode.TEST))
        executor = WorkflowExecutor(logging.getLogger("test"), self.root / "log.txt")
        page = WorkflowDetailPage(None, definition, executor, lambda: None)
        self.assertEqual(page.mode.currentData(), "TEST")
        page.mode.setCurrentIndex(page.mode.findData("PROD"))
        self.assertFalse(page.production_warning.isHidden())
        with patch.object(page, "_confirm", return_value=False) as confirmation:
            page._run()
        self.assertEqual(confirmation.call_args.args[0].mode, WorkflowMode.PRODUCTION)
        self.assertFalse(executor.is_running)
        self.assertIsNone(page.result_queue)
        page.close()

    def test_running_workflow_blocks_close_and_navigation(self):
        window = self.open_app()
        original = window.current_page
        window._set_busy(True)
        window.show_home()
        self.assertIs(window.current_page, original)
        with patch.object(QMessageBox, "warning"):
            self.assertFalse(window.close())
        window._set_busy(False)
        self.assertTrue(window.close())


if __name__ == "__main__":
    unittest.main()
