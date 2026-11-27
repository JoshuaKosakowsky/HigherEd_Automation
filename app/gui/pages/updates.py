"""Staff-accessible updates with background Git operations and restart gating."""

from __future__ import annotations

import queue
from threading import Thread
from typing import Callable

from PySide6.QtCore import QTimer, Signal
from PySide6.QtWidgets import QComboBox, QHBoxLayout, QProgressBar, QVBoxLayout, QWidget

from app.gui import APP_VERSION
from app.gui.services.updates import (
    UPDATE_BRANCHES, BranchSwitchPlan, EquivalentBranches, InstalledRevision,
    RepositoryUpdater, UpdateError, UpdatePlan,
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
        self.result_queue: queue.Queue[
            tuple[UpdatePlan | BranchSwitchPlan | EquivalentBranches | None, UpdateError | None]
        ] | None = None
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
        layout.addWidget(label("Close other automation tools before installing updates. Updates preserve local settings and data; local code changes require administrator review.", "muted"))
        self.branch_controls = QWidget()
        branch_row = QHBoxLayout(self.branch_controls)
        branch_row.setContentsMargins(0, 0, 0, 0)
        branch_caption = label("Update branch", wrap=False)
        self.branch_picker = QComboBox()
        self.branch_picker.setAccessibleName("Update branch")
        self.branch_picker.addItems(UPDATE_BRANCHES)
        if branch in UPDATE_BRANCHES:
            self.branch_picker.setCurrentText(branch)
        branch_caption.setBuddy(self.branch_picker)
        branch_row.addWidget(branch_caption)
        branch_row.addWidget(self.branch_picker)
        branch_row.addStretch()
        self.branch_controls.setVisible(bool(branch in UPDATE_BRANCHES and self.updater.can_switch_branch()))
        layout.addWidget(self.branch_controls)
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
        self.close_button = button("Close app", close_app)
        self.close_button.hide()
        for control in (self.check_button, self.install_button, self.close_button):
            layout.addWidget(control)
        self.branch_picker.currentTextChanged.connect(self._branch_selection_changed)
        layout.addStretch()
        self.timer = QTimer(self)
        self.timer.setInterval(100)
        self.timer.timeout.connect(self._poll)

    def _show_branch(self, branch: str | None) -> None:
        self.installed_branch = branch
        name = "Detached HEAD" if branch == "HEAD" else branch or "Unavailable"
        self.branch_label.setText(f"Installation branch · {name}")

    def _branch_selection_changed(self, branch: str) -> None:
        self.plan = None
        self.install_button.setText("Install update")
        self.install_button.setEnabled(False)
        self.status.setText(f"Ready to check {branch} for updates.")

    def _start(self, *, install: bool) -> None:
        if self.result_queue is not None or self.needs_restart or (install and not self.plan):
            return
        plan = self.plan
        self.plan = None
        selected = self.branch_picker.currentText() if not self.branch_controls.isHidden() else None
        other_branch = selected if selected != self.installed_branch else None
        results = queue.Queue()
        self.result_queue = results
        self.check_button.setEnabled(False)
        self.install_button.setEnabled(False)
        self.branch_picker.setEnabled(False)
        if not install and selected:
            self.status.setText(f"Checking {selected} for updates…")
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
                    results.put((self.updater.check(compare_branches=selected is not None), None))
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
        elif isinstance(plan, EquivalentBranches):
            message = f"main and Development are on the same commit ({plan.shared_commit[:12]})."
            if plan.installed_commit != plan.shared_commit:
                message += f" Select {plan.installed_branch} to check for an update on this installation's branch."
            self.status.setText(message)
        else:
            self.plan = plan
            if isinstance(plan, BranchSwitchPlan):
                message = f"{plan.branch} offers version {plan.version} • Git {plan.target_commit[:12]}\n"
                message += f"Installing this revision will make this installation follow {plan.branch}."
            elif plan.branches_equivalent:
                message = f"main and Development are on the same commit ({plan.target_commit[:12]}). Your installation is up to date."
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
        self.branch_picker.setEnabled(not self.needs_restart)
        self.busy_changed.emit(False)
