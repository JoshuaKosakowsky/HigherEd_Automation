"""Synthetic boundary and edit-preservation checks for long-running GUI forms."""

import logging
import os
import queue
import tempfile
import unittest
from datetime import date
from pathlib import Path
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QDate
from PySide6.QtWidgets import QApplication, QMessageBox

from app.gui.models import ParameterKind, WorkflowResult
from app.gui.pages.workflow_detail import WorkflowDetailPage
from app.gui.services.execution import WorkflowExecutor
from app.gui.workflow_registry import get_workflow


class WorkflowDefaultTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.qt = QApplication.instance() or QApplication([])

    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.executor = WorkflowExecutor(logging.getLogger("test-defaults"), self.root / "test.log")
        clock_patch = patch("app.gui.workflow_registry.date")
        self.clock = clock_patch.start()
        self.addCleanup(clock_patch.stop)
        self.clock.today.return_value = date(2026, 10, 31)

    def page(self, workflow_id):
        page = WorkflowDetailPage(None, get_workflow(workflow_id), self.executor,
                                  lambda: None, is_administrator=True)
        self.addCleanup(page.deleteLater)
        for parameter in page.definition.parameters:
            if parameter.required and parameter.kind in {
                ParameterKind.INPUT_FILE, ParameterKind.MULTI_INPUT_FILE,
            }:
                source = self.root / f"{parameter.key}.xlsx"
                source.touch()
                page.inputs[parameter.key].setText(str(source))
        if workflow_id == "canadian_tax":
            page.inputs["cwid"].setText("SYNTHETIC001")
        return page

    def review(self, page):
        with patch.object(page, "_confirm", return_value=False) as confirm:
            page._run()
        self.assertTrue(confirm.called, page.error.text())
        return confirm.call_args.args[0].parameters

    def test_reopening_forms_uses_current_term_month_fiscal_and_tax_year(self):
        # The registry stays imported throughout; only the workstation date changes.
        for today, term, month, first, last, fiscal in (
            (date(2026, 5, 15), "202610", "2026-04", "2026-04-01", "2026-04-30", 2025),
            (date(2026, 5, 16), "202655", "2026-04", "2026-04-01", "2026-04-30", 2025),
            (date(2026, 7, 1), "202655", "2026-06", "2026-06-01", "2026-06-30", 2026),
            (date(2026, 7, 16), "202680", "2026-06", "2026-06-01", "2026-06-30", 2026),
            (date(2027, 1, 1), "202710", "2026-12", "2026-12-01", "2026-12-31", 2026),
            (date(2028, 3, 1), "202810", "2028-02", "2028-02-01", "2028-02-29", 2027),
        ):
            with self.subTest(today=today):
                self.clock.today.return_value = today
                self.assertEqual(self.page("refund_review").inputs["target_term"].text(), term)
                self.assertEqual(self.page("textbook_brokers").inputs["term_code"].text(), term)
                recon = self.page("textbook_recon_manual")
                self.assertEqual(recon.inputs["recon_month"].text(), month)
                self.assertEqual(Path(recon.inputs["output_file"].text()).name, f"{month} TBB Recon.xlsx")
                graduate = self.page("graduate_contract_recon")
                self.assertEqual(graduate.inputs["start_date"].text(), first)
                self.assertEqual(graduate.inputs["end_date"].text(), last)
                trends = self.page("trends")
                self.assertEqual(trends.inputs["first_fiscal_year"].value(), fiscal)
                self.assertEqual(trends.inputs["last_fiscal_year"].value(), fiscal)
                self.assertEqual(self.page("canadian_tax").inputs["tax_year"].text(), str(today.year - 1))

    def test_open_forms_refresh_before_review_and_again_on_rerun(self):
        self.clock.today.return_value = date(2026, 6, 30)
        pages = {name: self.page(name) for name in (
            "refund_review", "textbook_recon_manual", "graduate_contract_recon", "trends", "canadian_tax",
        )}
        for today, term, month, first, last, fiscal in (
            (date(2026, 7, 16), "202680", "2026-06", "2026-06-01", "2026-06-30", 2026),
            (date(2027, 1, 1), "202710", "2026-12", "2026-12-01", "2026-12-31", 2026),
        ):
            with self.subTest(today=today):
                self.clock.today.return_value = today
                refund = self.review(pages["refund_review"])
                self.assertEqual(refund["target_term"], term)
                self.assertTrue(refund["output_file"].name.startswith(f"refund_review_{term}_"))
                recon = self.review(pages["textbook_recon_manual"])
                self.assertEqual(recon["recon_month"], month)
                self.assertEqual(recon["output_file"].name, f"{month} TBB Recon.xlsx")
                graduate_page = pages["graduate_contract_recon"]
                graduate_page.recon_source.setCurrentIndex(graduate_page.recon_source.findData("sql"))
                graduate = self.review(graduate_page)
                self.assertEqual(graduate["start_date"], first)
                self.assertEqual(graduate["end_date"], last)
                trends_page = pages["trends"]
                trends_page.recon_source.setCurrentIndex(trends_page.recon_source.findData("sql"))
                trends = self.review(trends_page)
                self.assertEqual(trends["first_fiscal_year"], fiscal)
                self.assertEqual(trends["last_fiscal_year"], fiscal)
                self.assertEqual(self.review(pages["canadian_tax"])["tax_year"], str(today.year - 1))

    def test_explicit_choices_remain_even_when_restored_to_original_defaults(self):
        refund = self.page("refund_review")
        original_term = refund.inputs["target_term"].text()
        refund.inputs["target_term"].setText("202610")
        refund.inputs["target_term"].setText(original_term)
        recon = self.page("textbook_recon_manual")
        original_month = recon.inputs["recon_month"].text()
        recon.inputs["recon_month"].setText("2020-01")
        recon.inputs["recon_month"].setText(original_month)
        original_output = recon.inputs["output_file"].text()
        recon.inputs["output_file"].setText(str(self.root / "chosen.xlsx"))
        recon.inputs["output_file"].setText(original_output)
        graduate = self.page("graduate_contract_recon")
        graduate.recon_source.setCurrentIndex(graduate.recon_source.findData("sql"))
        original_date = graduate.inputs["start_date"].date()
        graduate.inputs["start_date"].setDate(QDate(2020, 1, 1))
        graduate.inputs["start_date"].setDate(original_date)
        trends = self.page("trends")
        trends.recon_source.setCurrentIndex(trends.recon_source.findData("sql"))
        original_year = trends.inputs["first_fiscal_year"].value()
        trends.inputs["first_fiscal_year"].setValue(2020)
        trends.inputs["first_fiscal_year"].setValue(original_year)
        self.clock.today.return_value = date(2027, 8, 1)
        self.assertEqual(self.review(refund)["target_term"], original_term)
        result = self.review(recon)
        self.assertEqual(result["recon_month"], original_month)
        self.assertEqual(str(result["output_file"]), original_output)
        self.assertEqual(self.review(graduate)["start_date"], original_date.toString("yyyy-MM-dd"))
        self.assertEqual(self.review(trends)["first_fiscal_year"], original_year)

    def test_returning_to_visible_form_refreshes_defaults_but_not_an_active_run(self):
        page = self.page("textbook_brokers")
        page.show()
        page.hide()
        self.clock.today.return_value = date(2027, 1, 1)
        page.show()
        self.assertEqual(page.inputs["term_code"].text(), "202710")
        page.hide()
        page.result_queue = queue.Queue()
        self.clock.today.return_value = date(2027, 8, 1)
        page.show()
        self.assertEqual(page.inputs["term_code"].text(), "202710")
        page.result_queue = None
        page.close()

    def test_archive_retains_prepared_term_after_term_boundary(self):
        self.clock.today.return_value = date(2026, 7, 15)
        page = self.page("textbook_brokers")
        results = queue.Queue()
        with patch.object(page, "_confirm", return_value=True), \
             patch.object(self.executor, "run_async", return_value=results):
            page._run()
        results.put(WorkflowResult(True, "Prepared", self.root / "TSPLOAD.csv"))
        with patch.object(QMessageBox, "information"):
            page._poll_result()
        self.clock.today.return_value = date(2026, 7, 16)
        parameters = self.review(page)
        self.assertEqual(parameters["step"], "archive")
        self.assertEqual(parameters["term_code"], "202655")


if __name__ == "__main__":
    unittest.main()
