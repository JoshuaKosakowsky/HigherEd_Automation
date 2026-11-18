"""Headless GUI review shows the actual opening balances before any write."""

import logging
import os
import tempfile
import unittest
from datetime import date
from pathlib import Path
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication, QDialog, QLabel

from app.gui.models import WorkflowContext
from app.gui.pages.workflow_detail import WorkflowDetailPage
from app.gui.services.csmf_loans import run_csmf_loans
from app.gui.services.execution import WorkflowExecutor
from app.gui.workflow_registry import get_workflow
from data_processing.csmf_loans.balances import BalanceStore, prepare_opening_balances
from data_processing.csmf_loans.sources import LOANS
from shared.mines_paths import MinesPathError, get_shared_csmf_balances_directory
from test_csmf_loans import JOURNAL_HEADERS, JULY, journal_row, write_csv


class CsmfGuiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.qt = QApplication.instance() or QApplication([])

    def setUp(self):
        temporary = tempfile.TemporaryDirectory(); self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name); self.cache = self.root / "shared"
        self.journal = self.root / "journal.csv"; self.trial = self.root / "trial.csv"
        write_csv(self.journal, JOURNAL_HEADERS, [journal_row()])
        write_csv(self.trial, ["Worktags", "Debit Amount"],
                  [[f"Fund: 32 <br> Project: {project} Loan", 1000] for project in LOANS])
        patched = patch("data_processing.csmf_loans.balances.get_shared_csmf_balances_directory", return_value=self.cache)
        patched.start(); self.addCleanup(patched.stop)
        self.executor = WorkflowExecutor(logging.getLogger("csmf-test"), self.root / "gui.log")
        self.page = WorkflowDetailPage(None, get_workflow("csmf_loans"), self.executor, lambda: None)
        self.addCleanup(self.page.deleteLater)
        self.page.inputs["fiscal_year"].setValue(2027)
        self.page.inputs["journal_file"].setText(str(self.journal))
        self.page.inputs["output_file"].setText(str(self.root / "output.xlsx"))

    def cached(self):
        selection = prepare_opening_balances(2027, self.trial, now=JULY)
        store = BalanceStore(2027)
        with store.locked(None):
            store.save_locked(selection.balances)
        return store

    def test_first_fy_review_requires_trial_and_does_not_run(self):
        with patch.object(self.page, "_confirm") as confirm, patch.object(self.executor, "run_async") as run:
            self.page._run()
        confirm.assert_not_called(); run.assert_not_called()
        self.assertIn("Upload Trial Balance", self.page.error.text())

    def test_first_upload_is_previewed_without_saving_on_cancel(self):
        self.page.inputs["trial_balance_file"].setText(str(self.trial))
        with patch.object(self.page, "_confirm", return_value=False) as confirm, patch.object(self.executor, "run_async") as run:
            self.page._run()
        selection = confirm.call_args.args[0].parameters["_opening_balances"]
        self.assertEqual(len(selection.balances.values), 7)
        self.assertFalse(self.cache.exists()); run.assert_not_called()

    def test_saved_july_values_are_shown_when_reviewing_later(self):
        store = self.cached(); previous = store.path.read_bytes()
        with patch.object(self.page, "_confirm", return_value=False) as confirm:
            self.page._run()
        selection = confirm.call_args.args[0].parameters["_opening_balances"]
        self.assertIn("2026-07-10", selection.balances.updated_at)
        self.assertIsNone(selection.trial_path)
        self.assertEqual(store.path.read_bytes(), previous)

    def test_review_dialog_contains_all_values_and_saved_timestamp(self):
        self.cached()
        selection = prepare_opening_balances(2027)
        captured = []

        def reject(dialog):
            captured.extend(label.text() for label in dialog.findChildren(QLabel))
            return QDialog.DialogCode.Rejected

        with patch("app.gui.pages.workflow_detail.QDialog.exec", reject):
            self.assertFalse(self.page._confirm(WorkflowContext("csmf_loans", {"_opening_balances": selection})))
        text = "\n".join(captured)
        self.assertIn("Last uploaded/updated: 2026-07-10", text)
        for project in LOANS:
            self.assertIn(project, text)
        self.assertEqual(text.count("$1,000.00"), 7)

    def test_changing_fy_does_not_reuse_another_years_balances(self):
        self.cached(); self.page.inputs["fiscal_year"].setValue(2028)
        with patch.object(self.page, "_confirm") as confirm:
            self.page._run()
        confirm.assert_not_called()
        self.assertIn("FY2028", self.page.error.text())

    def test_shared_path_errors_stay_in_form_and_do_not_start_run(self):
        with patch("app.gui.pages.workflow_detail.prepare_opening_balances", side_effect=MinesPathError("Shared location unavailable")), patch.object(self.page, "_confirm") as confirm:
            self.page._run()
        confirm.assert_not_called()
        self.assertIn("Shared location unavailable", self.page.error.text())

    def test_damaged_trial_workbook_shows_error_without_opening_review(self):
        damaged = self.root / "damaged.xlsx"
        damaged.write_bytes(b"not an Excel archive")
        self.page.inputs["trial_balance_file"].setText(str(damaged))
        with patch.object(self.page, "_confirm") as confirm, patch.object(self.executor, "run_async") as run:
            self.page._run()
        confirm.assert_not_called(); run.assert_not_called()
        self.assertIn("Trial Balance could not be read", self.page.error.text())
        self.assertFalse(self.cache.exists())

    def test_registry_and_shared_storage_use_existing_environment_paths(self):
        definition = get_workflow("csmf_loans")
        self.assertEqual(definition.supported_modes, ())
        self.assertTrue(definition.cancellable)
        self.assertIs(definition.runner, run_csmf_loans)
        self.assertFalse(next(p for p in definition.parameters if p.key == "trial_balance_file").required)
        path = get_shared_csmf_balances_directory({"OneDriveCommercial": "C:/Synthetic/Institution"})
        self.assertEqual(path.name, "csmf_opening_balances")
        self.assertIn(Path("C:/Synthetic/Institution"), path.parents)

    def test_july_default_targets_previous_months_fy(self):
        definition = get_workflow("csmf_loans")
        factory = next(p for p in definition.parameters if p.key == "fiscal_year").default_factory
        with patch("app.gui.workflow_registry.date") as clock:
            clock.today.return_value = date(2027, 7, 10)
            self.assertEqual(factory(), 2027)
            clock.today.return_value = date(2027, 8, 10)
            self.assertEqual(factory(), 2028)


if __name__ == "__main__":
    unittest.main()
