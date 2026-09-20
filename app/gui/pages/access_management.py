"""Qt staff management: editable profiles, role permissions, and owner protection."""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path
from typing import Callable

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QAbstractItemView, QCheckBox, QComboBox, QDialog, QDialogButtonBox,
    QFormLayout, QHBoxLayout, QHeaderView, QInputDialog, QLineEdit,
    QMessageBox, QScrollArea, QTableWidget, QTableWidgetItem, QVBoxLayout, QWidget,
)

from app.gui.services.access import (
    AccessConfiguration, AccessConfigurationError, UserAccessProfile,
    add_view, rename_view, remove_view,
    create_owner_protection, load_access_configuration, save_access_configuration,
)
from app.gui.theme import button, label
from app.gui.workflow_registry import get_workflows
from shared.mines_paths import MinesPathError


class ProfileDialog(QDialog):
    """Keep every editable profile field in one form, with an explicit save."""

    def __init__(self, parent, configuration: AccessConfiguration, profile=None) -> None:
        super().__init__(parent)
        self.configuration = configuration
        self.profile = profile
        self.result_profile = None
        self.setWindowTitle("Edit staff access" if profile else "Add staff access")
        self.setMinimumWidth(460)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 24, 24, 24)
        layout.setSpacing(16)
        layout.addWidget(label(self.windowTitle(), "section"))
        layout.addWidget(label("The view controls available workflows. Job title is descriptive.", "muted"))
        form = QFormLayout()
        form.setSpacing(12)
        self.login = QLineEdit(profile.login if profile else "")
        self.login.setReadOnly(profile is not None)
        self.name = QLineEdit(profile.display_name if profile else "")
        self.title = QLineEdit(profile.job_title if profile else "")
        self.view = QComboBox()
        for view in sorted(configuration.workflows_by_view):
            self.view.addItem(view.title(), view)
        if profile:
            self.view.setCurrentIndex(self.view.findData(profile.view))
        else:
            self.view.setCurrentIndex(-1)
            self.view.setPlaceholderText("Choose a view")
        for caption, control in (
            ("Windows login", self.login), ("Display name", self.name),
            ("Job title", self.title), ("View", self.view),
        ):
            form.addRow(caption, control)
            control.setAccessibleName(caption)
        layout.addLayout(form)
        self.error = label("", "error")
        layout.addWidget(self.error)
        controls = QDialogButtonBox(QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel)
        controls.accepted.connect(self._validate)
        controls.rejected.connect(self.reject)
        layout.addWidget(controls)

    def _validate(self) -> None:
        login, name, title = (widget.text().strip() for widget in (self.login, self.name, self.title))
        view = self.view.currentData()
        if not all((login, name, title, view)):
            self.error.setText("Complete every field and choose a view.")
            return
        if self.profile is None and login.casefold() in self.configuration.users:
            self.error.setText("This login already exists. Edit or restore its existing profile.")
            return
        if any(len(text) > 150 or "\n" in text or "\r" in text for text in (login, name, title)):
            self.error.setText("Use a single line of no more than 150 characters per field.")
            return
        self.result_profile = UserAccessProfile(
            login, name, title, view, self.profile.active if self.profile else True
        )
        self.accept()


class AccessManagementPage(QWidget):
    def __init__(
        self, parent, *, configuration: AccessConfiguration, config_path: Path,
        current_login: str, go_home: Callable[[], None],
        policy_saved: Callable[[AccessConfiguration], None],
    ) -> None:
        super().__init__(parent)
        self.setObjectName("page")
        self.configuration = configuration
        self.config_path = config_path
        self.current_login = current_login
        self.policy_saved = policy_saved
        layout = QVBoxLayout(self)
        layout.setContentsMargins(36, 30, 36, 30)
        layout.setSpacing(16)
        layout.addWidget(label("ADMINISTRATION", "eyebrow"))
        layout.addWidget(label("Staff access", "title"))
        layout.addWidget(label(
            "Give each person a focused workspace. Revoking access keeps their profile for future restoration.",
            "muted",
        ))
        self.search = QLineEdit()
        self.search.setPlaceholderText("Find a person, login, or job title…")
        self.search.setClearButtonEnabled(True)
        self.search.setAccessibleName("Search staff")
        self.search.textChanged.connect(self._filter)
        layout.addWidget(self.search)
        toolbar = QHBoxLayout()
        self.add_button = button("Add user", self._add, "primary")
        self.edit_button = button("Edit profile", self._edit)
        self.toggle_button = button("Revoke / restore", self._toggle_active)
        for control in (self.add_button, self.edit_button, self.toggle_button):
            toolbar.addWidget(control)
        toolbar.addStretch()
        toolbar.addWidget(button("Reload", self._reload))
        layout.addLayout(toolbar)
        self.table = QTableWidget(0, 6)
        self.table.setHorizontalHeaderLabels(("Name", "Windows login", "Job title", "View", "Status", "Owner"))
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.setAlternatingRowColors(True)
        self.table.setShowGrid(False)
        self.table.verticalHeader().hide()
        self.table.verticalHeader().setDefaultSectionSize(48)
        self.table.horizontalHeader().setMinimumSectionSize(65)
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Interactive)
        for column, width in enumerate((115, 125, 150, 110, 80, 90)):
            self.table.setColumnWidth(column, width)
        self.table.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeMode.Stretch)
        self.table.setAccessibleName("Staff profiles")
        self.table.itemDoubleClicked.connect(lambda _: self._edit())
        self.table.itemSelectionChanged.connect(self._selection_changed)
        layout.addWidget(self.table, 1)
        actions = QHBoxLayout()
        self.permissions_button = button("Manage views & permissions", self._edit_view)
        self.owner_button = button("Owner password", self._set_owner_password)
        actions.addWidget(self.permissions_button)
        actions.addWidget(self.owner_button)
        actions.addStretch()
        layout.addLayout(actions)
        self.status = label("", "muted")
        layout.addWidget(self.status)
        self._refresh()

    @property
    def owner_key(self) -> str:
        return (self.configuration.owner_login or "").casefold()

    def _refresh(self) -> None:
        self.table.setSortingEnabled(False)
        self.table.setRowCount(0)
        for key, profile in sorted(self.configuration.users.items()):
            row = self.table.rowCount()
            self.table.insertRow(row)
            values = (profile.display_name, profile.login, profile.job_title,
                      profile.view.title(), "Active" if profile.active else "Revoked",
                      "Protected" if key == self.owner_key else "")
            for column, value in enumerate(values):
                item = QTableWidgetItem(value)
                item.setToolTip(value)
                item.setData(Qt.ItemDataRole.UserRole, key)
                self.table.setItem(row, column, item)
        self.table.setSortingEnabled(True)
        self._filter(self.search.text())
        active_admin = self.configuration.is_administrator(self.current_login)
        self.add_button.setEnabled(active_admin)
        self.permissions_button.setEnabled(active_admin)
        self.owner_button.setEnabled(active_admin and self.current_login.casefold() == self.owner_key)
        self._selection_changed()
        message = (
            "Owner password is set." if self.configuration.owner_protection
            else "The owner should set a password before changing their protected profile."
        )
        if self.configuration.updated_by:
            message += f"  Last saved by {self.configuration.updated_by}."
        self.status.setText(message)

    def _filter(self, query: str) -> None:
        query = query.strip().casefold()
        for row in range(self.table.rowCount()):
            text = " ".join(self.table.item(row, col).text() for col in range(6)).casefold()
            self.table.setRowHidden(row, query not in text)
        self._selection_changed()

    def _selected(self) -> tuple[str, UserAccessProfile] | None:
        row = self.table.currentRow()
        if row < 0 or self.table.isRowHidden(row):
            return None
        key = self.table.item(row, 0).data(Qt.ItemDataRole.UserRole)
        return key, self.configuration.users[key]

    def _selection_changed(self) -> None:
        selected = self._selected()
        enabled = selected is not None and self.configuration.is_administrator(self.current_login)
        self.edit_button.setEnabled(enabled)
        self.toggle_button.setEnabled(enabled)
        self.toggle_button.setText("Revoke access" if selected and selected[1].active else "Restore access")

    def _save(self, updated: AccessConfiguration, *, owner_password: str | None = None) -> bool:
        try:
            saved = save_access_configuration(
                self.config_path, updated, actor_login=self.current_login, owner_password=owner_password
            )
        except (AccessConfigurationError, OSError, MinesPathError) as error:
            QMessageBox.warning(self, "Access was not changed", str(error))
            return False
        self.configuration = saved
        self.policy_saved(saved)
        self._refresh()
        self.status.setText("Changes saved. " + self.status.text())
        return True

    def _reload(self) -> None:
        try:
            configuration = load_access_configuration(self.config_path)
        except AccessConfigurationError as error:
            QMessageBox.warning(self, "Could not reload access", str(error))
            return
        self.configuration = configuration
        self.policy_saved(configuration)
        self._refresh()

    def _add(self) -> None:
        dialog = ProfileDialog(self, self.configuration)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        profile = dialog.result_profile
        users = dict(self.configuration.users)
        users[profile.login.casefold()] = profile
        self._save(replace(self.configuration, users=users))

    def _edit(self) -> None:
        selected = self._selected()
        if selected is None:
            return
        key, current = selected
        dialog = ProfileDialog(self, self.configuration, current)
        if dialog.exec() != QDialog.DialogCode.Accepted or dialog.result_profile == current:
            return
        password = self._owner_password_if_needed(key)
        if password is False:
            return
        users = dict(self.configuration.users)
        users[key] = dialog.result_profile
        self._save(replace(self.configuration, users=users), owner_password=password)

    def _toggle_active(self) -> None:
        selected = self._selected()
        if selected is None:
            return
        key, profile = selected
        action = "Revoke" if profile.active else "Restore"
        if QMessageBox.question(
            self, f"{action} access", f"{action} GUI access for {profile.display_name}?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        ) != QMessageBox.StandardButton.Yes:
            return
        password = self._owner_password_if_needed(key)
        if password is False:
            return
        users = dict(self.configuration.users)
        users[key] = replace(profile, active=not profile.active)
        self._save(replace(self.configuration, users=users), owner_password=password)

    def _owner_password_if_needed(self, key: str) -> str | bool | None:
        if key != self.owner_key:
            return None
        if self.configuration.owner_protection is None:
            QMessageBox.information(self, "Set owner password first",
                                    "Use Owner password before changing the protected owner profile.")
            return False
        value, accepted = QInputDialog.getText(
            self, "Protected owner", "Owner password:", QLineEdit.EchoMode.Password
        )
        return value if accepted else False

    def _set_owner_password(self) -> None:
        if self.current_login.casefold() != self.owner_key:
            return
        dialog = QDialog(self)
        dialog.setWindowTitle("Owner password")
        dialog.setMinimumWidth(460)
        layout = QVBoxLayout(dialog)
        layout.addWidget(label("Protect your owner profile", "section"))
        layout.addWidget(label("Use a unique password of at least 12 characters.", "muted"))
        fields = QFormLayout()
        current, first, second = QLineEdit(), QLineEdit(), QLineEdit()
        for widget in (current, first, second):
            widget.setEchoMode(QLineEdit.EchoMode.Password)
        if self.configuration.owner_protection:
            fields.addRow("Current password", current)
        fields.addRow("New password", first)
        fields.addRow("Confirm password", second)
        layout.addLayout(fields)
        error_label = label("", "error")
        layout.addWidget(error_label)
        controls = QDialogButtonBox(QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel)
        layout.addWidget(controls)
        controls.rejected.connect(dialog.reject)

        def save() -> None:
            if first.text() != second.text():
                error_label.setText("Passwords do not match.")
                return
            try:
                protection = create_owner_protection(first.text())
            except AccessConfigurationError as error:
                error_label.setText(str(error))
                return
            if self._save(replace(self.configuration, owner_protection=protection),
                          owner_password=current.text() if self.configuration.owner_protection else None):
                dialog.accept()

        controls.accepted.connect(save)
        dialog.exec()

    def _edit_view(self) -> None:
        dialog = QDialog(self)
        dialog.setWindowTitle("Manage views & permissions")
        dialog.resize(620, 520)
        layout = QVBoxLayout(dialog)
        layout.addWidget(label("Views & workflow permissions", "section"))
        layout.addWidget(label(
            "Create a view for a team or position, then choose its workflows. "
            "Job titles can be changed separately in Edit profile. "
            "Administrator always includes every workflow.", "muted",
        ))
        view = QComboBox()
        view.setAccessibleName("View to configure")
        layout.addWidget(view)
        actions = QHBoxLayout()
        add_button = button("Add view", lambda: add())
        rename_button = button("Rename view", lambda: rename())
        remove_button = button("Remove view", lambda: remove())
        for control in (add_button, rename_button, remove_button):
            actions.addWidget(control)
        actions.addStretch()
        layout.addLayout(actions)
        assignment_label = label("", "muted")
        layout.addWidget(assignment_label)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        body = QWidget()
        checks_layout = QVBoxLayout(body)
        checks = {}
        for workflow in get_workflows():
            check = QCheckBox(workflow.name)
            check.setToolTip(workflow.description)
            checks[workflow.workflow_id] = check
            checks_layout.addWidget(check)
        checks_layout.addStretch()
        scroll.setWidget(body)
        layout.addWidget(scroll)
        error_label = label("", "error")
        layout.addWidget(error_label)
        layout.addWidget(label("Changes take effect only after Save. New views start with no workflows.", "muted"))
        pending = [self.configuration]
        selected_view = [None]
        loaded_checks = [frozenset()]

        def remember() -> None:
            key = selected_view[0]
            if key is not None:
                selected = frozenset(name for name, check in checks.items() if check.isChecked())
                if selected != loaded_checks[0]:
                    views = dict(pending[0].workflows_by_view)
                    # Preserve unknown IDs until explicitly addressed, and preserve
                    # wildcard grants when the administrator has made no change.
                    unknown = views[key] - checks.keys() - {"*"}
                    views[key] = selected | unknown
                    pending[0] = replace(pending[0], workflows_by_view=views)

        def load_view() -> None:
            remember()
            selected_view[0] = view.currentData()
            allowed = pending[0].workflows_by_view.get(selected_view[0], frozenset())
            for key, check in checks.items():
                check.setChecked("*" in allowed or key in allowed)
                check.setEnabled(selected_view[0] is not None)
            loaded_checks[0] = frozenset(key for key, check in checks.items() if check.isChecked())
            assigned = sum(profile.view == selected_view[0] for profile in pending[0].users.values())
            assignment_label.setText(f"Assigned to {assigned} staff profile(s), including revoked users.")
            rename_button.setEnabled(selected_view[0] is not None)
            remove_button.setEnabled(selected_view[0] is not None)

        def refresh(selected: str | None = None) -> None:
            selected_view[0] = None
            view.blockSignals(True)
            view.clear()
            for key in sorted(pending[0].workflows_by_view):
                if key != "administrator":
                    view.addItem(key.title(), key)
            if selected is not None:
                view.setCurrentIndex(view.findData(selected))
            view.blockSignals(False)
            load_view()

        def add() -> None:
            name, accepted = QInputDialog.getText(dialog, "Add view", "New view name:")
            if not accepted:
                return
            remember()
            try:
                pending[0] = add_view(pending[0], name)
            except AccessConfigurationError as error:
                error_label.setText(str(error))
                return
            error_label.clear()
            refresh(name.strip().casefold())

        def rename() -> None:
            key = view.currentData()
            if key is None:
                return
            name, accepted = QInputDialog.getText(
                dialog, "Rename view", "New view name:", QLineEdit.EchoMode.Normal, key.title()
            )
            if not accepted:
                return
            remember()
            try:
                pending[0] = rename_view(pending[0], key, name)
            except AccessConfigurationError as error:
                error_label.setText(str(error))
                return
            error_label.clear()
            refresh(name.strip().casefold())

        def remove() -> None:
            key = view.currentData()
            if key is None:
                return
            remember()
            try:
                updated = remove_view(pending[0], key)
            except AccessConfigurationError as error:
                error_label.setText(str(error))
                return
            if QMessageBox.question(
                dialog, "Remove view", f"Remove the {key.title()} view? Staff profiles will not be deleted.",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.No,
            ) != QMessageBox.StandardButton.Yes:
                return
            pending[0] = updated
            error_label.clear()
            refresh()

        view.currentIndexChanged.connect(load_view)
        refresh()
        controls = QDialogButtonBox(QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel)
        controls.rejected.connect(dialog.reject)

        def save() -> None:
            remember()
            password = None
            if pending[0].users.get(self.owner_key) != self.configuration.users.get(self.owner_key):
                password = self._owner_password_if_needed(self.owner_key)
                if password is False:
                    return
            if self._save(pending[0], owner_password=password):
                dialog.accept()

        controls.accepted.connect(save)
        layout.addWidget(controls)
        dialog.exec()
