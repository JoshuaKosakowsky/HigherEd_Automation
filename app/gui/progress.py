"""Shared accessible progress display for every registered workflow."""

from time import monotonic

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QProgressBar, QVBoxLayout, QWidget

from app.gui.theme import label
from shared.progress import ProgressUpdate


class WorkflowProgressWidget(QWidget):
    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        self.stage_label = label("", "status")
        self.stage_label.setAccessibleName("Current workflow stage")
        self.bar = QProgressBar(self)
        self.bar.setObjectName("workflowProgressBar")
        self.bar.setAccessibleName("Current stage progress")
        self.bar.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.bar.setTextVisible(True)
        self.time_label = label("", "muted")
        self.time_label.setAccessibleName("Workflow elapsed time")
        for widget in (self.stage_label, self.bar, self.time_label):
            layout.addWidget(widget)
        self._started = 0.0
        self._update: ProgressUpdate | None = None
        self.hide()

    def start(self) -> None:
        self._started = monotonic()
        self._update = None
        self.refresh(ProgressUpdate("Starting workflow"))
        self.show()

    def refresh(self, update: ProgressUpdate | None) -> None:
        if update is not None and update != self._update:
            self._update = update
            description = update.stage
            if update.percent is None:
                self.bar.setRange(0, 0)
                self.bar.setFormat("Working…")
                description += " — in progress; total work is not yet known"
            else:
                self.bar.setRange(0, 100)
                self.bar.setValue(update.percent)
                self.bar.setFormat("%p% of this stage")
                description += f" — {update.completed:,} of {update.total:,} completed"
                description += f" ({update.percent}% of this stage)"
            self.stage_label.setText(description)
            self.stage_label.setAccessibleName(f"Current workflow stage: {description}")
            self.bar.setAccessibleDescription(description)
        elapsed = max(0, int(monotonic() - self._started))
        minutes, seconds = divmod(elapsed, 60)
        self.time_label.setText(f"Elapsed: {minutes:02d}:{seconds:02d}")
        self.time_label.setAccessibleName(self.time_label.text())

    def finish(self, *, success: bool, cancelled: bool) -> None:
        self.refresh(None)
        stage = self._update.stage if self._update else "Starting workflow"
        text = "Completed" if success else f"{'Cancelled' if cancelled else 'Stopped'} during: {stage}"
        self.stage_label.setText(text)
        self.stage_label.setAccessibleName(text)
        if success or self.bar.maximum() == 0:
            self.bar.setRange(0, 100)
            self.bar.setValue(100 if success else 0)
        self.bar.setFormat("Completed" if success else "Stopped")
        self.bar.setAccessibleDescription(text)
