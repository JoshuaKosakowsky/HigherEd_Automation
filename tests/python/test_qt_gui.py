"""Headless Qt interaction tests; no production inputs or shared policy writes."""

from __future__ import annotations

import json
import logging
import os
import queue
import tempfile
import sys
import time
import unittest
from dataclasses import replace
from pathlib import Path
from unittest.mock import PropertyMock, patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QMimeData, QPointF, Qt, QUrl, QTimer
from PySide6.QtGui import QDropEvent
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QCheckBox, QComboBox, QDialogButtonBox, QInputDialog, QLineEdit, QMessageBox, QPushButton

from app.gui.main import AutomationApplication
from app.gui.models import ParameterDefinition, ParameterKind, WorkflowContext, WorkflowDefinition, WorkflowMode, WorkflowResult
from app.gui.pages.access_management import ProfileDialog
from app.gui.pages.workflow_detail import WorkflowDetailPage
from app.gui.services.access import (
    AccessConfigurationError, add_view, rename_view, remove_view, load_access_configuration,
)
from app.gui.services.drag_drop import FileInput
from app.gui.services.execution import WorkflowExecutor
from app.gui.services.parameters import parse_parameters
from app.gui.theme import apply_theme
from app.gui.workflow_registry import get_workflow
from app.gui.progress import WorkflowProgressWidget
from shared.progress import ProgressUpdate


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
            self.assertIsInstance(window.current_page.progress, WorkflowProgressWidget)
            self.assertEqual(window.current_page.progress.bar.accessibleName(), "Current stage progress")
        window.show_access_management()
        self.assertEqual(window.current_page.table.rowCount(), 2)
        window.show_home()
        window.current_page.search.setText("Refund")
        self.assertEqual(sum(not card.isHidden() for card, _ in window.current_page.cards), 1)

    def test_recon_has_one_card_and_admin_can_choose_sql(self):
        window = self.open_app()
        self.assertEqual(sum(item.name == "Textbook Recon" for item in window.visible_workflows), 1)
        window.show_workflow(get_workflow("textbook_recon_manual"))
        page = window.current_page
        self.assertEqual(page.recon_source.count(), 2)
        self.assertEqual(page.recon_source.currentData(), "manual")
        broker = self.root / "brokers.xlsx"
        broker.touch()
        page.inputs["brokers_file"].setText(str(broker))
        page.inputs["frst_file"].setText(str(self.root / "not-present.xlsx"))
        page.recon_source.setCurrentIndex(page.recon_source.findData("sql"))
        self.assertTrue(page.inputs["frst_file"].isHidden())
        self.assertTrue(page.inputs["book_file"].isHidden())
        self.assertTrue(page.production_warning.isVisible())
        captured = []
        with patch.object(page, "_confirm", side_effect=lambda context: captured.append(context) or False):
            page._run()
        self.assertEqual(captured[0].mode, WorkflowMode.PRODUCTION)
        self.assertEqual(captured[0].parameters["banner_source"], "sql")
        self.assertNotIn("frst_file", captured[0].parameters)

    def test_refund_admin_source_selection_and_manual_validation(self):
        window = self.open_app()
        window.show_workflow(get_workflow("refund_review"))
        page = window.current_page
        self.assertEqual(page.refund_source.count(), 2)
        self.assertEqual(page.refund_source.currentData(), "manual")
        with self.assertRaisesRegex(ValueError, "was not found"):
            page._parse_parameters()
        transaction = self.root / "transactions.csv"
        context = self.root / "context.xlsx"
        transaction.touch()
        context.touch()
        page.inputs["transaction_file"].setText(str(transaction))
        page.inputs["context_file"].setText(str(context))
        parsed = page._parse_parameters()
        self.assertEqual(parsed["refund_source"], "manual")
        self.assertEqual(parsed["transaction_file"], transaction)
        page.refund_source.setCurrentIndex(page.refund_source.findData("sql"))
        self.assertTrue(page.inputs["transaction_file"].isHidden())
        self.assertTrue(page.inputs["context_file"].isHidden())
        self.assertTrue(page.production_warning.isVisible())
        captured = []
        with patch.object(page, "_confirm", side_effect=lambda context: captured.append(context) or False):
            page._run()
        self.assertEqual(captured[0].mode, WorkflowMode.PRODUCTION)
        self.assertEqual(captured[0].parameters["refund_source"], "sql")
        self.assertNotIn("transaction_file", captured[0].parameters)
        self.assertNotIn("context_file", captured[0].parameters)
        page.refund_source.setCurrentIndex(0)
        self.assertFalse(page.inputs["transaction_file"].isHidden())
        self.assertTrue(page.production_warning.isHidden())

    def test_refund_is_admin_only_even_with_explicit_staff_grant(self):
        self.payload["views"]["analyst"]["workflows"] = ["refund_review"]
        self.write_policy()
        window = self.open_app("STAFF")
        self.assertEqual(window.visible_workflows, ())
        with patch.object(QMessageBox, "warning"):
            window.show_workflow(get_workflow("refund_review"))
        self.assertFalse(isinstance(window.current_page, WorkflowDetailPage))

    def test_staff_recon_offers_only_manual_files(self):
        self.payload["views"]["analyst"]["workflows"] = ["textbook_recon_manual"]
        self.write_policy()
        window = self.open_app("STAFF")
        self.assertEqual([item.name for item in window.visible_workflows], ["Textbook Recon"])
        window.show_workflow(window.visible_workflows[0])
        page = window.current_page
        self.assertEqual(page.recon_source.count(), 1)
        self.assertEqual(page.recon_source.currentData(), "manual")
        self.assertFalse(page.inputs["frst_file"].isHidden())
        self.assertFalse(page.inputs["book_file"].isHidden())
        self.assertTrue(page.production_warning.isHidden())

    def test_grad_contract_sponsor_sees_1305_uploads_only(self):
        self.payload["views"]["Grad Contract Sponsor"] = {"workflows": ["graduate_contract_recon"]}
        self.payload["users"]["STAFF"]["view"] = "Grad Contract Sponsor"
        self.write_policy()
        window = self.open_app("STAFF")
        self.assertEqual([item.workflow_id for item in window.visible_workflows], ["graduate_contract_recon"])
        window.show_workflow(window.visible_workflows[0])
        page = window.current_page
        self.assertEqual(page.recon_source.count(), 1)
        self.assertEqual(page.recon_source.currentData(), "manual")
        self.assertFalse(page.inputs["banner_file"].isHidden())
        self.assertEqual(page.inputs["detail_codes"].text(), "")
        self.assertEqual(page.mode.count(), 0)
        self.assertTrue(page.inputs["start_date"].calendarPopup())
        self.assertTrue(page.production_warning.isHidden())

    def test_admin_1305_offers_upload_and_prod_without_optional_banner_file(self):
        window = self.open_app()
        window.show_workflow(get_workflow("graduate_contract_recon"))
        page = window.current_page
        self.assertEqual(page.recon_source.count(), 2)
        page.recon_source.setCurrentIndex(page.recon_source.findData("sql"))
        self.assertTrue(page.inputs["banner_file"].isHidden())
        self.assertFalse(page.inputs["workday_file"].isHidden())
        self.assertFalse(page.production_warning.isHidden())
        wd = self.root / "synthetic_wd.xlsx"; wd.touch()
        page.inputs["workday_file"].editor.setText(str(wd))
        page.inputs["detail_codes"].setText("TPDT")
        values = page._parse_parameters()
        self.assertEqual(values["banner_source"], "sql")
        self.assertNotIn("banner_file", values)
        self.assertRegex(values["start_date"], r"^[0-9]{4}-[0-9]{2}-[0-9]{2}$")

    def test_staff_view_and_missing_policy_fail_closed(self):
        window = self.open_app("STAFF")
        self.assertTrue(window.access_button.isHidden())
        self.assertTrue(window.connections_button.isHidden())
        self.assertEqual(window.visible_workflows, ())
        window.show_access_management()
        self.assertTrue(window.access_button.isHidden())
        self.policy.unlink()
        window.show_home()
        self.assertEqual(window.visible_workflows, ())
        self.assertIsNotNone(window.access_error)

    def test_connections_are_admin_only_and_recheck_revocation(self):
        window = self.open_app()
        self.assertFalse(window.connections_button.isHidden())
        window.show_connections()
        page = window.current_page
        self.assertEqual(page.mode.currentData(), "TEST")
        self.payload["users"]["OWNER"]["active"] = False
        self.write_policy()
        with patch.object(window.executor, "run_async") as run:
            page._run("connect")
        run.assert_not_called()
        self.assertTrue(window.connections_button.isHidden())

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

    def test_view_rules_preserve_assignments_and_reject_invalid_changes(self):
        configuration = load_access_configuration(self.policy)
        added = add_view(configuration, "  Accounting Manager  ")
        self.assertEqual(added.workflows_by_view["accounting manager"], frozenset())
        for name in ("", "  ", "ANALYST", "Administrator", "Bad\nName"):
            with self.assertRaises(AccessConfigurationError):
                add_view(configuration, name)
        renamed = rename_view(configuration, "analyst", "AR Specialist")
        self.assertEqual(renamed.users["staff"].view, "ar specialist")
        self.assertEqual(renamed.users["staff"].job_title, "Analyst")
        revoked_users = dict(configuration.users)
        revoked_users["staff"] = replace(revoked_users["staff"], active=False)
        with self.assertRaises(AccessConfigurationError):
            remove_view(replace(configuration, users=revoked_users), "analyst")
        for operation in (lambda: rename_view(configuration, "administrator", "Boss"),
                          lambda: remove_view(configuration, "administrator"),
                          lambda: rename_view(configuration, "analyst", "cashier")):
            with self.assertRaises(AccessConfigurationError):
                operation()
        self.assertNotIn("accounting manager", remove_view(added, "accounting manager").workflows_by_view)

    def test_admin_can_create_rename_and_remove_views_from_dialog(self):
        # A second administrator can manage views without the owner's password.
        self.payload["users"]["DELEGATE"] = {
            "displayName": "Example Delegate", "jobTitle": "Bursar", "view": "administrator"
        }
        self.write_policy()
        window = self.open_app("DELEGATE")
        window.show_access_management()
        page = window.current_page

        def edit():
            dialog = QApplication.activeModalWidget()
            try:
                buttons = {widget.text(): widget for widget in dialog.findChildren(QPushButton)}
                combo = dialog.findChild(QComboBox)
                with patch.object(QInputDialog, "getText", return_value=("Collections", True)):
                    buttons["Add view"].click()
                self.assertEqual(combo.currentData(), "collections")
                self.assertTrue(all(not check.isChecked() for check in dialog.findChildren(QCheckBox)))
                dialog.findChildren(QCheckBox)[0].setChecked(True)
                combo.setCurrentIndex(combo.findData("analyst"))
                with patch.object(QInputDialog, "getText", return_value=("AR Specialist", True)):
                    buttons["Rename view"].click()
                combo.setCurrentIndex(combo.findData("cashier"))
                with patch.object(QMessageBox, "question", return_value=QMessageBox.StandardButton.Yes):
                    buttons["Remove view"].click()
                dialog.findChild(QDialogButtonBox).button(QDialogButtonBox.StandardButton.Save).click()
            finally:
                dialog.reject()

        QTimer.singleShot(0, edit)
        page._edit_view()
        saved = load_access_configuration(self.policy)
        self.assertEqual(saved.workflows_by_view["collections"], frozenset({"population_testing"}))
        self.assertEqual(saved.users["staff"].view, "ar specialist")
        self.assertNotIn("analyst", saved.workflows_by_view)
        self.assertNotIn("cashier", saved.workflows_by_view)
        self.assertEqual(saved.workflows_by_view["administrator"], frozenset({"*"}))
        profile = ProfileDialog(None, saved)
        self.assertGreaterEqual(profile.view.findData("collections"), 0)
        profile.close()

    def test_cancel_view_changes_does_not_write_policy(self):
        window = self.open_app()
        window.show_access_management()
        original = self.policy.read_bytes()

        def edit():
            dialog = QApplication.activeModalWidget()
            try:
                add = next(widget for widget in dialog.findChildren(QPushButton) if widget.text() == "Add view")
                with patch.object(QInputDialog, "getText", return_value=("Temporary", True)):
                    add.click()
            finally:
                dialog.reject()

        QTimer.singleShot(0, edit)
        window.current_page._edit_view()
        self.assertEqual(self.policy.read_bytes(), original)

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

    def test_textbook_workflow_shows_only_sftp_term_input(self):
        window = self.open_app()
        window.show_workflow(get_workflow("textbook_brokers"))
        page = window.current_page
        self.assertEqual(set(page.inputs), {"term_code"})
        self.assertIn("SFTP", page.definition.description)

    def test_textbook_preparation_prompts_and_selects_archive_for_same_term(self):
        window = self.open_app()
        window.show_workflow(get_workflow("textbook_brokers"))
        page = window.current_page
        results = queue.Queue()
        with patch.object(page, "_confirm", return_value=True), patch.object(window.executor, "run_async", return_value=results) as run:
            page.inputs["term_code"].setText("202680")
            page._run()
        self.assertEqual(run.call_args.args[1].parameters["step"], "prepare")
        self.assertFalse(page.form.isEnabled())
        results.put(WorkflowResult(True, "Prepared", self.root / "TSPLOAD.csv"))
        with patch.object(QMessageBox, "information") as prompt:
            page._poll_result()
        prompt.assert_called_once()
        self.assertIn("Complete TSPLOAD", prompt.call_args.args[2])
        self.assertEqual(page.textbook_step.currentData(), "archive")
        self.assertEqual(page.inputs["term_code"].text(), "202680")
        self.assertTrue(page.form.isEnabled())
        self.assertIsNone(page.result_queue)

    def test_textbook_no_pending_or_failure_does_not_offer_archive(self):
        window = self.open_app()
        window.show_workflow(get_workflow("textbook_brokers"))
        page = window.current_page
        for result in (WorkflowResult(True, "No pending files"), WorkflowResult(False, "Failed")):
            page.active_context = WorkflowContext("textbook_brokers", {"term_code": "202680", "step": "prepare"})
            page.result_queue = queue.Queue()
            page.result_queue.put(result)
            with patch.object(QMessageBox, "information") as prompt, patch.object(QMessageBox, "warning"):
                page._poll_result()
            prompt.assert_not_called()
            self.assertEqual(page.textbook_step.currentData(), "prepare")

    def test_textbook_archive_confirmation_defaults_to_no_and_cancel_never_runs(self):
        window = self.open_app()
        window.show_workflow(get_workflow("textbook_brokers"))
        page = window.current_page
        page.textbook_step.setCurrentIndex(page.textbook_step.findData("archive"))
        with patch.object(page, "_confirm", return_value=True), patch.object(QMessageBox, "question", return_value=QMessageBox.StandardButton.No) as prompt, patch.object(window.executor, "run_async") as run:
            page._run()
        self.assertEqual(prompt.call_args.args[-1], QMessageBox.StandardButton.No)
        self.assertIn("completed TSPLOAD", prompt.call_args.args[2])
        run.assert_not_called()
        self.assertIsNone(page.result_queue)

    def test_textbook_archive_sends_confirmation_and_rechecks_access(self):
        window = self.open_app()
        window.show_workflow(get_workflow("textbook_brokers"))
        page = window.current_page
        page.inputs["term_code"].setText("202680")
        page.textbook_step.setCurrentIndex(page.textbook_step.findData("archive"))
        for authorized in (False, True):
            with patch.object(page, "_confirm", return_value=True), patch.object(page, "authorize", side_effect=[True, authorized]), patch.object(QMessageBox, "question", return_value=QMessageBox.StandardButton.Yes), patch.object(window.executor, "run_async", return_value=queue.Queue()) as run:
                page._run()
            if not authorized:
                run.assert_not_called()
            else:
                context = run.call_args.args[1]
                self.assertEqual(context.parameters["term_code"], "202680")
                self.assertIs(context.parameters["banner_upload_confirmed"], True)
                page.result_queue.put(WorkflowResult(True, "Archived", self.root / "uploaded.csv"))
                with patch.object(QMessageBox, "information") as prompt:
                    page._poll_result()
                prompt.assert_not_called()
        self.assertIsNone(page.result_queue)

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

    def start_synthetic_refund(self):
        window = self.open_app()
        window.show_workflow(get_workflow("refund_review"))
        page = window.current_page
        page.refund_source.setCurrentIndex(page.refund_source.findData("sql"))
        results = queue.Queue()
        self.assertTrue(page.cancel_button.isHidden())
        with patch.object(page, "_confirm", return_value=True), patch.object(window.executor, "run_async", return_value=results):
            page._run()
        return window, page, results

    def test_refund_cancel_returns_navigation_without_error_dialog(self):
        window, page, results = self.start_synthetic_refund()
        self.assertFalse(page.cancel_button.isHidden())
        self.assertFalse(page.back_button.isEnabled())
        with patch.object(window.executor, "cancel", return_value=True) as cancel:
            QTest.mouseClick(page.cancel_button, Qt.MouseButton.LeftButton)
        cancel.assert_called_once()
        self.assertFalse(page.cancel_button.isEnabled())
        self.assertIn("Cancelling", page.status_label.text())
        results.put(WorkflowResult(False, "Workflow cancelled. No output was published.", cancelled=True))
        with patch.object(QMessageBox, "warning") as warning:
            page._poll_result()
        warning.assert_not_called()
        self.assertFalse(window._busy)
        self.assertTrue(page.cancel_button.isHidden())
        self.assertTrue(page.back_button.isEnabled())
        self.assertTrue(page.form.isEnabled())
        self.assertTrue(page.output_button.isHidden())
        self.assertIn("Cancelled", page.status_label.text())
        window.show_home()
        self.assertIsNot(window.current_page, page)

    def test_refund_close_can_cancel_and_close_after_result(self):
        window, page, results = self.start_synthetic_refund()
        with patch.object(QMessageBox, "question", return_value=QMessageBox.StandardButton.Yes), patch.object(window.executor, "cancel", return_value=True) as cancel:
            self.assertFalse(window.close())
        cancel.assert_called_once()
        self.assertTrue(window._close_after_cancel)
        results.put(WorkflowResult(False, "Cancelled", cancelled=True))
        page._poll_result()
        self.qt.processEvents()
        self.assertFalse(window.isVisible())

    def test_refund_close_decline_leaves_run_active(self):
        window, page, results = self.start_synthetic_refund()
        with patch.object(QMessageBox, "question", return_value=QMessageBox.StandardButton.No), patch.object(window.executor, "cancel") as cancel:
            self.assertFalse(window.close())
        cancel.assert_not_called()
        self.assertFalse(window._close_after_cancel)
        self.assertTrue(window._busy)
        results.put(WorkflowResult(False, "Cancelled", cancelled=True))
        page._poll_result()

    def test_refund_close_when_run_finishes_during_confirmation(self):
        window, page, results = self.start_synthetic_refund()

        def finish_while_prompt_is_open(*args, **kwargs):
            results.put(WorkflowResult(True, "Done", self.root / "review.xlsx"))
            page._poll_result()
            return QMessageBox.StandardButton.Yes

        with patch.object(QMessageBox, "question", side_effect=finish_while_prompt_is_open), patch.object(window.executor, "cancel") as cancel:
            self.assertFalse(window.close())
        cancel.assert_not_called()
        self.qt.processEvents()
        self.assertFalse(window.isVisible())

    def test_shared_progress_tracks_any_workflow_and_stops_on_success(self):
        window = self.open_app()
        window.show_workflow(get_workflow("setup_report_watcher"))
        page = window.current_page
        results = queue.Queue()
        with patch.object(page, "_confirm", return_value=True), patch.object(window.executor, "run_async", return_value=results):
            page._run()
        self.assertFalse(page.progress.isHidden())
        self.assertEqual(page.progress.bar.maximum(), 0)
        with patch.object(WorkflowExecutor, "progress_snapshot", new_callable=PropertyMock, return_value=ProgressUpdate("Registering tasks", 2, 5)):
            page._poll_result()
        self.assertEqual(page.progress.bar.value(), 40)
        self.assertIn("2 of 5 completed", page.progress.stage_label.text())
        self.assertIn("Registering tasks", page.progress.stage_label.accessibleName())
        self.assertIn("2 of 5", page.progress.bar.accessibleDescription())
        self.assertEqual(page.progress.bar.focusPolicy(), Qt.FocusPolicy.StrongFocus)
        results.put(WorkflowResult(True, "Done"))
        page._poll_result()
        self.assertEqual(page.progress.bar.value(), 100)
        self.assertEqual(page.progress.stage_label.text(), "Completed")
        self.assertFalse(page.timer.isActive())

    def test_progress_elapsed_time_and_stop_do_not_claim_completion(self):
        widget = WorkflowProgressWidget()
        self.addCleanup(widget.close)
        with patch("app.gui.progress.monotonic", return_value=100):
            widget.start()
        with patch("app.gui.progress.monotonic", return_value=161):
            widget.refresh(ProgressUpdate("Reading accounts", 1, 4))
            self.assertEqual(widget.time_label.text(), "Elapsed: 01:01")
            widget.finish(success=False, cancelled=True)
        self.assertEqual(widget.bar.value(), 25)
        self.assertIn("Cancelled during: Reading accounts", widget.stage_label.text())
        with patch("app.gui.progress.monotonic", return_value=200):
            widget.start()
            widget.finish(success=False, cancelled=False)
        self.assertEqual(widget.bar.maximum(), 100)
        self.assertEqual(widget.bar.value(), 0)
        self.assertIn("Stopped", widget.stage_label.text())

    def test_updates_are_available_to_staff_and_restart_blocks_workflows(self):
        from app.gui.pages.updates import UpdatesPage
        from app.gui.services.updates import UpdatePlan

        window = self.open_app("STAFF")
        self.assertFalse(window.updates_button.isHidden())
        window.show_updates()
        page = window.current_page
        self.assertIsInstance(page, UpdatesPage)
        plan = UpdatePlan(self.root, "main", "origin", "refs/remotes/origin/main",
                          "a" * 40, "b" * 40, 1, True)
        page.result_queue = queue.Queue()
        page.result_queue.put((plan, None))
        page.installing = False
        window._set_busy(True)
        with patch.object(QMessageBox, "warning"):
            self.assertFalse(window.close())
        page._poll()
        self.assertTrue(page.install_button.isEnabled())
        self.assertIn("Setup must be run again", page.status.text())
        page.result_queue = queue.Queue()
        page.result_queue.put((plan, None))
        page.installing = True
        window._set_busy(True)
        page._poll()
        self.assertTrue(window._restart_required)
        self.assertFalse(window.home_button.isEnabled())
        self.assertFalse(window.updates_button.isEnabled())
        self.assertIn("run setup.ps1", page.status.text())
        window.show_home()
        window.show_connections()
        window.show_workflow(get_workflow("refund_review"))
        self.assertIs(window.current_page, page)
        self.assertTrue(window.close())

    def test_update_check_runs_in_worker_and_failures_allow_retry(self):
        from app.gui.services.updates import UpdateError

        window = self.open_app()
        window.show_updates()
        page = window.current_page
        with patch.object(page.updater, "check", side_effect=UpdateError("Synthetic network failure")):
            page._start(install=False)
            self.assertTrue(window._busy)
            self.assertFalse(window.updates_button.isEnabled())
            original = window.current_page
            window.show_home()
            self.assertIs(window.current_page, original)
            deadline = time.monotonic() + 3
            while page.result_queue is not None and time.monotonic() < deadline:
                self.qt.processEvents()
                time.sleep(0.01)
        self.assertIsNone(page.result_queue)
        self.assertFalse(window._busy)
        self.assertTrue(page.check_button.isEnabled())
        self.assertFalse(page.install_button.isEnabled())
        self.assertIn("Synthetic network failure", page.status.text())

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
