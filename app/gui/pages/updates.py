"""Staff-accessible updates with background Git operations and restart gating."""

from __future__ import annotations

import queue
from threading import Thread
from typing import Callable

from PySide6.QtCore import QTimer, Signal
from PySide6.QtWidgets import QMessageBox, QProgressBar, QVBoxLayout, QWidget

from app.gui import APP_VERSION
from app.gui.services.updates import (
    UPDATE_BRANCHES, BranchSwitchResult, InstalledRevision, RepositoryUpdater, UpdateError, UpdatePlan,
)
from app.gui.theme import button, label


class UpdatesPage(QWidget):
    busy_changed = Signal(bool)
    restart_required = Signal()

    def __init__(self, parent, updater: RepositoryUpdater, close_app: Callable[[], None],
                 running_revision: InstalledRevision | None) -> None:
        super().__init__(parent)
        self.setObjectName("page")
        self.updater = updater
        self.plan: UpdatePlan | None = None
        self.result_queue: queue.Queue[tuple[UpdatePlan | BranchSwitchResult | None, UpdateError | None]] | None = None
        self.needs_restart = False
        self.installing = False
        layout = QVBoxLayout(self)
        layout.setContentsMargins(36, 30, 36, 30)
        layout.setSpacing(18)
        layout.addWidget(label("App updates", "title"))
        revision = f" • Git {running_revision.commit}" if running_revision else ""
        layout.addWidget(label(f"Running version {APP_VERSION}{revision}", "muted"))
        branch = running_revision.branch if running_revision else None
        self.branch_label = label("", "muted")
        self._show_branch(branch)
        layout.addWidget(self.branch_label)
        layout.addWidget(label("Check for updates from your installation's configured source. Close other automation tools before installing. Updates preserve local settings and data; local code changes require administrator review.", "muted"))
        self.status = label("Ready to check for updates.", "status")
        layout.addWidget(self.status)
        self.progress = QProgressBar()
        self.progress.setRange(0, 0)
        self.progress.setAccessibleName("App update operation")
        self.progress.hide()
        layout.addWidget(self.progress)
        self.check_button = button("Check for updates", lambda: self._start(install=False), "primary")
        self.install_button = button("Install update", lambda: self._start(install=True), "primary")
        self.install_button.setEnabled(False)
        self.switch_target = next((name for name in UPDATE_BRANCHES if name != branch), None) if (
            branch in UPDATE_BRANCHES
        ) else None
        self.switch_button = button(f"Switch to {self.switch_target}" if self.switch_target else "Switch branch",
                                    self._confirm_switch)
        self.switch_button.setVisible(bool(self.switch_target and self.updater.can_switch_branch()))
        self.close_button = button("Close app", close_app)
        self.close_button.hide()
        for control in (self.check_button, self.install_button, self.switch_button, self.close_button):
            layout.addWidget(control)
        layout.addStretch()
        self.timer = QTimer(self)
        self.timer.setInterval(100)
        self.timer.timeout.connect(self._poll)

    def _show_branch(self, branch: str | None) -> None:
        name = "Detached HEAD" if branch == "HEAD" else branch or "Unavailable"
        self.branch_label.setText(f"Installation branch · {name}")

    def _confirm_switch(self) -> None:
        if self.switch_target is None or self.switch_button.isHidden() or self.needs_restart or self.result_queue is not None:
            return
        answer = QMessageBox.question(
            self, "Switch update branch",
            f"Switch this installation to {self.switch_target}? Close other automation tools first. "
            "You will need to close and reopen the app after switching.",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if answer == QMessageBox.StandardButton.Yes:
            self._start(install=False, switch_to=self.switch_target)

    def _start(self, *, install: bool, switch_to: str | None = None) -> None:
        if self.result_queue is not None or self.needs_restart or (install and not self.plan):
            return
        plan = self.plan
        self.plan = None
        results = queue.Queue()
        self.result_queue = results
        self.check_button.setEnabled(False)
        self.install_button.setEnabled(False)
        self.switch_button.setEnabled(False)
        if switch_to:
            self.status.setText(f"Switching to {switch_to}…")
        else:
            self.status.setText("Installing update…" if install else "Checking update source…")
        self.progress.show()
        self.busy_changed.emit(True)

        def work() -> None:
            try:
                if switch_to:
                    results.put((self.updater.switch_branch(switch_to), None))
                elif install:
                    self.updater.install(plan)
                    results.put((plan, None))
                else:
                    results.put((self.updater.check(), None))
            except UpdateError as error:
                results.put((None, error))
            except Exception:
                # Outer worker boundary: always release the GUI, without copying
                # potentially sensitive exception details into the staff UI.
                results.put((None, UpdateError("The update operation failed. Ask your administrator to inspect the installation.",
                                               restart_required=install or switch_to is not None)))

        self.installing = install
        Thread(target=work, daemon=True).start()
        self.timer.start()

    def _poll(self) -> None:
        if self.result_queue is None:
            return
        try:
            plan, error = self.result_queue.get_nowait()
        except queue.Empty:
            return
        self.timer.stop()
        self.result_queue = None
        self.progress.hide()
        if error:
            self.status.setText(str(error))
            self.needs_restart = error.restart_required
        elif self.installing or isinstance(plan, BranchSwitchResult):
            self.needs_restart = True
            if isinstance(plan, BranchSwitchResult):
                self._show_branch(plan.branch)
                message = f"Installation switched to {plan.branch}."
            else:
                message = "Update installed."
            message += " Close the app and reopen it using your usual shortcut before running workflows."
            if plan.setup_required:
                message += " Setup components changed. Ask your administrator to run setup.ps1 before reopening."
            self.status.setText(message)
        else:
            self.plan = plan
            message = f"Source: {plan.remote} • Branch: {plan.branch}\n"
            message += (f"{plan.commit_count} new commit(s) available. Install update when ready."
                        if plan.commit_count else "Your installation is up to date.")
            if plan.setup_required:
                message += "\nSetup must be run again after installation; coordinate with your administrator before installing."
            self.status.setText(message)
        if self.needs_restart:
            self.restart_required.emit()
            self.close_button.show()
        self.check_button.setEnabled(not self.needs_restart)
        self.install_button.setEnabled(bool(self.plan and self.plan.commit_count) and not self.needs_restart)
        self.switch_button.setEnabled(not self.needs_restart)
        self.busy_changed.emit(False)
