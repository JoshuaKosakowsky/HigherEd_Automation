"""Staff-accessible updates with background Git operations and restart gating."""

from __future__ import annotations

import queue
from threading import Thread
from typing import Callable

from PySide6.QtCore import QTimer, Signal
from PySide6.QtWidgets import QProgressBar, QVBoxLayout, QWidget

from app.gui import APP_VERSION
from app.gui.services.updates import (
    BranchSwitchPlan, InstalledRevision, RepositoryUpdater, UpdateError, UpdatePlan,
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
        self.plan: UpdatePlan | BranchSwitchPlan | None = None
        self.result_queue: queue.Queue[tuple[UpdatePlan | BranchSwitchPlan | None, UpdateError | None]] | None = None
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
        other_branch = {"main": "Development", "Development": "main"}.get(branch)
        other_updates = "development" if branch == "main" else "stable"
        self.check_other_button = button(f"Check for {other_updates} updates",
                                         lambda: self._start(install=False, other_branch=other_branch))
        self.check_other_button.setVisible(bool(other_branch and self.updater.can_switch_branch()))
        self.close_button = button("Close app", close_app)
        self.close_button.hide()
        for control in (self.check_button, self.check_other_button, self.install_button, self.close_button):
            layout.addWidget(control)
        layout.addStretch()
        self.timer = QTimer(self)
        self.timer.setInterval(100)
        self.timer.timeout.connect(self._poll)

    def _show_branch(self, branch: str | None) -> None:
        name = "Detached HEAD" if branch == "HEAD" else branch or "Unavailable"
        self.branch_label.setText(f"Installation branch · {name}")

    def _start(self, *, install: bool, other_branch: str | None = None) -> None:
        if self.result_queue is not None or self.needs_restart or (install and not self.plan):
            return
        plan = self.plan
        self.plan = None
        results = queue.Queue()
        self.result_queue = results
        self.check_button.setEnabled(False)
        self.install_button.setEnabled(False)
        self.check_other_button.setEnabled(False)
        if other_branch:
            self.status.setText(f"Checking {other_branch} for updates…")
        else:
            self.status.setText("Installing update…" if install else "Checking update source…")
        self.progress.show()
        self.busy_changed.emit(True)

        def work() -> None:
            try:
                if install:
                    if isinstance(plan, BranchSwitchPlan):
                        self.updater.switch_branch(plan)
                    else:
                        self.updater.install(plan)
                    results.put((plan, None))
                elif other_branch:
                    results.put((self.updater.check_branch(other_branch), None))
                else:
                    results.put((self.updater.check(), None))
            except UpdateError as error:
                results.put((None, error))
            except Exception:
                # Outer worker boundary: always release the GUI, without copying
                # potentially sensitive exception details into the staff UI.
                results.put((None, UpdateError("The update operation failed. Ask your administrator to inspect the installation.",
                                               restart_required=install)))

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
        elif self.installing:
            self.needs_restart = True
            if isinstance(plan, BranchSwitchPlan):
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
            if isinstance(plan, BranchSwitchPlan):
                message = f"{plan.branch} offers version {plan.version} • Git {plan.target_commit[:12]}\n"
                message += f"Installing this revision will make this installation follow {plan.branch}."
            else:
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
        branch_preview = isinstance(self.plan, BranchSwitchPlan)
        self.install_button.setText(f"Install from {self.plan.branch}" if branch_preview else "Install update")
        self.install_button.setEnabled(bool(self.plan and (branch_preview or self.plan.commit_count)) and not self.needs_restart)
        self.check_other_button.setEnabled(not self.needs_restart)
        self.busy_changed.emit(False)
