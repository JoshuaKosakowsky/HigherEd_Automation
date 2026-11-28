"""Cashier queue, page preview and editable redaction marks."""

from __future__ import annotations

from pathlib import Path
import sqlite3
import subprocess
import sys

from PySide6.QtCore import QPointF, QRectF, Qt, QTimer
from PySide6.QtGui import QColor, QImage, QPainter, QPen
from PySide6.QtWidgets import (
    QApplication, QCheckBox, QComboBox, QDialog, QDialogButtonBox, QFormLayout,
    QHBoxLayout, QLabel, QLineEdit, QListWidget, QListWidgetItem, QMessageBox,
    QPlainTextEdit, QPushButton, QScrollArea, QVBoxLayout, QWidget,
)

from app.gui.services.check_scanning import start_check_scan_process
from app.gui.theme import apply_theme, label
from shared.mines_paths import get_papercut_scan_directory
from workflows.check_scanning.detection import Box, Mark
from workflows.check_scanning.documents import page_count, page_pixels
from workflows.check_scanning.intake import (
    ScanQueue, check_scan_output_directory, decode_finding, missing_redactions,
    queue_path, review_output_path,
)


def control(text, action, layout):
    widget = QPushButton(text)
    widget.setAutoDefault(False)
    widget.clicked.connect(action)
    layout.addWidget(widget)
    return widget


class PageCanvas(QWidget):
    def __init__(self, review):
        super().__init__()
        self.review = review
        self.image = QImage()
        self.selected = None
        self.drag = None
        self.original_marks = []
        self.scale = 1.0
        self.setMouseTracking(True)

    def load(self, source, page):
        pixels = page_pixels(source, page)
        h, w = pixels.shape[:2]
        self.image = QImage(pixels.data, w, h, pixels.strides[0], QImage.Format.Format_BGR888).copy()
        self.selected = self.drag = None
        self.fit()

    def fit(self):
        size = self.review.scroll.viewport().size()
        self.scale = min(max(200, size.width()-5) / self.image.width(),
                         max(200, size.height()-5) / self.image.height())
        self.zoom(1)

    def zoom(self, factor):
        self.scale = max(.05, min(4, self.scale * factor))
        self.setFixedSize(max(1, round(self.image.width()*self.scale)),
                          max(1, round(self.image.height()*self.scale)))
        self.update()

    def box_rect(self, box):
        return QRectF(box.left*self.width(), box.top*self.height(),
                      (box.right-box.left)*self.width(), (box.bottom-box.top)*self.height())

    def paintEvent(self, event):
        p = QPainter(self)
        p.drawImage(QRectF(self.rect()), self.image)
        for i, mark in enumerate(self.review.marks):
            if mark.page != self.review.page:
                continue
            rect = self.box_rect(mark.box)
            if self.review.preview.isChecked():
                p.fillRect(rect, Qt.GlobalColor.black)
                continue
            color = QColor("#d14627" if mark.kind == "MICR" else "#175ec2")
            p.setPen(QPen(color, 3 if i == self.selected else 2))
            p.setBrush(QColor(color.red(), color.green(), color.blue(), 55))
            p.drawRect(rect)
            if i == self.selected:
                for point in (rect.topLeft(), rect.topRight(), rect.bottomLeft(), rect.bottomRight()):
                    p.fillRect(QRectF(point.x()-4, point.y()-4, 8, 8), color)
        p.end()

    def position(self, event):
        point = event.position()
        return QPointF(min(1., max(0., point.x()/self.width())),
                       min(1., max(0., point.y()/self.height())))

    def mousePressEvent(self, event):
        if event.button() != Qt.MouseButton.LeftButton or self.review.preview.isChecked():
            return
        start = self.position(event)
        self.original_marks = self.review.marks.copy()
        self.review.approve.setEnabled(False)
        self.selected = None
        for i in reversed(range(len(self.review.marks))):
            mark = self.review.marks[i]
            if mark.page != self.review.page:
                continue
            rect = self.box_rect(mark.box)
            if rect.adjusted(-6, -6, 6, 6).contains(event.position()):
                self.selected = i
                for corner, opposite in ((rect.topLeft(), rect.bottomRight()), (rect.bottomRight(), rect.topLeft()),
                                         (rect.topRight(), rect.bottomLeft()), (rect.bottomLeft(), rect.topRight())):
                    if (corner - event.position()).manhattanLength() <= 14:
                        self.drag = ("resize", QPointF(opposite.x()/self.width(), opposite.y()/self.height()), mark)
                        break
                else:
                    self.drag = ("move", start, mark)
                break
        else:
            self.selected = len(self.review.marks)
            mark = Mark(self.review.page, self.review.kind.currentText(), Box(start.x(), start.y(), start.x(), start.y()))
            self.review.marks.append(mark)
            self.drag = ("resize", start, mark)
        self.update()

    def mouseMoveEvent(self, event):
        if not self.drag:
            return
        mode, start, mark = self.drag
        point, b = self.position(event), mark.box
        if mode == "move":
            dx = min(1-b.right, max(-b.left, point.x()-start.x()))
            dy = min(1-b.bottom, max(-b.top, point.y()-start.y()))
            box = Box(b.left+dx, b.top+dy, b.right+dx, b.bottom+dy)
        else:
            box = Box(min(start.x(), point.x()), min(start.y(), point.y()),
                      max(start.x(), point.x()), max(start.y(), point.y()))
        self.review.marks[self.selected] = Mark(mark.page, mark.kind, box)
        self.update()

    def mouseReleaseEvent(self, event):
        if self.drag:
            self.mouseMoveEvent(event)
            b = self.review.marks[self.selected].box
            if b.left == b.right or b.top == b.bottom:
                self.review.marks.pop(self.selected)
                self.selected = None
            self.drag = None
            if self.review.marks == self.original_marks:
                self.review.update_approval()
            else:
                self.review.history.append(self.original_marks)
                self.review.review_changed()
            self.update()


class CheckReview(QDialog):
    def __init__(self, parent, queue, record, previous_output: Path | None = None):
        super().__init__(parent)
        self.queue, self.record = queue, record
        self.saved_path: Path | None = None
        self.marked_unrelated = False
        self.source = queue.source(record)
        self.count = page_count(self.source)
        finding = decode_finding(record)
        self.marks, self.history, self.visited = finding.marks, [], set()
        self.page = 0
        self.setWindowTitle("Review check and backup pages")
        self.resize(1050, 850)
        layout = QVBoxLayout(self)
        if previous_output is not None:
            layout.addWidget(QLabel(f"Saved {previous_output.name}", textFormat=Qt.TextFormat.PlainText))
        layout.addWidget(QLabel(record["name"], textFormat=Qt.TextFormat.PlainText))
        missing = missing_redactions(self.marks)
        toolbar = QHBoxLayout()
        layout.addLayout(toolbar)
        self.prev = control("Previous page", lambda: self.show_page(self.page-1), toolbar)
        self.page_label = QLabel()
        toolbar.addWidget(self.page_label)
        self.next = control("Next page", lambda: self.show_page(self.page+1), toolbar)
        toolbar.addStretch()
        control("Fit page", lambda: self.canvas.fit(), toolbar)
        control("Zoom in", lambda: self.canvas.zoom(1.3), toolbar)
        control("Zoom out", lambda: self.canvas.zoom(1/1.3), toolbar)
        self.preview = QCheckBox("Redacted preview")
        toolbar.addWidget(self.preview)
        self.scroll = QScrollArea()
        self.scroll.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.canvas = PageCanvas(self)
        self.scroll.setWidget(self.canvas)
        layout.addWidget(self.scroll, 1)
        edit = QHBoxLayout()
        layout.addLayout(edit)
        edit.addWidget(QLabel("Draw a box"))
        self.kind = QComboBox()
        self.kind.addItems(["MICR", "Signature", "Other"])
        if len(missing) == 1:
            self.kind.setCurrentText(missing[0])
        edit.addWidget(self.kind)
        edit.addWidget(QLabel("Drag inside to move. Drag a corner to resize."))
        edit.addStretch()
        control("Delete selected", self.remove, edit)
        control("Undo", self.undo, edit)
        self.preview.toggled.connect(lambda _: self.canvas.update())
        form = QFormLayout()
        layout.addLayout(form)
        self.issuer = QLineEdit(finding.issuer)
        self.number = QLineEdit(finding.number)
        form.addRow("Company / issuer", self.issuer)
        form.addRow("Check number", self.number)
        self.destination = QLabel(textFormat=Qt.TextFormat.PlainText, wordWrap=True)
        form.addRow("Test copy", self.destination)
        self.approval_status = label("", "warning")
        layout.addWidget(self.approval_status)
        self.confirm = QCheckBox("I reviewed every page, the MICR and signature coverage, and the filename.")
        layout.addWidget(self.confirm)
        actions = QHBoxLayout()
        layout.addLayout(actions)
        control("Skip for now", self.reject, actions)
        if record["status"] not in ("Filed", "Unrelated"):
            control("Not a check", self.mark_not_a_check, actions)
        actions.addStretch()
        self.approve = control("Approve && Next", self.save, actions)
        for signal in (self.issuer.textChanged, self.number.textChanged):
            signal.connect(self.review_changed)
        self.confirm.toggled.connect(self.update_approval)
        self.show_page(0)
        QTimer.singleShot(0, self.canvas.fit)

    def review_changed(self, *_):
        self.confirm.setChecked(False)
        self.update_approval()

    def update_approval(self):
        directory = check_scan_output_directory()
        issues = []
        try:
            target = review_output_path(self.record, self.issuer.text(), self.number.text())
            self.destination.setText(str(target))
        except ValueError as exc:
            self.destination.setText(str(directory))
            issues.append(str(exc))
        if len(self.visited) != self.count:
            issues.append("Open each remaining page before approving.")
        missing = missing_redactions(self.marks)
        if missing:
            issues.append("Draw boxes for the missing redactions (" + ", ".join(missing) + ").")
        self.confirm.setEnabled(not issues)
        self.approve.setEnabled(not issues and self.confirm.isChecked() and self.canvas.drag is None)
        if not issues and not self.confirm.isChecked():
            issues.append("Check the review confirmation to enable approval.")
        self.approval_status.setText(" ".join(issues))
        self.approval_status.setVisible(bool(issues))

    def show_page(self, page):
        self.canvas.load(self.source, page)
        self.page = page
        self.visited.add(page)
        self.prev.setEnabled(page > 0)
        self.next.setEnabled(page < self.count-1)
        self.page_label.setText(f"{page+1} of {self.count}")
        self.update_approval()

    def remove(self):
        if self.canvas.selected is not None:
            self.history.append(self.marks.copy())
            self.marks.pop(self.canvas.selected)
            self.canvas.selected = None
            self.review_changed()
            self.canvas.update()

    def undo(self):
        if self.history:
            self.marks = self.history.pop()
            self.canvas.selected = None
            self.review_changed()
            self.canvas.update()

    def save(self):
        if not self.approve.isEnabled():
            return
        try:
            self.saved_path = self.queue.file(self.record, self.marks, self.issuer.text(), self.number.text())
        except (ValueError, OSError, RuntimeError, sqlite3.Error) as exc:
            QMessageBox.warning(self, "Check was not filed", str(exc))
            return
        self.accept()

    def mark_not_a_check(self):
        self.marked_unrelated = True
        self.reject()


class CheckInbox(QDialog):
    def __init__(self, queue):
        super().__init__()
        self.queue = queue
        self.displayed = None
        self.saved: list[tuple[str, Path]] = []
        self.awaiting_completion = False
        self.setWindowTitle("Check Scan Review")
        self.resize(775, 560)
        layout = QVBoxLayout(self)
        layout.addWidget(QLabel(str(queue.inbox), textFormat=Qt.TextFormat.PlainText))
        self.status = QLabel("Looking for completed PaperCut scans…")
        layout.addWidget(self.status)
        self.other = QCheckBox("Show all scans, including filed, unrelated, and dismissed items")
        layout.addWidget(self.other)
        self.listing = QListWidget()
        layout.addWidget(self.listing)
        actions = QHBoxLayout()
        layout.addLayout(actions)
        self.open_button = control("Review selected", self.review, actions)
        self.dismiss_button = control("Dismiss from queue", self.dismiss, actions)
        self.not_a_check_button = control("Not a check", self.mark_selected_unrelated, actions)
        actions.addStretch()
        control("Close", self.close, actions)
        self.listing.itemDoubleClicked.connect(lambda *_: self.review())
        self.listing.currentItemChanged.connect(self.update_classification_action)
        self.other.toggled.connect(self.refresh)
        try:
            self.worker = start_check_scan_process("workflows.check_scanning.watch")
        except OSError:
            self.worker = None
        self.timer = QTimer(self, interval=3000)
        self.timer.timeout.connect(self.refresh)
        self.timer.timeout.connect(self.check_completion)
        self.timer.start()
        self.refresh()

    def refresh(self, *_):
        previous = self.listing.currentItem()
        name = previous.data(Qt.ItemDataRole.UserRole)["name"] if previous else ""
        try:
            records = self.queue.records(self.other.isChecked())
        except sqlite3.Error:
            self.status.setText("The queue is unavailable. Check the workstation’s local storage.")
            return
        displayed = [(r["name"], r["digest"], r["status"]) for r in records]
        if displayed != self.displayed:
            self.displayed = displayed
            self.listing.clear()
            for record in records:
                item = QListWidgetItem(f"{record['status']}    {record['name']}")
                item.setData(Qt.ItemDataRole.UserRole, dict(record))
                self.listing.addItem(item)
                if record["name"] == name:
                    self.listing.setCurrentItem(item)
            if self.listing.currentRow() < 0 and records:
                self.listing.setCurrentRow(0)
        if not self.queue.inbox.is_dir():
            self.status.setText("The intake folder is unavailable. Check business OneDrive sync.")
        elif self.worker is None or self.worker.poll() is not None:
            self.status.setText("Scan recognition stopped. Rerun setup and reopen the queue.")
        elif not records:
            self.status.setText("No scans to review. Watching for new scans.")
        else:
            saved_status = f"{len(self.saved)} saved this session. " if self.saved else ""
            self.status.setText(f"{saved_status}{len(records)} shown. New scans are checked automatically.")
        self.open_button.setEnabled(bool(records))
        self.dismiss_button.setEnabled(bool(records))
        self.update_classification_action()

    def update_classification_action(self):
        item = self.listing.currentItem()
        self.not_a_check_button.setEnabled(
            item is not None and item.data(Qt.ItemDataRole.UserRole)["status"] not in ("Filed", "Unrelated")
        )

    def dismiss(self):
        item = self.listing.currentItem()
        if item:
            self.queue.dismiss(item.data(Qt.ItemDataRole.UserRole))
            self.refresh()
            self.awaiting_completion = bool(self.saved)
            self.check_completion()

    def mark_selected_unrelated(self):
        item = self.listing.currentItem()
        if item:
            self.mark_unrelated(item.data(Qt.ItemDataRole.UserRole))

    def mark_unrelated(self, record):
        try:
            changed = self.queue.mark_unrelated(record)
        except sqlite3.Error:
            QMessageBox.warning(self, "Queue unavailable", "Check local storage and try again.")
            return
        self.refresh()
        if not changed:
            QMessageBox.information(self, "Scan changed", "Select the updated scan in the queue to review it.")
        self.awaiting_completion = bool(self.saved)
        self.check_completion()

    def review(self):
        self.awaiting_completion = False
        while item := self.listing.currentItem():
            record = item.data(Qt.ItemDataRole.UserRole)
            if decode_finding(record).status == "Multiple check pages":
                QMessageBox.information(self, "Multiple check faces",
                                        "Verify and separate the packet or redact it manually in Acrobat.")
                return
            try:
                previous_output = self.saved[-1][1] if self.saved else None
                viewer = CheckReview(self, self.queue, record, previous_output)
            except (OSError, ValueError, RuntimeError):
                QMessageBox.warning(self, "Scan unavailable", "Check whether the complete PDF is synced and readable.")
                return
            viewer.exec()
            saved_path = viewer.saved_path
            marked_unrelated = viewer.marked_unrelated
            viewer.deleteLater()
            if marked_unrelated:
                self.mark_unrelated(record)
                return
            if saved_path is None:
                self.refresh()
                if self.listing.count():
                    self.listing.setCurrentRow((self.listing.currentRow()+1) % self.listing.count())
                return
            self.saved.append((record["name"], saved_path))
            self.refresh()
            if self.other.isChecked():
                break
        self.awaiting_completion = bool(self.saved)
        self.check_completion()

    def check_completion(self):
        if not self.awaiting_completion:
            return
        try:
            pending_intake = self.queue.has_pending_intake()
            remaining = self.queue.records()
        except (OSError, sqlite3.Error):
            return
        if remaining:
            self.awaiting_completion = False
        elif pending_intake:
            if self.worker is not None and self.worker.poll() is None:
                self.status.setText(f"Saved {len(self.saved)}. Checking remaining incoming scans…")
        else:
            self.awaiting_completion = False
            self.show_completion()
            self.accept()

    def show_completion(self):
        dialog = QDialog(self)
        dialog.setWindowTitle("Queue complete")
        dialog.resize(680, 420)
        layout = QVBoxLayout(dialog)
        count = len(self.saved)
        caption = "redacted PDF saved" if count == 1 else "redacted PDFs saved"
        layout.addWidget(QLabel(f"{count} {caption}."))
        locations = QFormLayout()
        layout.addLayout(locations)
        folders = "\n".join(str(path) for path in dict.fromkeys(output.parent for _, output in self.saved))
        locations.addRow("Redacted copies saved to", QLabel(folders, textFormat=Qt.TextFormat.PlainText, wordWrap=True))
        locations.addRow("Original scans kept in", QLabel(str(self.queue.inbox), textFormat=Qt.TextFormat.PlainText, wordWrap=True))
        files = QPlainTextEdit("\n".join(f"{source} → {output.name}" for source, output in self.saved))
        files.setReadOnly(True)
        files.setAccessibleName("Original scan and redacted copy filenames")
        layout.addWidget(files)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        buttons.rejected.connect(dialog.accept)
        layout.addWidget(buttons)
        dialog.exec()

    def done(self, result):
        self.timer.stop()
        if self.worker is not None and self.worker.poll() is None:
            self.worker.kill()
            try:
                self.worker.wait(timeout=3)
            except subprocess.TimeoutExpired:
                pass
        super().done(result)


def main():
    app = QApplication(sys.argv)
    apply_theme(app)
    inbox = CheckInbox(ScanQueue(get_papercut_scan_directory(), queue_path()))
    inbox.exec()
    return 0


if __name__ == "__main__":
    sys.exit(main())
