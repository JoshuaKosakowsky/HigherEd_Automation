"""Staff sign-in, separate from department-level environment provisioning."""

from __future__ import annotations

import queue
from datetime import datetime
from typing import Callable

from PySide6.QtCore import Qt, QTimer, Signal
from PySide6.QtWidgets import QComboBox, QHBoxLayout, QMessageBox, QProgressBar, QVBoxLayout, QWidget

from app.gui.models import WorkflowContext, WorkflowDefinition, WorkflowMode
from app.gui.services.execution import WorkflowExecutor
from app.gui.services.insights import run_insights_connection
from app.gui.theme import button, card, label
from shared.insights.config import InsightsConfigurationError, load_department_profiles


class ConnectionsPage(QWidget):
    busy_changed = Signal(bool)

    def __init__(self, parent, executor: WorkflowExecutor, authorize: Callable[[], bool]):
        super().__init__(parent)
        self.executor = executor
        self.authorize = authorize
        self.result_queue = None
        self.statuses: dict[str, str] = {}
        self.setObjectName("page")
        layout = QVBoxLayout(self)
        layout.setContentsMargins(36, 30, 36, 30)
        layout.setSpacing(16)
        layout.addWidget(label("Connections", "title"))
        layout.addWidget(label("Ellucian Insights", "section"))
        layout.addWidget(label(
            "Environment setup is supplied by the department. You only sign in "
            "with your own MyMines account when your session needs renewing.", "muted"
        ))
        self.profiles = {}
        self.config_error = None
        try:
            self.profiles = load_department_profiles()
        except InsightsConfigurationError as error:
            self.config_error = str(error)
        panel, controls = card()
        self.mode = QComboBox()
        self.mode.setAccessibleName("Insights environment")
        self.mode.addItem("TEST", "TEST")
        self.mode.addItem("PROD", "PROD")
        controls.addWidget(label("Environment", "field"))
        controls.addWidget(self.mode)
        self.instructions = label("")
        self.instructions.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        controls.addWidget(self.instructions)
        row = QHBoxLayout()
        self.actions = {}
        for action, title in (
            ("connect", "Connect and sign in"), ("check", "Check connection"),
            ("reconnect", "Sign in again"), ("logout", "Sign out"),
        ):
            control = button(title, lambda checked=False, value=action: self._run(value),
                             "primary" if action == "connect" else "")
            self.actions[action] = control
            row.addWidget(control)
        controls.addLayout(row)
        layout.addWidget(panel)
        self.progress = QProgressBar()
        self.progress.setRange(0, 0)
        self.progress.hide()
        layout.addWidget(self.progress)
        self.status_label = label("", "status")
        layout.addWidget(self.status_label)
        layout.addStretch()
        self.mode.currentIndexChanged.connect(self._refresh)
        self.timer = QTimer(self)
        self.timer.setInterval(100)
        self.timer.timeout.connect(self._poll)
        self._refresh()

    def _refresh(self) -> None:
        environment = self.mode.currentData()
        profile = self.profiles.get(environment)
        for control in self.actions.values():
            control.setEnabled(profile is not None and self.result_queue is None)
        if profile is None:
            self.instructions.setText(self.config_error or (
                f"{environment} is not configured for the department yet. "
                "The application owner configures it once, not each employee."
            ))
        else:
            self.instructions.setText(
                f"Connect opens MyMines. After signing in, open {profile.experience_url} "
                f"in that same window, then launch Insights {environment}.\n\n"
                "The dedicated automation browser closes after the handoff or a "
                "five-minute timeout. Return here for the result. Its local profile "
                "can retain persistent SSO recognition for future automation; the "
                "API session is saved separately in your OS credential vault."
            )
        self.status_label.setText(self.statuses.get(environment, "Not checked in this view. No login is performed until you click Connect."))

    def _run(self, action: str) -> None:
        if self.result_queue is not None or self.executor.is_running or not self.authorize():
            return
        environment = self.mode.currentData()
        if not self.profiles.get(environment):
            return
        if environment == "PROD" and action != "logout":
            answer = QMessageBox.question(
                self, "Confirm production connection",
                "Connect to the production Insights environment? This check runs SELECT 1 only.",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.No,
            )
            if answer != QMessageBox.StandardButton.Yes:
                return
        definition = WorkflowDefinition("insights_connection", "Insights connection", "", "Connections", run_insights_connection)
        context = WorkflowContext(definition.workflow_id, {"action": action}, WorkflowMode(environment))
        try:
            self.result_queue = self.executor.run_async(definition, context)
        except RuntimeError:
            self.status_label.setText("Another task is running. Wait for it to finish.")
            return
        self.running_environment = environment
        self.mode.setEnabled(False)
        self._refresh()
        self.status_label.setText("Working… If a browser opens, complete sign-in there and return here for the result.")
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
        self.busy_changed.emit(False)
