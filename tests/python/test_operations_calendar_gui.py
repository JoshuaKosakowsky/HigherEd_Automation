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

from PySide6.QtCore import QPoint, Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QDialog, QInputDialog, QMessageBox

from app.gui.main import AutomationApplication
from app.gui.pages.operations_calendar import (
    CoverageDialog, EventDialog, GroupsDialog, OccurrenceDialog, OperationsCalendarPage,
    SEMESTER_COLORS, timeline_marks,
)
from app.gui.services.operations_calendar import (
    Audience, CalendarData, CalendarEvent, CalendarGroup, CalendarStore, Coverage, DateOverride, RolePerson,
    occurrences, replace_override, assign_group, timeline_rows,
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
        self.assertTrue(page.review_action.isEnabled())
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

    def test_laptop_layout_reserves_space_for_timeline_and_keeps_panels_available(self):
        self.store.save(self.synthetic_calendar())
        window = self.keep(AutomationApplication(user_login_override="ADMIN", access_config_path=self.access_path))
        window.resize(1000, 700)
        window.show()
        window.show_operations_calendar()
        self.qt.processEvents()
        page = window.current_page
        self.assertEqual(window.size().width(), 1000)
        self.assertGreater(page.table.height(), 400)
        self.assertGreater(page.table.columnWidth(2), page.table.viewport().width() * .5)
        self.assertFalse(page.options_panel.isVisible())
        self.assertFalse(page.attention.isVisible())
        page.options_button.click()
        self.qt.processEvents()
        self.assertTrue(page.options_panel.isVisible())
        self.assertTrue(page.actions_button.isVisible())
        self.assertGreaterEqual(page.search.x(), page.role.geometry().right())
        page.options_button.click()
        page.reminders_button.click()
        self.qt.processEvents()
        self.assertTrue(page.attention.isVisible())
        self.assertGreater(page.attention.rowCount(), 0)
        self.assertGreater(page.table.height(), 250)

    def test_resizing_and_hidden_filters_preserve_calendar(self):
        self.store.save(self.synthetic_calendar())
        page = self.page()
        before = self.store.path.read_bytes()
        rows = list(page.rows)
        width = page.table.columnWidth(2)
        page.resize(850, 700)
        self.qt.processEvents()
        self.assertLess(page.table.columnWidth(2), width)
        self.assertEqual(page.rows, rows)
        page.search.setText("Dual counter")
        self.assertEqual(page.options_button.text(), "Filters (1)")
        self.assertEqual(len(page.rows), 1)
        page.search.clear()
        self.assertEqual(page.options_button.text(), "Filters")
        self.assertEqual(self.store.path.read_bytes(), before)
        page.grab()

    def test_filter_panel_counts_clears_and_keeps_date_range_and_saved_calendar(self):
        self.store.save(self.synthetic_calendar())
        page = self.page()
        saved = self.store.path.read_bytes()
        page.period.setCurrentIndex(page.period.findData(9))
        page.options_button.click()
        self.qt.processEvents()
        self.assertEqual(page.options_button.arrowType(), Qt.ArrowType.DownArrow)
        self.assertTrue(page.search.hasFocus())
        self.assertFalse(page.clear_filters_button.isEnabled())
        page.category.setCurrentIndex(page.category.findData("Tuition"))
        page.semester.setCurrentIndex(page.semester.findData(None))
        page.role.setCurrentIndex(page.role.findData(json.dumps(["cashier", None])))
        page.search.setText("Dual counter")
        self.assertEqual(page.options_button.text(), "Filters (4)")
        self.assertTrue(page.clear_filters_button.isEnabled())
        self.assertEqual(len(page.rows), 1)
        page.options_button.click()
        self.assertEqual(page.options_button.arrowType(), Qt.ArrowType.RightArrow)
        self.assertEqual(page.options_button.text(), "Filters (4)")
        page.options_button.click()
        page.clear_filters_button.click()
        self.assertEqual(page.options_button.text(), "Filters")
        self.assertFalse(page.clear_filters_button.isEnabled())
        self.assertEqual(page.year.value(), 2026)
        self.assertEqual(page.period.currentData(), 9)
        self.assertEqual(len(page.rows), 6)
        self.assertEqual(self.store.path.read_bytes(), saved)

    def test_calendar_actions_are_available_without_opening_filters(self):
        self.store.save(self.synthetic_calendar())
        page = self.page()
        self.assertFalse(page.options_panel.isVisible())
        self.assertFalse(page.review_action.isEnabled())
        self.assertTrue(page.remove_action.isEnabled())
        self.assertTrue(page.add_action.isEnabled())
        page.table.selectRow(0)
        self.assertTrue(page.review_action.isEnabled())
        self.assertTrue(page.series_action.isEnabled())
        self.assertTrue(page.remove_action.isEnabled())
        with patch("app.gui.pages.operations_calendar.EventDialog") as dialog:
            dialog.return_value.exec.return_value = QDialog.DialogCode.Rejected
            page.add_action.trigger()
            dialog.assert_called_once_with(page, page.data, page.access)
        self.assertFalse(page.options_panel.isVisible())

    def click_remove_menu_item(self, page):
        QTest.mouseClick(page.actions_button, Qt.MouseButton.LeftButton)
        self.qt.processEvents()
        self.assertTrue(page.actions_menu.isVisible())
        self.assertTrue(page.remove_action.isEnabled())
        QTest.mouseClick(page.actions_menu, Qt.MouseButton.LeftButton,
                         pos=page.actions_menu.actionGeometry(page.remove_action).center())
        self.qt.processEvents()

    def test_remove_menu_explains_missing_individual_selection_without_changing_data(self):
        self.store.save(self.grouped_data())
        page = self.page()
        before = self.store.path.read_bytes()
        for group_selected in (False, True):
            with self.subTest(group_selected=group_selected):
                if group_selected:
                    page.table.selectRow(next(i for i, row in enumerate(page.display_rows)
                                              if isinstance(row, CalendarGroup)))
                with patch.object(QMessageBox, "information") as information, \
                        patch.object(QInputDialog, "getItem") as scope:
                    self.click_remove_menu_item(page)
                self.assertIn("Select an individual event", information.call_args.args[2])
                scope.assert_not_called()
                self.assertEqual(self.store.path.read_bytes(), before)

    def test_remove_menu_hides_only_selected_occurrence(self):
        self.store.save(self.synthetic_calendar())
        page = self.page()
        row = next(i for i, row in enumerate(page.display_rows) if row.occurrence.event.id == "billing")
        page.table.selectRow(row)
        selected = page._selected()
        with patch.object(QInputDialog, "getItem", return_value=("Only this occurrence", True)), \
                patch.object(QMessageBox, "question", return_value=QMessageBox.StandardButton.Yes):
            self.click_remove_menu_item(page)
        saved = self.store.load()
        self.assertEqual(len(saved.events), 2)
        self.assertEqual(len(saved.overrides), 1)
        self.assertTrue(saved.overrides[0].hidden)
        self.assertEqual(saved.overrides[0].event_id, selected.event.id)
        self.assertEqual(saved.overrides[0].nominal, selected.nominal)
        self.assertEqual(len(page.rows), 14)

    def test_remove_menu_deletes_selected_schedule_and_linked_coverage(self):
        self.store.save(self.grouped_data())
        page = self.page()
        row = next(i for i, row in enumerate(page.display_rows)
                   if not isinstance(row, CalendarGroup) and row.occurrence.event.id == "deadline")
        page.table.selectRow(row)
        with patch.object(QInputDialog, "getItem", return_value=("Entire schedule and linked coverage", True)), \
                patch.object(QMessageBox, "question", return_value=QMessageBox.StandardButton.Yes):
            self.click_remove_menu_item(page)
        saved = self.store.load()
        self.assertEqual([event.id for event in saved.events], ["billing"])
        self.assertEqual(saved.groups[0].id, "fall")
        self.assertFalse(any(row.occurrence.event.id == "deadline" for row in page.rows))

    def test_remove_menu_cancellation_preserves_saved_calendar(self):
        self.store.save(self.synthetic_calendar())
        page = self.page()
        page.table.selectRow(0)
        before = self.store.path.read_bytes()
        for accept_scope in (False, True):
            with self.subTest(accept_scope=accept_scope):
                with patch.object(QInputDialog, "getItem", return_value=("Only this occurrence", accept_scope)), \
                        patch.object(QMessageBox, "question", return_value=QMessageBox.StandardButton.No) as confirm:
                    self.click_remove_menu_item(page)
                self.assertEqual(confirm.call_count, int(accept_scope))
                self.assertEqual(self.store.path.read_bytes(), before)

    def test_toolbar_wraps_at_large_zoom_without_clipping_filter_or_action_buttons(self):
        self.addCleanup(apply_theme, self.qt)
        window = self.keep(AutomationApplication(user_login_override="ADMIN", access_config_path=self.access_path))
        window.resize(900, 640)
        window.show()
        window.show_operations_calendar()
        window._apply_zoom(150)
        self.qt.processEvents()
        page = window.current_page
        self.assertEqual(page._toolbar_columns, 2)
        for control in (page.options_button, page.actions_button):
            self.assertGreaterEqual(control.width(), control.minimumSizeHint().width())
        self.assertGreater(page.options_button.y(), page.year.y())
        # Exercise wider text metrics without depending on a Windows font being
        # installed locally. A single column must fit before the window grows.
        original_text = page.actions_button.text()
        page.actions_button.setText("Calendar actions: edit and remove")
        page._layout_toolbar()
        self.qt.processEvents()
        self.assertEqual(page._toolbar_columns, 1)
        self.assertEqual(window.width(), 900)
        self.assertGreaterEqual(page.actions_button.width(), page.actions_button.minimumSizeHint().width())
        page.actions_button.setText(original_text)
        page._layout_toolbar()
        self.qt.processEvents()
        self.assertEqual(page._toolbar_columns, 2)
        for control in (page.options_button, page.actions_button):
            self.assertGreaterEqual(control.width(), control.minimumSizeHint().width())
        window._apply_zoom(100)
        self.qt.processEvents()
        self.assertEqual(page._toolbar_columns, 4)

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
        self.assertFalse(page.add_action.isEnabled())
        self.assertFalse(page.remove_action.isEnabled())

    def grouped_data(self):
        data = self.synthetic_calendar()
        return assign_group(replace(data, groups=(CalendarGroup("fall", "Fall Payment Deadline"),)),
                            "fall", frozenset(e.id for e in data.events))

    def test_group_heading_collapses_without_hiding_reminders(self):
        self.store.save(self.grouped_data())
        page = self.page()
        self.assertEqual(page.table.rowCount(), 16)
        self.assertIsInstance(page.display_rows[0], CalendarGroup)
        reminder_count = page.attention.rowCount()
        page.table.selectRow(0)
        self.assertIsNone(page._selected())
        self.assertFalse(page.review_action.isEnabled())
        control = page.group_buttons["fall"]
        self.assertGreaterEqual(control.height(), 44)
        QTest.mouseClick(control, Qt.MouseButton.LeftButton,
                         pos=QPoint(control.width() - 10, control.height() // 2))
        self.assertEqual(sum(not page.table.isRowHidden(i) for i in range(page.table.rowCount())), 1)
        self.assertEqual(page.attention.rowCount(), reminder_count)
        self.assertIs(page.group_buttons["fall"], control)
        QTest.mouseClick(control, Qt.MouseButton.LeftButton)
        self.assertEqual(sum(not page.table.isRowHidden(i) for i in range(page.table.rowCount())), 16)
        self.assertEqual(page.table.rowCount(), 16)
        page.table.selectRow(1)
        self.assertIsNotNone(page._selected())
        page.grab()

    def test_group_control_handles_repeated_clicks_and_keyboard_without_rebuilding(self):
        saved = self.store.save(self.grouped_data())
        page = self.page()
        control = page.group_buttons["fall"]
        for index in range(8):
            QTest.mouseClick(control, Qt.MouseButton.LeftButton)
            self.assertEqual("fall" in page.collapsed_groups, index % 2 == 0)
            self.assertIs(page.group_buttons["fall"], control)
        control.setFocus()
        QTest.keyClick(control, Qt.Key.Key_Space)
        self.assertIn("fall", page.collapsed_groups)
        self.assertIn("Expand", control.accessibleName())
        QTest.keyClick(control, Qt.Key.Key_Space)
        self.assertNotIn("fall", page.collapsed_groups)
        self.assertIn("Collapse", control.accessibleName())
        self.assertEqual(self.store.load(), saved)

    def test_scrolled_group_button_stays_visible_after_toggle(self):
        data = self.synthetic_calendar()
        data = assign_group(replace(data, groups=(CalendarGroup("fall", "Fall Payment Deadline"),)),
                            "fall", frozenset({"deadline"}))
        self.store.save(data)
        page = self.page()
        index = next(i for i, row in enumerate(page.display_rows) if isinstance(row, CalendarGroup))
        page.table.scrollToItem(page.table.item(index, 0))
        self.qt.processEvents()
        control = page.group_buttons["fall"]
        for _ in range(4):
            self.assertFalse(control.visibleRegion().isEmpty())
            visible = control.visibleRegion().boundingRect()
            QTest.mouseClick(control, Qt.MouseButton.LeftButton, pos=visible.center())
            self.qt.processEvents()
            self.assertFalse(control.visibleRegion().isEmpty())
            self.assertEqual(page.table.currentRow(), index)

    def test_collapsed_group_survives_filter_rebuild_with_no_stale_buttons(self):
        self.store.save(self.grouped_data())
        page = self.page()
        QTest.mouseClick(page.group_buttons["fall"], Qt.MouseButton.LeftButton)
        page.search.setText("Fall Payment Deadline")
        self.qt.processEvents()
        self.assertIn("fall", page.collapsed_groups)
        self.assertEqual(sum(not page.table.isRowHidden(i) for i in range(page.table.rowCount())), 1)
        QTest.mouseClick(page.group_buttons["fall"], Qt.MouseButton.LeftButton)
        self.assertEqual(sum(not page.table.isRowHidden(i) for i in range(page.table.rowCount())), 16)
        self.assertIsNone(page.table.cellWidget(1, 0))

    def test_group_button_works_in_visible_area_after_horizontal_scrolling(self):
        self.store.save(self.grouped_data())
        page = self.page()
        page.table.setColumnWidth(0, 1300)
        page.table.horizontalScrollBar().setValue(page.table.horizontalScrollBar().maximum())
        self.qt.processEvents()
        control = page.group_buttons["fall"]
        visible = control.visibleRegion().boundingRect()
        self.assertFalse(visible.isEmpty())
        QTest.mouseClick(control, Qt.MouseButton.LeftButton, pos=visible.center())
        self.assertIn("fall", page.collapsed_groups)
        self.qt.processEvents()
        self.assertFalse(control.visibleRegion().isEmpty())

    def test_group_search_finds_members_and_category_filters_still_apply(self):
        self.store.save(self.grouped_data())
        page = self.page()
        page.search.setText("Fall Payment Deadline")
        self.assertEqual(page.table.rowCount(), 16)
        page.category.setCurrentIndex(page.category.findData("Tuition"))
        self.assertEqual(page.table.rowCount(), 4)

    def test_event_editor_can_change_group_without_changing_dates(self):
        saved = self.store.save(self.grouped_data())
        event = saved.events[0]
        dialog = self.keep(EventDialog(None, saved, self.store.access(), event))
        self.assertEqual(dialog.group.currentData(), "fall")
        dialog.group.setCurrentIndex(0)
        dialog._save()
        self.assertEqual(dialog.result_event, replace(event, group_id=None))

    def test_groups_dialog_moves_existing_items_and_preserves_dates(self):
        saved = self.store.save(self.grouped_data())
        dialog = self.keep(GroupsDialog(None, self.store))
        with patch.object(QInputDialog, "getText", return_value=("Fee Assessment", True)):
            dialog._add()
        new_id = dialog.groups.currentData()
        billing = next(dialog.items.item(i) for i in range(dialog.items.count())
                       if dialog.items.item(i).data(Qt.ItemDataRole.UserRole) == "billing")
        billing.setCheckState(Qt.CheckState.Checked)
        dialog.groups.setCurrentIndex(dialog.groups.findData("fall"))
        dialog.groups.setCurrentIndex(dialog.groups.findData(new_id))
        dialog._save()
        self.assertEqual(dialog.result(), QDialog.DialogCode.Accepted)
        current = self.store.load()
        self.assertEqual(next(e.group_id for e in current.events if e.id == "billing"), new_id)
        self.assertEqual([replace(e, group_id=None) for e in current.events],
                         [replace(e, group_id=None) for e in saved.events])

    def test_removing_group_keeps_events_and_cancel_does_not_save(self):
        saved = self.store.save(self.grouped_data())
        dialog = self.keep(GroupsDialog(None, self.store))
        with patch.object(QMessageBox, "question", return_value=QMessageBox.StandardButton.Yes):
            dialog._remove()
        dialog.reject()
        self.assertEqual(self.store.load(), saved)
        dialog = self.keep(GroupsDialog(None, self.store))
        with patch.object(QMessageBox, "question", return_value=QMessageBox.StandardButton.Yes):
            dialog._remove()
        dialog._save()
        self.assertEqual(self.store.load().groups, ())
        self.assertEqual([replace(e, group_id=None) for e in saved.events], list(self.store.load().events))

    def test_group_dialog_rejects_stale_save_and_revoked_admin(self):
        saved = self.store.save(self.grouped_data())
        dialog = self.keep(GroupsDialog(None, self.store))
        self.store.save(replace(saved, groups=(CalendarGroup("fall", "Renamed by another admin"),)))
        dialog._save()
        self.assertIn("Another administrator", dialog.error.text())
        self.policy["users"]["SECOND"] = dict(self.policy["users"]["ADMIN"])
        self.policy["users"]["ADMIN"]["active"] = False
        self.write_policy()
        dialog._save()
        self.assertIn("active administrator", dialog.error.text())

    def test_semester_editor_filter_and_group_summary_preserve_data(self):
        data = self.grouped_data()
        events = tuple(replace(data.events[0], id=f"event-{i}", title=f"Cycle step {i}",
                               semester=semester, coverage=() if i else data.events[0].coverage)
                       for i, semester in enumerate(("fall", "spring", "summer", "general", None)))
        saved = self.store.save(replace(data, events=events))
        before = self.store.path.read_bytes()
        page = self.page()
        self.assertEqual(SEMESTER_COLORS, {"fall": "#CC4628", "spring": "#09396C",
                                          "summer": "#57A2BD", "general": "#81848A"})
        summary = page.table.item(0, 2).data(Qt.ItemDataRole.UserRole)
        self.assertEqual(len(summary), 7)
        self.assertIn("Spring", page.table.item(0, 2).toolTip())
        self.assertIn("Cashier", page.table.item(0, 2).toolTip())
        reminders = page.attention.rowCount()
        page._set_groups_collapsed(True)
        self.assertEqual(sum(not page.table.isRowHidden(i) for i in range(page.table.rowCount())), 1)
        self.assertEqual(page.attention.rowCount(), reminders)
        self.assertFalse(page.grab().isNull())
        page.semester.setCurrentIndex(page.semester.findData("fall"))
        self.assertEqual(len(page.rows), 3)  # Linked coverage inherits the event's semester.
        self.assertEqual(len(page.table.item(0, 2).data(Qt.ItemDataRole.UserRole)), 3)
        page.semester.setCurrentIndex(page.semester.findData(None))
        self.assertEqual(len(page.rows), 1)
        self.assertIsNone(page.rows[0].occurrence.event.semester)
        page.semester.setCurrentIndex(page.semester.findData("all"))
        page._set_groups_collapsed(False)
        self.assertEqual(sum(not page.table.isRowHidden(i) for i in range(page.table.rowCount())), 8)
        self.assertEqual(self.store.path.read_bytes(), before)
        event = saved.events[1]
        dialog = self.keep(EventDialog(None, saved, self.store.access(), event))
        self.assertEqual(dialog.semester.currentData(), "spring")
        dialog.semester.setCurrentIndex(dialog.semester.findData("summer"))
        dialog._save()
        self.assertEqual(dialog.result_event, replace(event, semester="summer"))

    def test_compact_marks_keep_same_day_and_nearby_dates_in_separate_lanes(self):
        data = self.synthetic_calendar()
        events = tuple(replace(data.events[0], id=str(i), title=f"Deadline {i}", coverage=(),
                               anchor=date(2026, 9, 14 + i), semester="spring") for i in range(4))
        data = replace(data, events=events)
        rows = tuple(row for item in occurrences(data, date(2026, 1, 1), date(2026, 12, 31))
                     for row in timeline_rows(item))
        marks = timeline_marks(rows, date(2026, 1, 1), date(2026, 12, 31), 400)
        self.assertEqual(len(marks), 4)
        self.assertEqual(len({mark.lane for mark in marks}), 4)
        wider = timeline_marks(rows, date(2026, 9, 1), date(2026, 9, 30), 1000)
        self.assertEqual({mark.lane for mark in wider}, {0})
        same_day = tuple(replace(row, start=date(2026, 9, 14), end=date(2026, 9, 14)) for row in rows)
        same_day_marks = timeline_marks(same_day, date(2026, 9, 1), date(2026, 9, 30), 1000)
        self.assertEqual(len({mark.lane for mark in same_day_marks}), 4)
        # Group summary has no bar filling the gaps between independent dates.
        self.assertEqual({mark.row for mark in marks}, set(rows))
        data = assign_group(replace(data, groups=(CalendarGroup("cycle", "Billing Cycle"),)),
                            "cycle", frozenset(e.id for e in events))
        self.store.save(data)
        page = self.page()
        self.assertGreater(page.table.rowHeight(0), 52)
        original_height = page.table.rowHeight(0)
        page.period.setCurrentIndex(page.period.findData(9))
        self.assertLessEqual(page.table.rowHeight(0), original_height)
        page._set_groups_collapsed(True)
        self.assertFalse(page.grab().isNull())

    def test_group_timeline_paints_all_semester_colors(self):
        data = self.grouped_data()
        events = tuple(replace(data.events[0], id=str(i), title=f"Step {i}",
                               semester=semester, anchor=date(2026, 9, 14 + i * 3), coverage=())
                       for i, semester in enumerate(SEMESTER_COLORS))
        self.store.save(replace(data, events=events))
        page = self.page()
        page._set_groups_collapsed(True)
        self.qt.processEvents()
        cell = page.table.visualRect(page.table.model().index(0, 2))
        image = page.table.viewport().grab(cell).toImage()
        colors = {image.pixelColor(x, y).name().upper()
                  for x in range(image.width()) for y in range(image.height())}
        self.assertTrue(set(SEMESTER_COLORS.values()) <= colors)


if __name__ == "__main__":
    unittest.main()
