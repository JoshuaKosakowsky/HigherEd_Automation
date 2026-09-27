"""Staff sign-in, separate from department-level environment provisioning."""

from __future__ import annotations

import queue
from datetime import datetime
from pathlib import Path
from typing import Callable

from PySide6.QtCore import Qt, QTimer, Signal
from PySide6.QtWidgets import (
    QFileDialog, QComboBox, QDialog, QDialogButtonBox, QFormLayout,
    QHBoxLayout, QLineEdit, QMessageBox, QProgressBar, QScrollArea,
    QVBoxLayout, QWidget,
)

from app.gui.models import WorkflowContext, WorkflowDefinition, WorkflowMode
from app.gui.services.execution import WorkflowExecutor
from app.gui.services.insights import run_insights_connection
from app.gui.theme import button, card, label
from mymines.credentials import MyMinesCredentialStore
from shared.credentials import CredentialStoreError
from shared.insights.config import InsightsConfigurationError, load_department_profiles
from shared.insights.query_catalog import QUERIES, get_query


class ConnectionsPage(QScrollArea):
    busy_changed = Signal(bool)

    def __init__(self, parent, executor: WorkflowExecutor, authorize: Callable[[], bool]):
        super().__init__(parent)
        self.executor = executor
        self.authorize = authorize
        self.result_queue = None
        self.statuses: dict[str, str] = {}
        self.setWidgetResizable(True)
        body = QWidget()
        body.setObjectName("page")
        self.setWidget(body)
        layout = QVBoxLayout(body)
        layout.setContentsMargins(36, 30, 36, 30)
        layout.setSpacing(18)
        layout.addWidget(label("INSIGHTS / ADMIN CONNECTIONS", "eyebrow"))
        layout.addWidget(label("Connections", "title"))
        layout.addWidget(label(
            "Connect to Ellucian Insights, manage your MyMines login, and export approved reports.",
            "muted",
        ))
        self.profiles = {}
        self.config_error = None
        try:
            self.profiles = load_department_profiles()
        except InsightsConfigurationError as error:
            self.config_error = str(error)

        connection_card, connection = card()
        heading = QHBoxLayout()
        heading.addWidget(label("Insights connection", "section"), 1)
        environment = QVBoxLayout()
        environment.setSpacing(4)
        environment.addWidget(label("Environment", "field"))
        self.mode = QComboBox()
        self.mode.setAccessibleName("Insights environment")
        self.mode.setMinimumWidth(160)
        self.mode.addItem("TEST", "TEST")
        self.mode.addItem("PROD", "PROD")
        environment.addWidget(self.mode)
        heading.addLayout(environment)
        connection.addLayout(heading)
        self.instructions = label("")
        self.instructions.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        connection.addWidget(self.instructions)
        self.status_label = label("", "status")
        connection.addWidget(self.status_label)
        primary_actions = QHBoxLayout()
        secondary_actions = QHBoxLayout()
        self.actions = {}
        for action, title, target in (
            ("connect", "Connect and sign in", primary_actions),
            ("check", "Check connection", primary_actions),
            ("reconnect", "Sign in again", secondary_actions),
            ("logout", "Sign out", secondary_actions),
        ):
            control = button(title, lambda checked=False, value=action: self._run(value),
                             "primary" if action == "connect" else "")
            self.actions[action] = control
            target.addWidget(control)
        primary_actions.addStretch()
        secondary_actions.addStretch()
        connection.addLayout(primary_actions)
        connection.addLayout(secondary_actions)
        self.progress = QProgressBar()
        self.progress.setRange(0, 0)
        self.progress.setTextVisible(False)
        self.progress.hide()
        connection.addWidget(self.progress)
        layout.addWidget(connection_card)

        login_card, login = card()
        login.addWidget(label("MyMines autofill", "section"))
        login.addWidget(label(
            "Optional. Save your login on this computer; complete MFA in the browser when prompted.",
            "muted",
        ))
        self.credential_status = label("", "muted")
        login.addWidget(self.credential_status)
        credentials_row = QHBoxLayout()
        self.save_login_button = button("Set or update saved login", self._save_mines_login)
        self.remove_login_button = button("Remove saved login", self._remove_mines_login)
        credentials_row.addWidget(self.save_login_button)
        credentials_row.addWidget(self.remove_login_button)
        credentials_row.addStretch()
        login.addLayout(credentials_row)
        layout.addWidget(login_card)

        export_card, export = card()
        export.addWidget(label("Export an approved report", "section"))
        export.addWidget(label("Choose a report and save the workbook to an approved location.", "muted"))
        export.addWidget(label("Report", "field"))
        self.queries = QComboBox()
        self.queries.setAccessibleName("Insights query")
        for query in QUERIES:
            self.queries.addItem(f"{query.group} — {query.title}", query.query_id)
        export.addWidget(self.queries)
        self.query_description = label("", "muted")
        export.addWidget(self.query_description)
        self.term_label = label("Banner term", "field")
        self.term = QLineEdit()
        self.term.setAccessibleName("Banner term for selected query")
        self.term.setPlaceholderText("Six-digit term, for example 202680")
        export.addWidget(self.term_label)
        export.addWidget(self.term)
        export.addWidget(label("Reports may contain student and financial data.", "muted"))
        self.actions["query_export"] = button(
            "Run selected query and save Excel",
            lambda checked=False: self._run("query_export"),
            "primary",
        )
        export_actions = QHBoxLayout()
        export_actions.addWidget(self.actions["query_export"])
        export_actions.addStretch()
        export.addLayout(export_actions)
        layout.addWidget(export_card)
        layout.addStretch()
        self.mode.currentIndexChanged.connect(self._refresh)
        self.queries.currentIndexChanged.connect(self._refresh_query)
        self.timer = QTimer(self)
        self.timer.setInterval(100)
        self.timer.timeout.connect(self._poll)
        self._refresh_query()
        self._refresh()

    def _refresh_query(self) -> None:
        query = get_query(self.queries.currentData())
        self.query_description.setText(query.description)
        requires_term = query.term_variable is not None
        self.term_label.setVisible(requires_term)
        self.term.setVisible(requires_term)

    def _refresh(self) -> None:
        environment = self.mode.currentData()
        profile = self.profiles.get(environment)
        for control in self.actions.values():
            control.setEnabled(profile is not None and self.result_queue is None)
        self.queries.setEnabled(profile is not None and self.result_queue is None)
        self.term.setEnabled(profile is not None and self.result_queue is None)
        self.save_login_button.setEnabled(self.result_queue is None)
        self.remove_login_button.setEnabled(self.result_queue is None)
        try:
            saved = MyMinesCredentialStore().load()
        except CredentialStoreError:
            self.credential_status.setText("The saved MyMines login could not be read. Update it to use autofill.")
        else:
            self.credential_status.setText(
                f"Saved for {saved.username}. MFA stays with you."
                if saved else "No MyMines login saved. You can still sign in manually."
            )
        if profile is None:
            self.instructions.setText(self.config_error or (
                f"{environment} is not configured for the department yet. "
                "The application owner configures it once, not each employee."
            ))
            self.instructions.setToolTip("")
        else:
            self.instructions.setText(
                f"Connect opens MyMines and launches {environment} Insights. "
                "Complete MFA in the browser if prompted."
            )
            self.instructions.setToolTip(
                f"If automatic navigation stops, open {profile.experience_url} "
                "in the same browser and select Reporting → Insights."
            )
        self.status_label.setText(self.statuses.get(environment, "No connection checked yet."))

    def _save_mines_login(self) -> None:
        if self.result_queue is not None or not self.authorize():
            return
        dialog = QDialog(self)
        dialog.setWindowTitle("Save MyMines login")
        layout = QVBoxLayout(dialog)
        layout.addWidget(label(
            "Saved locally in Windows Credential Manager or macOS Keychain. "
            "Only MyMines sign-in uses this password; you complete MFA yourself.",
            "muted",
        ))
        form = QFormLayout()
        username = QLineEdit()
        username.setAccessibleName("MyMines username")
        password = QLineEdit()
        password.setAccessibleName("MyMines password")
        password.setEchoMode(QLineEdit.EchoMode.Password)
        form.addRow("Username", username)
        form.addRow("Password", password)
        layout.addLayout(form)
        error_label = label("", "error")
        layout.addWidget(error_label)
        controls = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel
        )

        def save() -> None:
            try:
                MyMinesCredentialStore().save(username.text(), password.text())
            except (ValueError, CredentialStoreError) as error:
                error_label.setText(str(error))
                return
            password.clear()
            dialog.accept()

        controls.accepted.connect(save)
        controls.rejected.connect(dialog.reject)
        layout.addWidget(controls)
        dialog.exec()
        password.clear()
        self._refresh()

    def _remove_mines_login(self) -> None:
        if self.result_queue is not None or not self.authorize():
            return
        try:
            MyMinesCredentialStore().delete()
        except CredentialStoreError as error:
            QMessageBox.warning(self, "Saved login unavailable", str(error))
        self._refresh()

    def _run(self, action: str) -> None:
        if self.result_queue is not None or self.executor.is_running or not self.authorize():
            return
        environment = self.mode.currentData()
        if not self.profiles.get(environment):
            return
        if action == "query_export":
            query = get_query(self.queries.currentData())
            term_code = self.term.text().strip() if query.term_variable else None
            try:
                query.render_sql(term_code)
            except (OSError, ValueError) as error:
                QMessageBox.warning(self, "Query input needed", str(error))
                return
            suggested_name = (
                f"{query.query_id}_{environment.lower()}_"
                f"{datetime.now():%Y%m%d_%H%M%S}.xlsx"
            )
            filename, _ = QFileDialog.getSaveFileName(
                self, f"Save {query.title}",
                str(Path.home() / suggested_name), "Excel workbooks (*.xlsx)",
            )
            if not filename:
                return
            if not self.authorize():
                return
            output_path = Path(filename).resolve()
            if output_path.exists():
                QMessageBox.warning(
                    self, "Workbook already exists", "Choose a new filename for this export."
                )
                return
            parameters = {
                "action": action,
                "query_id": query.query_id,
                "output_path": str(output_path),
            }
            if term_code is not None:
                parameters["term_code"] = term_code
        else:
            parameters = {"action": action}
        is_query = action == "query_export"
        workflow_id = "insights_query_export" if is_query else "insights_connection"
        title = "Insights query export" if is_query else "Insights connection"
        definition = WorkflowDefinition(
            workflow_id, title, "", "Connections", run_insights_connection,
        )
        context = WorkflowContext(definition.workflow_id, parameters, WorkflowMode(environment))
        try:
            self.result_queue = self.executor.run_async(definition, context)
        except RuntimeError:
            self.status_label.setText("Another task is running. Wait for it to finish.")
            return
        self.running_environment = environment
        self.mode.setEnabled(False)
        self._refresh()
        self.status_label.setText("Working… If a browser opens, complete sign-in there and return here for the result.")
        self.verticalScrollBar().setValue(0)
        self.progress.show()
        self.busy_changed.emit(True)
        self.timer.start()

    def _poll(self) -> None:
        if self.result_queue is None:
            return
        try:
            result = self.result_queue.get_nowait()
        except queue.Empty:
            return
        self.timer.stop()
        self.result_queue = None
        self.statuses[self.running_environment] = (
            f"Last result at {datetime.now():%H:%M:%S} — " + result.message
        )
        self.mode.setEnabled(True)
        self.progress.hide()
        self._refresh()
        self.verticalScrollBar().setValue(0)
        self.busy_changed.emit(False)
