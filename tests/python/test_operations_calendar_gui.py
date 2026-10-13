"""Headless calendar interaction tests with synthetic local staff and dates."""

from __future__ import annotations

import json
import os
import sys
import tempfile
import unittest
from dataclasses import replace
from datetime import date
from pathlib import Path
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication, QDialog, QInputDialog, QMessageBox

from app.gui.main import AutomationApplication
from app.gui.pages.operations_calendar import (
    CoverageDialog, EventDialog, OccurrenceDialog, OperationsCalendarPage,
)
from app.gui.services.operations_calendar import (
    Audience, CalendarData, CalendarEvent, CalendarStore, Coverage, DateOverride, RolePerson,
    occurrences, replace_override,
)
from app.gui.theme import apply_theme
from test_operations_calendar import synthetic_access_payload


class CalendarGuiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.qt = QApplication.instance() or QApplication([])
        apply_theme(cls.qt)

    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.access_path = self.root / "gui_access.json"
        self.policy = synthetic_access_payload()
        self.write_policy()
        self.store = CalendarStore(self.access_path, "ADMIN")
        self.errors = []
        previous = sys.excepthook
        sys.excepthook = lambda *args: self.errors.append(args)
        self.addCleanup(setattr, sys, "excepthook", previous)
        self.widgets = []

    def tearDown(self):
        for widget in reversed(self.widgets):
            widget.close()
            widget.deleteLater()
        self.qt.processEvents()
        self.assertEqual(self.errors, [], "An exception escaped a Qt callback or paint event")

    def write_policy(self):
        self.access_path.write_text(json.dumps(self.policy), encoding="utf-8")

    def keep(self, widget):
        self.widgets.append(widget)
        return widget

    def synthetic_calendar(self):
        audience = Audience(False, ("cashier",))
        return CalendarData(
            events=(CalendarEvent(
                "deadline", "Semester payment deadline", "Tuition", date(2026, 9, 12),
                recurrence="annual", audience=Audience(),
                coverage=(Coverage("email", "Extra email coverage", -21, 7, audience),
                          Coverage("counter", "Dual counter coverage", -14, 0, audience)),
            ), CalendarEvent("billing", "Monthly billing", "Billing", date(2026, 1, 12),
                             recurrence="monthly", tags=("Late Fees", "Holds"), audience=audience)),
        )

    def page(self):
        page = self.keep(OperationsCalendarPage(None, self.store))
        page.resize(1100, 850)
        page.show()
        page.year.setValue(2026)
        self.qt.processEvents()
        return page

    def test_admin_navigation_and_home_reminder(self):
        self.store.save(self.synthetic_calendar())
        window = self.keep(AutomationApplication(user_login_override="ADMIN", access_config_path=self.access_path))
        window.show()
        self.qt.processEvents()
        self.assertFalse(window.calendar_button.isHidden())
        self.assertIn("Bursar Office Calendar", window.current_page.calendar_reminder.text())
        window.show_operations_calendar()
        self.qt.processEvents()
        self.assertIsInstance(window.current_page, OperationsCalendarPage)
        self.assertTrue(window.calendar_button.isChecked())
        window.show_access_management()
        self.assertFalse(window.calendar_button.isChecked())
        self.assertFalse(hasattr(window.current_page, "calendar_positions_button"))
        window._set_busy(True)
        self.assertFalse(window.calendar_button.isEnabled())
        original = window.current_page
        window.show_operations_calendar()
        self.assertIs(window.current_page, original)
        window._set_busy(False)

    def test_non_admin_cannot_open_calendar_or_see_home_reminders(self):
        window = self.keep(AutomationApplication(user_login_override="STAFF", access_config_path=self.access_path))
        self.assertTrue(window.calendar_button.isHidden())
        self.assertFalse(hasattr(window.current_page, "calendar_reminder"))
        window.show_operations_calendar()
        self.assertNotIsInstance(window.current_page, OperationsCalendarPage)
        self.assertFalse(self.store.path.exists())

    def test_timeline_paints_and_filters_deadlines_and_coverage(self):
        self.store.save(self.synthetic_calendar())
        page = self.page()
        self.assertEqual(page.table.rowCount(), 15)
        image = page.grab()
        self.assertFalse(image.isNull())
        page.category.setCurrentIndex(page.category.findData("Tuition"))
        self.assertEqual(page.table.rowCount(), 3)
        page.search.setText("Dual counter")
        self.assertEqual(page.table.rowCount(), 1)
        self.assertTrue(page.rows[0].coverage)
        self.assertEqual(page.table.item(0, 1).text(), "Cashier")
        page.table.selectRow(0)
        self.assertTrue(page.review_button.isEnabled())
        self.assertEqual(page._selected().event.id, "deadline")
        page.grab()

    def test_three_month_view_spans_year_boundary(self):
        self.store.save(self.synthetic_calendar())
        page = self.page()
        page.period.setCurrentIndex(page.period.findData(11))
        self.assertEqual(page.delegate.start, date(2026, 11, 1))
        self.assertEqual(page.delegate.end, date(2027, 1, 31))
        self.assertEqual(page.table.rowCount(), 3)
        self.assertEqual(page.period.currentText(), "Nov–Jan (3 months)")
        page.grab()

    def test_category_and_affected_role_are_saved_on_the_item(self):
        page = self.page()
        dialog = self.keep(EventDialog(None, page.data, self.store.access()))
        dialog.title.setText("Recurring refund preparation")
        with patch.object(QInputDialog, "getText", return_value=("Refunds", True)):
            dialog.new_category_button.click()
        dialog.audience.everyone.setChecked(False)
        for index in range(dialog.audience.choices.topLevelItemCount()):
            item = dialog.audience.choices.topLevelItem(index)
            item.setCheckState(0, Qt.CheckState.Checked if item.data(0, Qt.ItemDataRole.UserRole) == "cashier"
                               else Qt.CheckState.Unchecked)
        dialog._save()
        self.assertEqual(dialog.result_event.audience, Audience(False, ("cashier",)))
        self.assertTrue(page._save(replace(page.data, events=(dialog.result_event,))))
        self.assertGreaterEqual(page.category.findData("Refunds"), 0)
        reopened = self.keep(EventDialog(None, self.store.load(), self.store.access()))
        self.assertGreaterEqual(reopened.category.findText("Refunds"), 0)
        self.assertNotIn("positions", json.loads(self.store.path.read_text()))

    def test_role_filters_include_everyone(self):
        self.store.save(self.synthetic_calendar())
        page = self.page()
        page.role.setCurrentIndex(page.role.findData(json.dumps(["cashier", None])))
        self.assertEqual(page.table.rowCount(), 15)
        page.role.setCurrentIndex(page.role.findData(json.dumps(["administrator", None])))
        self.assertEqual(page.table.rowCount(), 1)

    def test_role_tree_selects_whole_group_or_people_beneath_it(self):
        dialog = self.keep(EventDialog(None, CalendarData(), self.store.access()))
        audience = dialog.audience
        audience.everyone.setChecked(False)
        roles = {audience.choices.topLevelItem(i).data(0, Qt.ItemDataRole.UserRole):
                 audience.choices.topLevelItem(i) for i in range(audience.choices.topLevelItemCount())}
        role = roles["cashier"]
        self.assertEqual(role.childCount(), 2)
        role.setCheckState(0, Qt.CheckState.Checked)
        self.assertEqual(audience.value(), Audience(False, ("cashier",)))
        child = next(role.child(i) for i in range(role.childCount())
                     if role.child(i).data(0, Qt.ItemDataRole.UserRole) == "staff")
        child.setCheckState(0, Qt.CheckState.Checked)
        self.assertEqual(audience.value(), Audience(False, people=(RolePerson("cashier", "staff"),)))
        role.setCheckState(0, Qt.CheckState.Checked)
        self.assertEqual(child.checkState(0), Qt.CheckState.Unchecked)
        self.assertEqual(audience.value(), Audience(False, ("cashier",)))

    def test_person_filter_includes_everyone_and_whole_role_but_excludes_other_people(self):
        data = self.synthetic_calendar()
        individual = replace(data.events[1], id="personal", title="Specific person's reminder",
                             audience=Audience(False, people=(RolePerson("cashier", "staff"),)))
        self.store.save(replace(data, events=(*data.events, individual)))
        page = self.page()
        page.role.setCurrentIndex(page.role.findData(json.dumps(["cashier", "staff"])))
        self.assertEqual(page.table.rowCount(), 27)
        page.role.setCurrentIndex(page.role.findData(json.dumps(["cashier", "new"])))
        self.assertEqual(page.table.rowCount(), 15)
        self.assertFalse(any(row.occurrence.event.id == "personal" for row in page.rows))

    def test_unassigned_person_remains_in_picker_for_reassignment(self):
        person = RolePerson("cashier", "staff")
        self.policy["users"]["STAFF"]["active"] = False
        self.write_policy()
        event = replace(self.synthetic_calendar().events[0], audience=Audience(False, people=(person,)))
        dialog = self.keep(EventDialog(None, CalendarData(events=(event,)), self.store.access(), event))
        self.assertEqual(dialog.audience.value(), event.audience)
        role = next(dialog.audience.choices.topLevelItem(i)
                    for i in range(dialog.audience.choices.topLevelItemCount())
                    if dialog.audience.choices.topLevelItem(i).data(0, Qt.ItemDataRole.UserRole) == "cashier")
        selected = next(role.child(i) for i in range(role.childCount())
                        if role.child(i).data(0, Qt.ItemDataRole.UserRole) == "staff")
        self.assertIn("unassigned", selected.text(0))

    def test_role_vacancy_and_replacement_follow_staff_access(self):
        saved = self.store.save(self.synthetic_calendar())
        self.policy["users"]["STAFF"]["active"] = False
        self.policy["users"]["NEW"]["active"] = False
        self.write_policy()
        page = self.page()
        self.assertIn("1 unassigned", page.summary.text())
        self.assertIn("no active staff", page.table.item(1, 1).text())
        self.policy["users"]["NEW"]["active"] = True
        self.write_policy()
        page._reload()
        self.assertIn("0 unassigned", page.summary.text())
        self.assertEqual(page.table.item(1, 1).text(), "Cashier")
        self.assertEqual(self.store.load().events, saved.events)

    def test_event_dialog_validates_and_adds_monthly_subset_with_details(self):
        data = self.synthetic_calendar()
        dialog = self.keep(EventDialog(None, data, self.store.access()))
        dialog._save()
        self.assertIn("title", dialog.error.text())
        dialog.title.setText("Billing with holds")
        dialog.category.setCurrentText("Billing")
        dialog.recurrence.setCurrentIndex(dialog.recurrence.findData("monthly"))
        dialog.anchor.setDate(dialog.anchor.date().fromString("2026-01-12", "yyyy-MM-dd"))
        for index, check in enumerate(dialog.months):
            check.setChecked(index + 1 in (2, 4, 8))
        dialog.tags.setText("Late Fees, Holds")
        dialog._save()
        self.assertEqual(dialog.result(), QDialog.DialogCode.Accepted)
        self.assertEqual(dialog.result_event.months, (2, 4, 8))
        self.assertEqual(dialog.result_event.tags, ("Late Fees", "Holds"))
        self.store.save(replace(data, events=(dialog.result_event,)))

    def test_coverage_dialog_rejects_reversed_period(self):
        dialog = self.keep(CoverageDialog(None, self.store.access()))
        dialog.title.setText("Dual counter coverage")
        dialog.start.setValue(10)
        dialog.end.setValue(-10)
        dialog._save()
        self.assertIsNone(dialog.result_coverage)
        dialog.start.setValue(-14)
        dialog.end.setValue(0)
        dialog._save()
        self.assertEqual(dialog.result_coverage.start_offset, -14)

    def test_date_review_moves_coverage_without_changing_future_dates(self):
        saved = self.store.save(self.synthetic_calendar())
        occurrence = next(o for o in occurrences(saved, date(2026, 9, 1), date(2026, 9, 30)) if o.event.id == "deadline")
        dialog = self.keep(OccurrenceDialog(None, occurrence))
        self.assertFalse(dialog.approved.isChecked())
        dialog.approved.setChecked(True)
        dialog.actual.setDate(dialog.actual.date().addDays(2))
        self.assertFalse(dialog.approved.isChecked())
        dialog.approved.setChecked(True)
        dialog._save()
        self.store.save(replace_override(saved, dialog.result_override))
        page = self.page()
        actual = next(row for row in page.rows if row.occurrence.event.id == "deadline" and row.coverage)
        self.assertEqual(actual.start, date(2026, 8, 26))
        self.assertTrue(actual.occurrence.approved)

    def test_stale_page_save_reports_conflict_without_overwriting(self):
        saved = self.store.save(self.synthetic_calendar())
        page = self.page()
        self.store.save(replace(saved, events=(replace(saved.events[0], notes="Changed by another admin"), *saved.events[1:])))
        with patch.object(QMessageBox, "warning") as warning:
            self.assertFalse(page._save(page.data))
        self.assertIn("Another administrator", warning.call_args.args[2])
        self.assertEqual(self.store.load().events[0].notes, "Changed by another admin")

    def test_revocation_blocks_save_and_reload_clears_calendar(self):
        self.store.save(self.synthetic_calendar())
        page = self.page()
        self.policy["users"]["SECOND"] = dict(self.policy["users"]["ADMIN"])
        self.policy["users"]["ADMIN"]["active"] = False
        self.write_policy()
        with patch.object(QMessageBox, "warning"):
            self.assertFalse(page._save(page.data))
        page._reload()
        self.assertEqual(page.table.rowCount(), 0)
        self.assertFalse(page.add_button.isEnabled())


if __name__ == "__main__":
    unittest.main()
