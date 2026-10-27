"""Admin-editable cyclical Bursar Office Calendar and Gantt timeline."""

from __future__ import annotations

import calendar
import json
from dataclasses import dataclass, replace
from datetime import date
from uuid import uuid4

from PySide6.QtCore import QDate, QEvent, QPointF, QRectF, QSignalBlocker, Qt, QTimer
from PySide6.QtGui import QColor, QFont, QFontMetrics, QPainter, QPen, QPolygonF
from PySide6.QtWidgets import (
    QAbstractItemView, QCheckBox, QComboBox, QDateEdit, QDialog,
    QDialogButtonBox, QFormLayout, QFrame, QGridLayout, QHBoxLayout, QHeaderView, QInputDialog,
    QLineEdit, QListWidget, QListWidgetItem, QMenu, QMessageBox, QPlainTextEdit, QPushButton, QTreeWidget, QTreeWidgetItem,
    QScrollArea, QSizePolicy, QSpinBox, QStyle, QStyledItemDelegate, QStyleOptionViewItem, QTableWidget,
    QTableWidgetItem, QToolButton, QVBoxLayout, QWidget,
)

from app.gui.services.access import AccessConfigurationError
from app.gui.services.operations_calendar import (
    Audience, CalendarData, CalendarError, CalendarEvent, CalendarGroup, CalendarStore,
    Coverage, DateOverride, Occurrence, RolePerson, audience_labels, audience_matches,
    person_available, person_label, role_label,
    occurrences, reminder_entries, replace_event, replace_future, replace_override,
    timeline_rows, unassigned_targets, assign_group, remove_group,
    SEMESTER_LABELS, TimelineRow,
)
from app.gui.theme import (
    BLASTER_BLUE, COLORADO_RED, LIGHT_BLUE, MUTED, MUTED_BLUE, PALE_BLUE, SILVER, button, label,
)
from shared.mines_paths import MinesPathError


ERRORS = (CalendarError, AccessConfigurationError, OSError, MinesPathError)


SEMESTER_COLORS = {"fall": COLORADO_RED, "spring": BLASTER_BLUE, "summer": MUTED_BLUE, "general": SILVER}


def semester_label(event: CalendarEvent) -> str:
    return SEMESTER_LABELS.get(event.semester, "Not assigned")


@dataclass(frozen=True)
class TimelineMark:
    row: TimelineRow
    left: float
    right: float
    lane: int


def timeline_marks(rows: tuple[TimelineRow, ...], start: date, end: date, width: int) -> tuple[TimelineMark, ...]:
    """Pack visible marks into lanes so nearby deadlines never conceal each other."""
    scale = max(width, 1) / ((end - start).days + 1)
    bounds = []
    for row in rows:
        if row.start > end or row.end < start:
            continue
        left = (max(row.start, start) - start).days * scale
        right = ((min(row.end, end) - start).days + 1) * scale
        # Reserve the diamond's actual drawn width, including on a year view.
        if row.start == row.end:
            center = (left + right) / 2
            left, right = center - 7, center + 7
        else:
            right = max(right, left + 3)
        bounds.append((row, left, right))
    lanes, marks = [], []
    for row, left, right in sorted(bounds, key=lambda item: (item[1], item[2], item[0].title)):
        lane = next((i for i, last in enumerate(lanes) if last + 4 <= left), len(lanes))
        if lane == len(lanes):
            lanes.append(right)
        else:
            lanes[lane] = right
        marks.append(TimelineMark(row, left, right, lane))
    return tuple(marks)


def date_control(day: date) -> QDateEdit:
    control = QDateEdit(QDate(day.year, day.month, day.day))
    control.setCalendarPopup(True)
    control.setDisplayFormat("MMM d, yyyy")
    control.setDateRange(QDate(1900, 1, 1), QDate(2199, 12, 31))
    return control


def spin_control(value: int, low: int, high: int) -> QSpinBox:
    control = QSpinBox()
    control.setRange(low, high)
    control.setValue(value)
    return control


def tags_from(text: str) -> tuple[str, ...]:
    return tuple(dict.fromkeys(tag.strip() for tag in text.split(",") if tag.strip()))


def month_ticks(start: date, end: date) -> tuple[tuple[int, int], ...]:
    return tuple((year, month) for year in range(start.year, end.year + 1)
                 for month in range(1, 13) if start <= date(year, month, 1) <= end)


def table_setup(table: QTableWidget, headings: tuple[str, ...]) -> None:
    table.setHorizontalHeaderLabels(headings)
    table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
    table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
    table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
    table.setAlternatingRowColors(True)
    table.verticalHeader().hide()
    table.verticalHeader().setDefaultSectionSize(48)


class AudienceEditor(QWidget):
    def __init__(self, access, audience=Audience(), parent=None):
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        self.everyone = QCheckBox("Everyone")
        self.everyone.setChecked(audience.everyone)
        layout.addWidget(self.everyone)
        layout.addWidget(label("Select a whole role or specific people beneath it.", "muted"))
        self.choices = QTreeWidget()
        self.choices.setHeaderHidden(True)
        self.choices.setAccessibleName("Affected roles and people")
        self.choices.setMinimumHeight(100)
        self.choices.setMaximumHeight(190)
        views = set(access.workflows_by_view) | set(audience.views) | {p.view for p in audience.people}
        for view in sorted(views):
            title = role_label(view) if view in access.workflows_by_view else f"{role_label(view)} — choose a current role"
            role = QTreeWidgetItem(self.choices, [title])
            self._checkable(role, view, view in audience.views)
            logins = {p.login.casefold() for p in access.users.values() if p.active and p.view == view}
            logins.update(p.login for p in audience.people if p.view == view)
            people = [RolePerson(view, login) for login in logins]
            for person in sorted(people, key=lambda p: person_label(p, access).casefold()):
                profile = access.raw_profile_for_login(person.login)
                name = profile.display_name if profile else person.login
                if not person_available(person, access):
                    name += " — unassigned"
                child = QTreeWidgetItem(role, [name])
                self._checkable(child, person.login, person in audience.people)
            role.setExpanded(True)
        layout.addWidget(self.choices)
        self.choices.itemChanged.connect(self._selection_changed)
        self.everyone.toggled.connect(lambda checked: self.choices.setEnabled(not checked))
        self.choices.setEnabled(not audience.everyone)

    def _checkable(self, item, key, checked):
        item.setData(0, Qt.ItemDataRole.UserRole, key)
        item.setFlags(item.flags() | Qt.ItemFlag.ItemIsUserCheckable)
        item.setCheckState(0, Qt.CheckState.Checked if checked else Qt.CheckState.Unchecked)

    def _selection_changed(self, item, column):
        if item.checkState(0) != Qt.CheckState.Checked:
            return
        self.choices.blockSignals(True)
        try:
            if item.parent() is None:
                for index in range(item.childCount()):
                    item.child(index).setCheckState(0, Qt.CheckState.Unchecked)
            else:
                item.parent().setCheckState(0, Qt.CheckState.Unchecked)
        finally:
            self.choices.blockSignals(False)

    def value(self) -> Audience:
        if self.everyone.isChecked():
            return Audience()
        views, people = [], []
        for index in range(self.choices.topLevelItemCount()):
            role = self.choices.topLevelItem(index)
            view = role.data(0, Qt.ItemDataRole.UserRole)
            if role.checkState(0) == Qt.CheckState.Checked:
                views.append(view)
            else:
                people.extend(RolePerson(view, role.child(i).data(0, Qt.ItemDataRole.UserRole))
                              for i in range(role.childCount())
                              if role.child(i).checkState(0) == Qt.CheckState.Checked)
        return Audience(False, tuple(views), tuple(people))


class CoverageDialog(QDialog):
    def __init__(self, parent, access, coverage=None):
        super().__init__(parent)
        self.original = coverage
        self.result_coverage = None
        self.setWindowTitle("Coverage period")
        self.resize(540, 450)
        layout = QVBoxLayout(self)
        layout.addWidget(label("Coverage follows the event date", "section"))
        layout.addWidget(label("Use negative days for before the deadline and positive days for after it. Both endpoints are included.", "muted"))
        form = QFormLayout()
        self.title = QLineEdit(coverage.title if coverage else "")
        self.title.setPlaceholderText("For example: Dual counter coverage")
        self.start = spin_control(coverage.start_offset if coverage else -14, -366, 366)
        self.end = spin_control(coverage.end_offset if coverage else 0, -366, 366)
        self.audience = AudienceEditor(access, coverage.audience if coverage else Audience())
        for title, widget in (("Coverage label", self.title), ("Start: days from event", self.start),
                              ("End: days from event", self.end), ("Affects", self.audience)):
            form.addRow(title, widget)
        layout.addLayout(form)
        self.error = label("", "error")
        layout.addWidget(self.error)
        controls = QDialogButtonBox(QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel)
        controls.accepted.connect(self._save)
        controls.rejected.connect(self.reject)
        layout.addWidget(controls)

    def _save(self):
        audience = self.audience.value()
        if not self.title.text().strip() or self.start.value() > self.end.value():
            self.error.setText("Enter a label and an end offset on or after the start offset.")
            return
        if not audience.everyone and not (audience.views or audience.people):
            self.error.setText("Choose who this coverage affects.")
            return
        self.result_coverage = Coverage(self.original.id if self.original else uuid4().hex,
                                       self.title.text().strip(), self.start.value(), self.end.value(), audience)
        self.accept()


class EventDialog(QDialog):
    def __init__(self, parent, data, access, event=None, *, first_date=None):
        super().__init__(parent)
        self.access, self.original = access, event
        self.result_event = None
        self.coverage = list(event.coverage if event else ())
        self.setWindowTitle("Edit recurring schedule" if event else "Add calendar item")
        self.resize(720, 800)
        layout = QVBoxLayout(self)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        body = QWidget()
        fields = QVBoxLayout(body)
        fields.addWidget(label(self.windowTitle(), "section"))
        fields.addWidget(label("Future dates follow this schedule; weekend adjustments need date review. Use separate schedules for months with different billing rules, or edit one occurrence's details.", "muted"))
        form = QFormLayout()
        self.title = QLineEdit(event.title if event else "")
        self.category = QComboBox()
        self.category.setEditable(True)
        self.category.setAccessibleName("Category")
        self.category.lineEdit().setMaxLength(200)
        for category in sorted({e.category for e in data.events} | {"Billing", "Payment Deadline", "Tuition", "Other"}):
            self.category.addItem(category)
        self.category.setCurrentText(event.category if event else "Other")
        self.group = QComboBox()
        self.group.addItem("No group", None)
        for group in sorted(data.groups, key=lambda g: g.name.casefold()):
            self.group.addItem(group.name, group.id)
        self.group.setCurrentIndex(max(0, self.group.findData(event.group_id if event else None)))
        self.group.setToolTip("Related items share a heading. Their dates and reminders stay independent. Use Groups… on the calendar to create groups or organize existing items.")
        self.semester = QComboBox()
        self.semester.addItem("Not assigned", None)
        for value, title in SEMESTER_LABELS.items():
            self.semester.addItem(title, value)
        self.semester.setCurrentIndex(max(0, self.semester.findData(event.semester if event else None)))
        self.semester.setToolTip("Choose the semester the work belongs to, even when its date falls in another semester. General means no semester; Not assigned leaves older entries unclassified.")
        category_row = QWidget()
        category_layout = QHBoxLayout(category_row)
        category_layout.setContentsMargins(0, 0, 0, 0)
        category_layout.addWidget(self.category, 1)
        self.new_category_button = button("New category…", self._new_category)
        category_layout.addWidget(self.new_category_button)
        self.anchor = date_control(first_date or (event.anchor if event else date.today()))
        self.duration = spin_control(event.duration if event else 1, 1, 366)
        self.recurrence = QComboBox()
        for title, value in (("One time", "once"), ("Every year", "annual"), ("Every month (selected months)", "monthly")):
            self.recurrence.addItem(title, value)
        self.recurrence.setCurrentIndex(self.recurrence.findData(event.recurrence if event else "once"))
        month_row = QWidget()
        month_layout = QGridLayout(month_row)
        month_layout.setContentsMargins(0, 0, 0, 0)
        self.months = []
        for month in range(1, 13):
            check = QCheckBox(calendar.month_abbr[month])
            check.setChecked(not event or month in event.months)
            self.months.append(check)
            month_layout.addWidget(check, (month - 1) // 6, (month - 1) % 6)
        self.recurrence.currentIndexChanged.connect(lambda: month_row.setEnabled(self.recurrence.currentData() == "monthly"))
        month_row.setEnabled(self.recurrence.currentData() == "monthly")
        self.has_until = QCheckBox("End recurring schedule on")
        self.has_until.setChecked(bool(event and event.until))
        self.until = date_control(event.until if event and event.until else date(date.today().year + 3, 12, 31))
        self.until.setEnabled(self.has_until.isChecked())
        self.has_until.toggled.connect(self.until.setEnabled)
        self.weekend = QComboBox()
        for title, value in (("Propose next Monday", "monday"), ("Keep college / normal date", "keep"), ("Propose previous Friday", "friday")):
            self.weekend.addItem(title, value)
        self.weekend.setCurrentIndex(self.weekend.findData(event.weekend if event else "monday"))
        self.reminder = spin_control(event.reminder_days if event else 21, 0, 366)
        self.tags = QLineEdit(", ".join(event.tags) if event else "")
        self.tags.setPlaceholderText("For example: Late Fees, Holds")
        self.notes = QPlainTextEdit(event.notes if event else "")
        self.notes.setMaximumHeight(85)
        self.audience = AudienceEditor(access, event.audience if event else Audience())
        for title, widget in (("Title", self.title), ("Category", category_row), ("Group (optional)", self.group),
                              ("Semester (optional)", self.semester),
                              ("First / normal date", self.anchor), ("Length in days", self.duration),
                              ("Repeat", self.recurrence), ("Monthly selection", month_row),
                              ("", self.has_until), ("Last date", self.until),
                              ("If normal date is a weekend", self.weekend), ("Remind days beforehand", self.reminder),
                              ("Billing details / labels", self.tags), ("Notes", self.notes), ("Affects", self.audience)):
            form.addRow(title, widget)
            widget.setAccessibleName(title or "Limit recurring schedule")
        fields.addLayout(form)
        self.recurrence.currentIndexChanged.connect(
            lambda: form.setRowVisible(month_row, self.recurrence.currentData() == "monthly")
        )
        form.setRowVisible(month_row, self.recurrence.currentData() == "monthly")
        self.has_until.toggled.connect(lambda checked: form.setRowVisible(self.until, checked))
        form.setRowVisible(self.until, self.has_until.isChecked())
        fields.addWidget(label("Linked coverage (moves with this item's date)", "section"))
        self.coverage_table = QTableWidget(0, 3)
        table_setup(self.coverage_table, ("Coverage", "Days from event", "Affects"))
        self.coverage_table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        self.coverage_table.setMinimumHeight(150)
        self.coverage_table.itemDoubleClicked.connect(lambda _: self._coverage(edit=True))
        fields.addWidget(self.coverage_table)
        actions = QHBoxLayout()
        actions.addWidget(button("Add coverage", self._coverage))
        actions.addWidget(button("Edit coverage", lambda: self._coverage(edit=True)))
        actions.addWidget(button("Remove coverage", self._remove_coverage))
        fields.addLayout(actions)
        scroll.setWidget(body)
        layout.addWidget(scroll, 1)
        self.error = label("", "error")
        layout.addWidget(self.error)
        controls = QDialogButtonBox(QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel)
        controls.accepted.connect(self._save)
        controls.rejected.connect(self.reject)
        layout.addWidget(controls)
        self._refresh_coverage()

    def _new_category(self):
        name, accepted = QInputDialog.getText(self, "New category", "Category name:")
        if not accepted:
            return
        name = name.strip()
        if not name or len(name) > 200 or "\n" in name or "\r" in name:
            self.error.setText("Enter a category name of 1–200 characters on one line.")
            return
        index = next((i for i in range(self.category.count())
                      if self.category.itemText(i).casefold() == name.casefold()), -1)
        if index < 0:
            self.category.addItem(name)
            index = self.category.count() - 1
        self.category.setCurrentIndex(index)
        self.error.setText("")

    def _refresh_coverage(self):
        self.coverage_table.setRowCount(len(self.coverage))
        for row, coverage in enumerate(self.coverage):
            values = (coverage.title, f"{coverage.start_offset:+d} to {coverage.end_offset:+d}",
                      "; ".join(audience_labels(coverage.audience, self.access)))
            for column, value in enumerate(values):
                self.coverage_table.setItem(row, column, QTableWidgetItem(value))

    def _coverage(self, checked=False, *, edit=False):
        index = self.coverage_table.currentRow()
        if edit and index < 0:
            return
        dialog = CoverageDialog(self, self.access, self.coverage[index] if edit else None)
        if dialog.exec() == QDialog.DialogCode.Accepted:
            if edit:
                self.coverage[index] = dialog.result_coverage
            else:
                self.coverage.append(dialog.result_coverage)
            self._refresh_coverage()

    def _remove_coverage(self):
        index = self.coverage_table.currentRow()
        if index >= 0:
            self.coverage.pop(index)
            self._refresh_coverage()

    def _save(self):
        anchor = self.anchor.date().toPython()
        until = self.until.date().toPython() if self.has_until.isChecked() else None
        months = tuple(i + 1 for i, check in enumerate(self.months) if check.isChecked())
        audience = self.audience.value()
        if not self.title.text().strip() or not self.category.currentText().strip():
            self.error.setText("Enter a title and category.")
            return
        if not months or (until and until < anchor):
            self.error.setText("Select at least one month and an end date on or after the first date.")
            return
        if not audience.everyone and not (audience.views or audience.people):
            self.error.setText("Choose who this item affects.")
            return
        self.result_event = CalendarEvent(
            self.original.id if self.original else uuid4().hex,
            self.title.text().strip(), self.category.currentText().strip(), anchor,
            self.recurrence.currentData(), months, until, self.weekend.currentData(),
            self.duration.value(), self.reminder.value(), audience, tags_from(self.tags.text()),
            self.notes.toPlainText().strip(), tuple(self.coverage), self.group.currentData(), self.semester.currentData(),
        )
        self.accept()


class GroupsDialog(QDialog):
    """Organize existing schedules without recreating or rescheduling them."""

    def __init__(self, parent, store: CalendarStore):
        super().__init__(parent)
        self.store = store
        self.data = store.load()
        self.selected_group = None
        self.setWindowTitle("Calendar Groups")
        self.resize(720, 560)
        layout = QVBoxLayout(self)
        layout.addWidget(label("Related Items, Independent Dates", "section"))
        layout.addWidget(label("Create a group such as Annual PCI Cycle, then select its existing items. Grouping keeps each item's dates, recurrence, roles, and reminders unchanged.", "muted"))
        self.groups = QComboBox()
        self.groups.setAccessibleName("Calendar group")
        self.groups.currentIndexChanged.connect(self._load_group)
        layout.addWidget(self.groups)
        actions = QHBoxLayout()
        actions.addWidget(button("New group…", self._add))
        self.rename_button = button("Rename…", self._rename)
        self.remove_button = button("Remove group", self._remove)
        actions.addWidget(self.rename_button)
        actions.addWidget(self.remove_button)
        actions.addStretch()
        layout.addLayout(actions)
        layout.addWidget(label("Select the items in this group. Checking an item in another group moves it here.", "muted"))
        self.items = QListWidget()
        self.items.setAccessibleName("Items in the selected group")
        layout.addWidget(self.items, 1)
        self.error = label("", "error")
        layout.addWidget(self.error)
        controls = QDialogButtonBox(QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel)
        controls.accepted.connect(self._save)
        controls.rejected.connect(self.reject)
        layout.addWidget(controls)
        self._refresh()

    def _remember(self):
        if self.selected_group is not None:
            selected = frozenset(self.items.item(i).data(Qt.ItemDataRole.UserRole)
                                 for i in range(self.items.count())
                                 if self.items.item(i).checkState() == Qt.CheckState.Checked)
            self.data = assign_group(self.data, self.selected_group, selected)

    def _refresh(self, selected=None):
        self.selected_group = None
        self.groups.blockSignals(True)
        self.groups.clear()
        for group in sorted(self.data.groups, key=lambda g: g.name.casefold()):
            self.groups.addItem(group.name, group.id)
        if selected is not None:
            self.groups.setCurrentIndex(self.groups.findData(selected))
        self.groups.blockSignals(False)
        self._load_group()

    def _load_group(self):
        self._remember()
        self.selected_group = self.groups.currentData()
        self.items.clear()
        names = {g.id: g.name for g in self.data.groups}
        for event in sorted(self.data.events, key=lambda e: (e.title.casefold(), e.anchor, e.id)):
            text = f"{event.title} · {event.category} · from {event.anchor:%b %d, %Y}"
            if event.group_id and event.group_id != self.selected_group:
                text += f" (in {names[event.group_id]})"
            item = QListWidgetItem(text, self.items)
            item.setToolTip(text)
            item.setData(Qt.ItemDataRole.UserRole, event.id)
            item.setFlags(item.flags() | Qt.ItemFlag.ItemIsUserCheckable)
            item.setCheckState(Qt.CheckState.Checked if event.group_id == self.selected_group and self.selected_group else Qt.CheckState.Unchecked)
        enabled = self.selected_group is not None
        self.items.setEnabled(enabled)
        self.rename_button.setEnabled(enabled)
        self.remove_button.setEnabled(enabled)

    def _name(self, title, current=""):
        name, accepted = QInputDialog.getText(self, title, "Group name:", text=current)
        if not accepted:
            return None
        name = name.strip()
        if not name or len(name) > 200 or "\n" in name or "\r" in name:
            self.error.setText("Enter a group name of 1–200 characters on one line.")
            return None
        if any(g.name.casefold() == name.casefold() and g.id != (self.selected_group if current else None)
               for g in self.data.groups):
            self.error.setText("A group with that name already exists.")
            return None
        self.error.setText("")
        return name

    def _add(self):
        name = self._name("New Group")
        if name is None:
            return
        self._remember()
        group = CalendarGroup(uuid4().hex, name)
        self.data = replace(self.data, groups=(*self.data.groups, group))
        self._refresh(group.id)

    def _rename(self):
        group = next((g for g in self.data.groups if g.id == self.selected_group), None)
        if group is None:
            return
        name = self._name("Rename Group", group.name)
        if name is not None:
            self._remember()
            self.data = replace(self.data, groups=tuple(replace(g, name=name) if g.id == group.id else g for g in self.data.groups))
            self._refresh(group.id)

    def _remove(self):
        if self.selected_group is None:
            return
        if QMessageBox.question(self, "Remove Group?", "Remove this group? Its calendar items and all their dates will be kept.",
                                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                                QMessageBox.StandardButton.No) != QMessageBox.StandardButton.Yes:
            return
        self._remember()
        self.data = remove_group(self.data, self.selected_group)
        self._refresh()

    def _save(self):
        self._remember()
        try:
            self.store.save(self.data)
        except ERRORS as error:
            self.error.setText(str(error))
            return
        self.accept()


class OccurrenceDialog(QDialog):
    def __init__(self, parent, occurrence: Occurrence):
        super().__init__(parent)
        self.occurrence = occurrence
        self.result_override = None
        self.setWindowTitle("Review / edit this date")
        self.resize(560, 480)
        layout = QVBoxLayout(self)
        layout.addWidget(label(occurrence.event.title, "section"))
        layout.addWidget(label(f"Normal date: {occurrence.nominal:%b %d, %Y}\n{occurrence.review_reason}", "muted"))
        form = QFormLayout()
        self.actual = date_control(occurrence.actual)
        self.duration = spin_control((occurrence.end - occurrence.actual).days + 1, 1, 366)
        self.tags = QLineEdit(", ".join(occurrence.tags))
        self.notes = QPlainTextEdit(occurrence.notes)
        self.notes.setMaximumHeight(110)
        self.approved = QCheckBox("Date reviewed by an admin")
        self.approved.setChecked(occurrence.approved)
        self.actual.dateChanged.connect(lambda _: self.approved.setChecked(False))
        self.duration.valueChanged.connect(lambda _: self.approved.setChecked(False))
        for title, widget in (("Actual / proposed date", self.actual), ("Length in days", self.duration),
                              ("Billing details / labels", self.tags), ("Notes", self.notes), ("", self.approved)):
            form.addRow(title, widget)
        layout.addLayout(form)
        layout.addWidget(label("Moving this date also moves its linked coverage. Other occurrences keep their own dates. Review can be changed later.", "muted"))
        controls = QDialogButtonBox(QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel)
        controls.accepted.connect(self._save)
        controls.rejected.connect(self.reject)
        layout.addWidget(controls)

    def _save(self):
        self.result_override = DateOverride(
            self.occurrence.event.id, self.occurrence.nominal, self.actual.date().toPython(),
            self.approved.isChecked(), self.duration.value(), tags_from(self.tags.text()),
            self.notes.toPlainText().strip(),
        )
        self.accept()


class EventLabelDelegate(QStyledItemDelegate):
    """Keep dates readable even when a long title needs to be elided."""

    def paint(self, painter, option, index):
        styled = QStyleOptionViewItem(option)
        self.initStyleOption(styled, index)
        # Qt normalizes line breaks in style options. Read the original display
        # value so the date can be drawn separately from an elided title.
        lines = str(index.data(Qt.ItemDataRole.DisplayRole)).split("\n", 1)
        styled.text = ""
        option.widget.style().drawControl(QStyle.ControlElement.CE_ItemViewItem, styled, painter, option.widget)
        painter.save()
        painter.setClipRect(option.rect)
        rect = option.rect.adjusted(10, 2, -8, -2)
        painter.setFont(styled.font)
        painter.setPen(styled.palette.text().color())
        title = QFontMetrics(styled.font).elidedText(lines[0], Qt.TextElideMode.ElideRight, rect.width())
        painter.drawText(rect.adjusted(0, 0, 0, -rect.height() // 2), Qt.AlignmentFlag.AlignVCenter, title)
        if len(lines) > 1:
            small = QFont(styled.font)
            small.setPointSizeF(max(8, small.pointSizeF() - 1))
            painter.setFont(small)
            painter.setPen(QColor(MUTED))
            dates = QFontMetrics(small).elidedText(lines[1], Qt.TextElideMode.ElideRight, rect.width())
            painter.drawText(rect.adjusted(0, rect.height() // 2, 0, 0), Qt.AlignmentFlag.AlignVCenter, dates)
        painter.restore()


class GanttDelegate(QStyledItemDelegate):
    def __init__(self, parent):
        super().__init__(parent)
        self.start = date.today().replace(month=1, day=1)
        self.end = self.start.replace(month=12, day=31)

    def paint(self, painter: QPainter, option, index):
        super().paint(painter, option, index)
        value = index.data(Qt.ItemDataRole.UserRole)
        if value is None:
            return
        painter.save()
        painter.setClipRect(option.rect)
        rect = option.rect.adjusted(8, 0, -8, 0)
        days = (self.end - self.start).days + 1
        scale = rect.width() / days
        for year, month in month_ticks(self.start, self.end):
            day = date(year, month, 1)
            if self.start <= day <= self.end:
                x = rect.left() + (day - self.start).days * scale
                painter.setPen(QPen(QColor(PALE_BLUE)))
                painter.drawLine(QPointF(x, rect.top()), QPointF(x, rect.bottom()))
        today = date.today()
        if self.start <= today <= self.end:
            x = rect.left() + (today - self.start).days * scale
            painter.setPen(QPen(QColor(COLORADO_RED), 2))
            painter.drawLine(QPointF(x, rect.top()), QPointF(x, rect.bottom()))
        grouped = isinstance(value, tuple)
        marks = timeline_marks(value if grouped else (value,), self.start, self.end, rect.width())
        lane_count = max((mark.lane + 1 for mark in marks), default=1)
        for mark in marks:
            row = mark.row
            left, right = rect.left() + mark.left, rect.left() + mark.right
            color = QColor(SEMESTER_COLORS.get(row.occurrence.event.semester,
                                             LIGHT_BLUE if row.coverage else BLASTER_BLUE))
            painter.setPen(QPen(color, 2))
            painter.setBrush(QColor(PALE_BLUE) if row.occurrence.needs_review else color)
            y = rect.center().y() + (mark.lane - (lane_count - 1) / 2) * 20
            if row.start == row.end:
                x = (left + right) / 2
                painter.drawPolygon(QPolygonF([QPointF(x, y - 7), QPointF(x + 7, y),
                                               QPointF(x, y + 7), QPointF(x - 7, y)]))
            else:
                height = 10 if row.coverage else 14
                painter.drawRoundedRect(QRectF(left, y - height / 2, right - left, height), 3, 3)
        painter.restore()


class TimelineHeader(QHeaderView):
    def __init__(self, delegate, parent):
        super().__init__(Qt.Orientation.Horizontal, parent)
        self.delegate = delegate

    def paintSection(self, painter, rect, logical_index):
        super().paintSection(painter, rect, logical_index)
        if logical_index != 2:
            return
        painter.save()
        painter.setClipRect(rect)
        painter.fillRect(rect, QColor(PALE_BLUE))
        painter.setPen(QColor(BLASTER_BLUE))
        start, end = self.delegate.start, self.delegate.end
        scale = (rect.width() - 16) / ((end - start).days + 1)
        next_label_x = rect.left()
        for year, month in month_ticks(start, end):
            day = date(year, month, 1)
            if start <= day <= end:
                x = rect.left() + 8 + (day - start).days * scale
                text = calendar.month_abbr[month]
                width = painter.fontMetrics().horizontalAdvance(text)
                if x + 4 >= next_label_x and x + 4 + width < rect.right():
                    painter.drawText(int(x + 4), rect.bottom() - 9, text)
                    next_label_x = x + width + 12
        painter.restore()


class OperationsCalendarPage(QWidget):
    def __init__(self, parent, store: CalendarStore):
        super().__init__(parent)
        self.setObjectName("page")
        self.store = store
        self.data = CalendarData()
        self.access = None
        self.rows = []
        self.display_rows = []
        self.collapsed_groups = set()
        self.group_buttons = {}
        self.group_timelines = {}
        self.attention_occurrences = []
        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 12, 16, 12)
        options_body = QFrame()
        options_body.setObjectName("calendarFiltersPanel")
        options_layout = QVBoxLayout(options_body)
        options_layout.setContentsMargins(12, 10, 12, 10)
        options_layout.setSpacing(8)
        self.options_panel = QScrollArea()
        self.options_panel.setWidgetResizable(True)
        self.options_panel.setWidget(options_body)
        self.options_panel.setMinimumHeight(160)
        self.options_panel.setMaximumHeight(190)
        self.options_panel.hide()
        layout.addWidget(label("Bursar Office Calendar", "title"))
        filter_heading = QHBoxLayout()
        filter_heading.addWidget(label("Filter calendar", "field", wrap=False))
        filter_heading.addStretch()
        self.clear_filters_button = button("Clear filters", self._clear_filters)
        self.clear_filters_button.setObjectName("calendarClearFilters")
        self.clear_filters_button.setMinimumHeight(24)
        self.clear_filters_button.setEnabled(False)
        filter_heading.addWidget(self.clear_filters_button)
        options_layout.addLayout(filter_heading)
        filters = QGridLayout()
        filters.setHorizontalSpacing(12)
        filters.setVerticalSpacing(8)
        self.year = spin_control(date.today().year, 1901, 2198)
        self.period = QComboBox()
        self.period.addItem("Full year", 0)
        for month in range(1, 13):
            last = (month + 1) % 12 + 1
            self.period.addItem(f"{calendar.month_abbr[month]}–{calendar.month_abbr[last]} (3 months)", month)
        self.period.setToolTip("Choose the months to display. The year is the starting year; Nov–Jan and Dec–Feb continue into the next year.")
        self.toolbar = QGridLayout()
        self._toolbar_columns = 0
        self.options_button = QToolButton()
        self.options_button.setObjectName("calendarFilters")
        self.options_button.setText("Filters")
        self.options_button.setCheckable(True)
        self.options_button.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.options_button.setAccessibleDescription("Filters collapsed")
        self.options_button.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
        self.options_button.setArrowType(Qt.ArrowType.RightArrow)
        self.options_button.setMinimumHeight(38)
        self.options_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self.options_button.setToolTip("Show or hide calendar filters. Filtering does not change calendar items.")
        self.options_button.toggled.connect(self._toggle_filters)
        self.actions_button = QPushButton("Calendar actions")
        self.actions_button.setMinimumHeight(38)
        self.actions_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self.actions_menu = QMenu(self.actions_button)
        self.add_action = self.actions_menu.addAction("Add item", self._add)
        self.review_action = self.actions_menu.addAction("Review / edit date", self._edit_date)
        self.series_action = self.actions_menu.addAction("Edit schedule", self._edit_series)
        self.groups_action = self.actions_menu.addAction("Groups…", self._groups)
        self.actions_menu.addSeparator()
        self.actions_menu.addAction("Calendar key…", self._calendar_key)
        self.actions_menu.addAction("Reload", self._reload)
        self.actions_menu.addSeparator()
        self.remove_action = self.actions_menu.addAction("Remove item", self._remove)
        self.actions_button.setMenu(self.actions_menu)
        layout.addLayout(self.toolbar)
        layout.addWidget(self.options_panel)
        self.category = QComboBox()
        self.category.setToolTip("Assign a category in Add item or Edit schedule. Use New category… there to add another label.")
        self.semester = QComboBox()
        self.semester.addItem("All semesters", "all")
        self.semester.addItem("Not assigned", None)
        for value, title in SEMESTER_LABELS.items():
            self.semester.addItem(title, value)
        self.role = QComboBox()
        self.search = QLineEdit()
        self.search.setPlaceholderText("Find an event, coverage, or billing detail…")
        self.search.setClearButtonEnabled(True)
        self.year.setAccessibleName("Year")
        self.period.setAccessibleName("Calendar view")
        for index, (caption, widget) in enumerate((("Category", self.category), ("Semester", self.semester),
                                                  ("Role / person", self.role), ("Search calendar", self.search))):
            field_layout = QVBoxLayout()
            field_layout.setSpacing(4)
            field_label = label(caption, "field", wrap=False)
            field_label.setBuddy(widget)
            field_layout.addWidget(field_label)
            field_layout.addWidget(widget)
            widget.setAccessibleName(caption)
            filters.addLayout(field_layout, index // 2, index % 2)
        filters.setColumnStretch(0, 1)
        filters.setColumnStretch(1, 1)
        for combo in (self.category, self.semester, self.role):
            combo.setSizeAdjustPolicy(QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon)
            combo.setMinimumContentsLength(8)
            combo.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        options_layout.addLayout(filters)
        group_actions = QHBoxLayout()
        for caption, collapsed in (("Collapse all", True), ("Expand all", False)):
            control = QToolButton()
            control.setText(caption)
            control.setToolTip(f"{caption} calendar groups")
            control.clicked.connect(lambda checked=False, value=collapsed: self._set_groups_collapsed(value))
            group_actions.addWidget(control)
        group_actions.addStretch()
        self.reminders_button = QToolButton()
        self.reminders_button.setText("Reminders")
        self.reminders_button.setCheckable(True)
        group_actions.addWidget(self.reminders_button)
        layout.addLayout(group_actions)
        self.summary = label("", "muted")
        layout.addWidget(self.summary)
        self.table = QTableWidget(0, 3)
        table_setup(self.table, ("Event / coverage / date", "Affects", "Timeline"))
        self.table.setAccessibleName("Bursar Office Calendar timeline")
        self.delegate = GanttDelegate(self.table)
        self.table.setHorizontalHeader(TimelineHeader(self.delegate, self.table))
        self.table.setHorizontalHeaderLabels(("Event / coverage / date", "Affects", "Timeline"))
        self.table.setColumnWidth(0, 235)
        self.table.setColumnWidth(1, 210)
        self.table.horizontalHeader().setMinimumSectionSize(65)
        self.table.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeMode.Stretch)
        self.table.setItemDelegateForColumn(2, self.delegate)
        self.table.setItemDelegateForColumn(0, EventLabelDelegate(self.table))
        self.table.itemDoubleClicked.connect(self._activate_row)
        self.table.itemSelectionChanged.connect(self._selection)
        self.table.horizontalHeader().sectionResized.connect(self._resize_group_timelines)
        layout.addWidget(self.table, 1)
        self.attention = QTableWidget(0, 3)
        table_setup(self.attention, ("Date", "Event / coverage", "Reminder"))
        self.attention.setAccessibleName("Upcoming and recently passed dates")
        self.attention.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        self.attention.setMaximumHeight(190)
        self.attention.itemDoubleClicked.connect(lambda _: self._edit_attention())
        layout.addWidget(self.attention)
        self.attention.hide()
        self.reminders_button.toggled.connect(self.attention.setVisible)
        self.year.valueChanged.connect(self._render)
        for combo in (self.period, self.category, self.semester, self.role):
            combo.currentIndexChanged.connect(self._render)
        self.search.textChanged.connect(self._render)
        self._reload()

    def _toggle_filters(self, expanded: bool) -> None:
        self.options_panel.setVisible(expanded)
        self.options_button.setArrowType(Qt.ArrowType.DownArrow if expanded else Qt.ArrowType.RightArrow)
        self.options_button.setAccessibleDescription("Filters expanded" if expanded else "Filters collapsed")
        if expanded:
            self.search.setFocus()
            QTimer.singleShot(0, self, lambda: self.options_panel.ensureWidgetVisible(self.search))

    def _clear_filters(self) -> None:
        with (QSignalBlocker(self.category), QSignalBlocker(self.semester),
              QSignalBlocker(self.role), QSignalBlocker(self.search)):
            self.category.setCurrentIndex(0)
            self.semester.setCurrentIndex(0)
            self.role.setCurrentIndex(0)
            self.search.clear()
        self._render()

    def _calendar_key(self) -> None:
        colors = "<br>".join(
            f'<span style="color:{color}">■</span> {SEMESTER_LABELS[key]}'
            for key, color in SEMESTER_COLORS.items()
        )
        QMessageBox.information(
            self, "Calendar key",
            "Filled marks: scheduled / reviewed<br>Outlined marks: needs date review<br>"
            "Red line: today<br>Diamonds: deadlines<br>Bars: work / coverage periods<br><br>" + colors,
        )

    def resizeEvent(self, event):
        super().resizeEvent(event)
        if not hasattr(self, "table"):
            return
        width = self.width() - 32 - 2 * self.table.frameWidth() - self.table.verticalScrollBar().sizeHint().width()
        # Keep most of a laptop viewport for dates. Exact labels remain in
        # tooltips, and columns can still be dragged wider for detailed review.
        self.table.setColumnWidth(0, max(150, min(235, round(width * .27))))
        self.table.setColumnWidth(1, max(100, min(180, round(width * .18))))
        self._layout_toolbar()

    def changeEvent(self, event):
        super().changeEvent(event)
        if event.type() in (QEvent.Type.FontChange, QEvent.Type.StyleChange):
            QTimer.singleShot(0, self, self._layout_toolbar)

    def _layout_toolbar(self):
        if not hasattr(self, "actions_button"):
            return
        controls = (self.year, self.period, self.options_button, self.actions_button)
        widths = [control.minimumSizeHint().width() for control in controls]
        columns = 1
        for candidate in (4, 2):
            required = sum(max(widths[column::candidate]) for column in range(candidate))
            if required + (candidate - 1) * self.toolbar.spacing() <= self.width() - 32:
                columns = candidate
                break
        # Qt can compress styled controls below their hints on Windows. Reserve
        # the measured column widths again after every font/style change, even
        # when the toolbar stays in the same row arrangement.
        for column in range(4):
            self.toolbar.setColumnMinimumWidth(
                column, max(widths[column::columns]) if column < columns else 0,
            )
            self.toolbar.setColumnStretch(column, int(column == (1 if columns > 1 else 0)))
        if columns == self._toolbar_columns:
            return
        self._toolbar_columns = columns
        while self.toolbar.count():
            self.toolbar.takeAt(0)
        for index, control in enumerate(controls):
            self.toolbar.addWidget(control, index // columns, index % columns)

    def _reload(self):
        try:
            self.data = self.store.load()
            self.access = self.store.access()
        except ERRORS as error:
            self.actions_button.setToolTip(str(error))
            self.access = None
            self.table.setRowCount(0)
            self.attention.setRowCount(0)
            self.summary.setText("Calendar unavailable. Reload after access or synchronization is restored.")
            self._selection()
            return
        category, role = self.category.currentData(), self.role.currentData()
        for combo in (self.category, self.role):
            combo.blockSignals(True)
            combo.clear()
        self.category.addItem("All categories", None)
        for name in sorted({e.category for e in self.data.events}):
            self.category.addItem(name, name)
        self.role.addItem("All roles / people", None)
        audiences = tuple(audience for event in self.data.events
                          for audience in (event.audience, *(c.audience for c in event.coverage)))
        used_views = {view for event in self.data.events
                      for audience in (event.audience, *(c.audience for c in event.coverage))
                      for view in (*audience.views, *(p.view for p in audience.people))}
        for view in sorted(set(self.access.workflows_by_view) | used_views):
            self.role.addItem(role_label(view), json.dumps([view, None]))
            people = {RolePerson(view, profile.login.casefold()) for profile in self.access.users.values()
                      if profile.active and profile.view == view}
            people.update(p for audience in audiences for p in audience.people if p.view == view)
            for person in sorted(people, key=lambda p: person_label(p, self.access).casefold()):
                caption = person_label(person, self.access)
                if not person_available(person, self.access):
                    caption += " — unassigned"
                self.role.addItem("    " + caption, json.dumps([view, person.login]))
        self.category.setCurrentIndex(max(0, self.category.findData(category)))
        self.role.setCurrentIndex(max(0, self.role.findData(role)))
        for combo in (self.category, self.role):
            combo.blockSignals(False)
        self.actions_button.setToolTip(f"Shared calendar · last saved by {self.data.updated_by} at {self.data.updated_at}" if self.data.updated_by else "Shared calendar is empty. Add your first recurring item and select its affected roles or people.")
        self._render()

    def _save(self, data):
        try:
            self.store.save(data)
        except ERRORS as error:
            QMessageBox.warning(self, "Calendar was not changed", str(error))
            return False
        self._reload()
        return True

    def _matches(self, row):
        if self.category.currentData() and row.occurrence.event.category != self.category.currentData():
            return False
        semester = self.semester.currentData()
        if semester != "all" and row.occurrence.event.semester != semester:
            return False
        target = self.role.currentData()
        if target:
            view, login = json.loads(target)
            if not audience_matches(row.audience, view, login):
                return False
        group = next((g.name for g in self.data.groups if g.id == row.occurrence.event.group_id), "")
        text = " ".join((row.title, row.occurrence.event.title, row.occurrence.event.category, group,
                         semester_label(row.occurrence.event),
                         *row.occurrence.tags, row.occurrence.notes,
                         *audience_labels(row.audience, self.access))).casefold()
        return self.search.text().strip().casefold() in text

    def _render(self, *_):
        if self.access is None:
            return
        active_count = sum((self.category.currentData() is not None, self.semester.currentData() != "all",
                            self.role.currentData() is not None, bool(self.search.text().strip())))
        self.options_button.setText(f"Filters ({active_count})" if active_count else "Filters")
        self.options_button.setAccessibleName(f"Calendar filters, {active_count} active")
        self.clear_filters_button.setEnabled(active_count > 0)
        self._layout_toolbar()
        year, month = self.year.value(), self.period.currentData() or 1
        start = date(year, month, 1)
        last_month_index = month + 1 if self.period.currentData() else 11
        last_year, last_month = year + last_month_index // 12, last_month_index % 12 + 1
        end = date(last_year, last_month, calendar.monthrange(last_year, last_month)[1])
        self.delegate.start, self.delegate.end = start, end
        self.table.horizontalHeader().viewport().update()
        self.rows = [row for occurrence in occurrences(self.data, start, end)
                     for row in timeline_rows(occurrence)
                     if row.start <= end and row.end >= start and self._matches(row)]
        grouped = {g.id: [] for g in self.data.groups}
        self.display_rows = []
        for row in self.rows:
            if row.occurrence.event.group_id:
                grouped[row.occurrence.event.group_id].append(row)
            else:
                self.display_rows.append(row)
        for group in sorted(self.data.groups, key=lambda g: g.name.casefold()):
            if grouped[group.id]:
                self.display_rows.append(group)
                self.display_rows.extend(grouped[group.id])
        self.table.clearSpans()
        self.group_timelines = {}
        self.table.setRowCount(0)
        self.group_buttons = {}
        self.table.setRowCount(len(self.display_rows))
        for index, row in enumerate(self.display_rows):
            if isinstance(row, CalendarGroup):
                count = len({r.occurrence.event.id for r in grouped[row.id]})
                header = QTableWidgetItem("")
                header.setData(Qt.ItemDataRole.AccessibleTextRole, row.name)
                self.table.setItem(index, 0, header)
                self.table.setSpan(index, 0, 1, 2)
                members = tuple(grouped[row.id])
                self.group_timelines[index] = members
                timeline = QTableWidgetItem("")
                timeline.setData(Qt.ItemDataRole.UserRole, members)
                tip = "\n".join(
                    f"{member.title} · {semester_label(member.occurrence.event)} · "
                    f"{member.start:%b %d, %Y} – {member.end:%b %d, %Y} · "
                    f"{member.occurrence.review_reason} · "
                    f"{'; '.join(audience_labels(member.audience, self.access))}"
                    for member in members
                )
                timeline.setToolTip(tip)
                timeline.setData(Qt.ItemDataRole.AccessibleTextRole, tip)
                self.table.setItem(index, 2, timeline)
                control = QToolButton(self.table)
                control.setCheckable(True)
                control.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
                control.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
                control.setMinimumHeight(44)
                control.setStyleSheet(
                    f"QToolButton {{ background: {PALE_BLUE}; border: 1px solid {LIGHT_BLUE}; "
                    "border-radius: 4px; padding: 8px 12px; font-weight: 600; }"
                    f"QToolButton:hover {{ background: {LIGHT_BLUE}; }}"
                    f"QToolButton:focus {{ border: 2px solid {BLASTER_BLUE}; }}"
                )
                control.setProperty("groupName", row.name)
                control.setProperty("itemCount", count)
                control.clicked.connect(lambda checked=False, group_id=row.id: self._toggle_group(group_id))
                self.group_buttons[row.id] = control
                self._update_group_button(row.id)
                self.table.setCellWidget(index, 0, control)
                self.table.setRowHeight(index, 52)
                continue
            occurrence = row.occurrence
            text = f"{'  ' if occurrence.event.group_id else ''}{'↳ ' if row.coverage else ''}{row.title}"
            if not row.coverage and occurrence.tags:
                text += " · " + ", ".join(occurrence.tags)
            affected = "; ".join(audience_labels(row.audience, self.access))
            dates = f"{row.start:%b %d}" + (f" – {row.end:%b %d}" if row.end != row.start else "")
            text += "\n" + dates + " · " + ("Reviewed" if occurrence.approved else "Proposed" if occurrence.needs_review else "Scheduled")
            text += " · " + semester_label(occurrence.event)
            tip = (f"{row.title}\n{row.start:%b %d, %Y} – {row.end:%b %d, %Y}\n"
                   f"{affected}\nNormal event date: {occurrence.nominal:%b %d, %Y}\n"
                   f"{occurrence.review_reason}\nSemester: {semester_label(occurrence.event)}\nCategory: {occurrence.event.category}\n"
                   f"Details: {', '.join(occurrence.tags)}\n{occurrence.notes}")
            for column, value in enumerate((text, affected, "")):
                item = QTableWidgetItem(value)
                item.setToolTip(tip)
                if column == 2:
                    item.setData(Qt.ItemDataRole.UserRole, row)
                    item.setData(Qt.ItemDataRole.AccessibleTextRole, tip)
                self.table.setItem(index, column, item)
        self._apply_group_visibility()
        self._resize_group_timelines()
        proposed = len({(r.occurrence.event.id, r.occurrence.nominal) for r in self.rows if r.occurrence.needs_review})
        vacant = {name for row in self.rows for name in unassigned_targets(row.audience, self.access)}
        self.summary.setText(f"{len(self.rows)} matching deadlines / coverage periods · {proposed} dates need review · {len(vacant)} unassigned. Overlapping bars show overlapping demand.")
        self._render_attention()
        self._selection()

    def _render_attention(self):
        entries = [(row, message) for row, message in reminder_entries(self.data, self.access, date.today())
                   if self._matches(row)]
        self.attention_occurrences = [row.occurrence for row, _ in entries]
        self.reminders_button.setText(f"Reminders ({len(entries)})")
        self.attention.setRowCount(len(entries))
        self.attention.setFixedHeight(min(190, max(80, 48 * len(entries) + 48)))
        for index, (row, message) in enumerate(entries):
            group = next((g.name for g in self.data.groups if g.id == row.occurrence.event.group_id), None)
            title = f"{group} · {row.title}" if group else row.title
            for column, value in enumerate((f"{row.start:%b %d, %Y}", title, message)):
                item = QTableWidgetItem(value)
                item.setToolTip(value)
                self.attention.setItem(index, column, item)

    def _selected(self):
        index = self.table.currentRow()
        if (0 <= index < len(self.display_rows) and not self.table.isRowHidden(index)
                and not isinstance(self.display_rows[index], CalendarGroup)):
            return self.display_rows[index].occurrence
        return None

    def _activate_row(self, item):
        row = self.display_rows[item.row()]
        if not isinstance(row, CalendarGroup):
            self._edit_date(occurrence=row.occurrence)

    def _update_group_button(self, group_id):
        control = self.group_buttons[group_id]
        expanded = group_id not in self.collapsed_groups
        action = "Collapse" if expanded else "Expand"
        name, count = control.property("groupName"), control.property("itemCount")
        control.setText(f"{name} · {count} related item(s) · {action}")
        control.setArrowType(Qt.ArrowType.DownArrow if expanded else Qt.ArrowType.RightArrow)
        control.setChecked(expanded)
        control.setAccessibleName(f"{action} {name}")
        control.setToolTip(f"{name}\nClick this button, or focus it and press Space, to expand or collapse. The timeline keeps every matching date and coverage period visible. Each item keeps its own dates and reminders. Use Groups… to change membership.")

    def _resize_group_timelines(self, *_):
        width = self.table.columnWidth(2) - 16
        for index, members in self.group_timelines.items():
            marks = timeline_marks(members, self.delegate.start, self.delegate.end, width)
            lanes = max((mark.lane + 1 for mark in marks), default=1)
            self.table.setRowHeight(index, max(52, lanes * 20 + 12))

    def _set_groups_collapsed(self, collapsed):
        if collapsed:
            self.collapsed_groups.update(self.group_buttons)
        else:
            self.collapsed_groups.clear()
        for group_id in self.group_buttons:
            self._update_group_button(group_id)
        self._apply_group_visibility()
        self._selection()

    def _apply_group_visibility(self):
        for index, row in enumerate(self.display_rows):
            hidden = not isinstance(row, CalendarGroup) and row.occurrence.event.group_id in self.collapsed_groups
            self.table.setRowHidden(index, hidden)

    def _toggle_group(self, group_id):
        if group_id not in self.group_buttons:
            return
        if group_id in self.collapsed_groups:
            self.collapsed_groups.remove(group_id)
        else:
            self.collapsed_groups.add(group_id)
        # Keep the actual button alive while hiding rows. Rebuilding the table
        # during a click discards focus and can move the control out from under
        # the pointer when the view is scrolled.
        self._update_group_button(group_id)
        self._apply_group_visibility()
        index = next(i for i, row in enumerate(self.display_rows)
                     if isinstance(row, CalendarGroup) and row.id == group_id)
        self.table.setCurrentCell(index, 0)
        self.table.scrollToItem(self.table.item(index, 0), QAbstractItemView.ScrollHint.EnsureVisible)
        self._selection()

    def _groups(self):
        try:
            dialog = GroupsDialog(self, self.store)
        except ERRORS as error:
            QMessageBox.warning(self, "Groups unavailable", str(error))
            return
        if dialog.exec() == QDialog.DialogCode.Accepted:
            self._reload()

    def _selection(self):
        self.add_action.setEnabled(self.access is not None)
        self.groups_action.setEnabled(self.access is not None)
        self.remove_action.setEnabled(self.access is not None)
        for control in (self.review_action, self.series_action):
            control.setEnabled(self.access is not None and self._selected() is not None)

    def _add(self):
        if self.access is None:
            return
        dialog = EventDialog(self, self.data, self.access)
        if dialog.exec() == QDialog.DialogCode.Accepted:
            self._save(replace_event(self.data, dialog.result_event))

    def _edit_date(self, checked=False, *, occurrence=None):
        occurrence = occurrence or self._selected()
        if occurrence is None:
            return
        dialog = OccurrenceDialog(self, occurrence)
        if dialog.exec() == QDialog.DialogCode.Accepted:
            self._save(replace_override(self.data, dialog.result_override))

    def _edit_attention(self):
        index = self.attention.currentRow()
        if 0 <= index < len(self.attention_occurrences):
            self._edit_date(occurrence=self.attention_occurrences[index])

    def _edit_series(self):
        occurrence = self._selected()
        if occurrence is None:
            return
        scope, ok = QInputDialog.getItem(self, "Edit schedule", "Apply schedule changes to:",
                                        ("Entire schedule", "This occurrence and future dates"), 1, False)
        if not ok:
            return
        future = scope == "This occurrence and future dates"
        dialog = EventDialog(self, self.data, self.access, occurrence.event,
                             first_date=occurrence.nominal if future else None)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        if future:
            if dialog.result_event.anchor < occurrence.nominal:
                QMessageBox.warning(self, "Calendar was not changed", "For a future-only edit, the first date cannot precede the selected occurrence.")
                return
            if QMessageBox.question(self, "Replace future schedule?",
                                    "Earlier dates will stay as they are. This and future dates will use the new schedule; their existing date exceptions and approvals will be reset. Continue?",
                                    QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                                    QMessageBox.StandardButton.No) != QMessageBox.StandardButton.Yes:
                return
            data = replace_future(self.data, occurrence, replace(dialog.result_event, id=uuid4().hex))
        else:
            data = replace_event(self.data, dialog.result_event)
        self._save(data)

    def _remove(self):
        occurrence = self._selected()
        if occurrence is None:
            QMessageBox.information(
                self, "Select an item to remove",
                "Select an individual event or coverage row in the calendar, then choose "
                "Calendar actions → Remove item.\n\n"
                "To remove a group heading while keeping its items, use Calendar actions → Groups….",
            )
            self.table.setFocus()
            return
        scope, ok = QInputDialog.getItem(self, "Remove calendar item", "Remove:",
                                        ("Only this occurrence", "Entire schedule and linked coverage"), 0, False)
        if not ok:
            return
        if QMessageBox.question(self, "Remove calendar item?", f"{scope}: {occurrence.event.title}?",
                                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                                QMessageBox.StandardButton.No) != QMessageBox.StandardButton.Yes:
            return
        if scope == "Only this occurrence":
            data = replace_override(self.data, DateOverride(
                occurrence.event.id, occurrence.nominal, occurrence.actual,
                hidden=True, duration=(occurrence.end - occurrence.actual).days + 1,
                tags=occurrence.tags, notes=occurrence.notes,
            ))
        else:
            data = replace(self.data, events=tuple(e for e in self.data.events if e.id != occurrence.event.id),
                           overrides=tuple(o for o in self.data.overrides if o.event_id != occurrence.event.id))
        self._save(data)
