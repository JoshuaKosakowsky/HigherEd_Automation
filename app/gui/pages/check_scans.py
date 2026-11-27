"""Cashier queue, page preview and editable redaction marks."""

from __future__ import annotations

from pathlib import Path
import shutil
import sqlite3
import sys

from PySide6.QtCore import QPointF, QProcess, QRectF, Qt, QTimer
from PySide6.QtGui import QColor, QImage, QPainter, QPen
from PySide6.QtWidgets import (
    QApplication, QCheckBox, QComboBox, QDialog, QFormLayout,
    QHBoxLayout, QLabel, QLineEdit, QListWidget, QListWidgetItem, QMessageBox,
    QPushButton, QScrollArea, QVBoxLayout, QWidget,
)

from app.gui.theme import apply_theme
from shared.mines_paths import get_papercut_scan_directory
from workflows.check_scanning.detection import Box, Mark
from workflows.check_scanning.documents import page_count, page_pixels
from workflows.check_scanning.intake import (
    ScanQueue, check_scan_output_directory, decode_finding, output_name, queue_path,
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
        self.review.history.append(self.review.marks.copy())
        self.review.confirm.setChecked(False)
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
            self.update()


class CheckReview(QDialog):
    def __init__(self, parent, queue, record):
        super().__init__(parent)
        self.queue, self.record = queue, record
        self.source = queue.source(record)
        self.count = page_count(self.source)
        finding = decode_finding(record)
        self.marks, self.history, self.visited = finding.marks, [], set()
        self.page = 0
        self.setWindowTitle("Review check and backup pages")
        self.resize(1050, 850)
        layout = QVBoxLayout(self)
        layout.addWidget(QLabel(record["name"], textFormat=Qt.TextFormat.PlainText))
        missing = {"MICR", "Signature"} - {mark.kind for mark in self.marks}
        if missing:
            layout.addWidget(QLabel("No initial box suggested for " + ", ".join(sorted(missing)) + ". Draw the missing areas."))
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
            self.kind.setCurrentText(next(iter(missing)))
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
        self.confirm = QCheckBox("I reviewed every page, the MICR and signature coverage, and the filename.")
        layout.addWidget(self.confirm)
        actions = QHBoxLayout()
        layout.addLayout(actions)
        control("Skip for now", self.reject, actions)
        actions.addStretch()
        self.approve = control("Approve && Next", self.save, actions)
        for signal in (self.issuer.textChanged, self.number.textChanged):
            signal.connect(self.update_destination)
        self.confirm.toggled.connect(self.approve.setEnabled)
        self.update_destination()
        self.show_page(0)
        QTimer.singleShot(0, self.canvas.fit)

    def update_destination(self, *_):
        self.confirm.setChecked(False)
        self.approve.setEnabled(False)
        directory = check_scan_output_directory()
        try:
            name = output_name(self.issuer.text(), self.number.text())
        except ValueError:
            name = "(enter company and check number)"
        self.destination.setText(str(directory / name))

    def show_page(self, page):
        self.canvas.load(self.source, page)
        self.page = page
        self.visited.add(page)
        self.prev.setEnabled(page > 0)
        self.next.setEnabled(page < self.count-1)
        self.page_label.setText(f"{page+1} of {self.count}")

    def remove(self):
        if self.canvas.selected is not None:
            self.history.append(self.marks.copy())
            self.marks.pop(self.canvas.selected)
            self.canvas.selected = None
            self.confirm.setChecked(False)
            self.canvas.update()

    def undo(self):
        if self.history:
            self.marks = self.history.pop()
            self.canvas.selected = None
            self.confirm.setChecked(False)
            self.canvas.update()

    def save(self):
        if not self.confirm.isChecked():
            return
        if len(self.visited) != self.count:
            QMessageBox.information(self, "Review backup pages", "Open each page in this packet before approving.")
            return
        try:
            self.queue.file(self.record, self.marks, self.issuer.text(), self.number.text())
        except (ValueError, OSError, RuntimeError, sqlite3.Error) as exc:
            QMessageBox.warning(self, "Check was not filed", str(exc))
            return
        self.accept()


class CheckInbox(QDialog):
    def __init__(self, queue):
        super().__init__()
        self.queue = queue
        self.displayed = None
        self.setWindowTitle("Check Scan Review")
        self.resize(775, 560)
        layout = QVBoxLayout(self)
        layout.addWidget(QLabel(str(queue.inbox), textFormat=Qt.TextFormat.PlainText))
        self.status = QLabel("Looking for completed PaperCut scans…")
        layout.addWidget(self.status)
        self.other = QCheckBox("Show all scans, including unrelated and dismissed items")
        layout.addWidget(self.other)
        self.listing = QListWidget()
        layout.addWidget(self.listing)
        actions = QHBoxLayout()
        layout.addLayout(actions)
        self.open_button = control("Review selected", self.review, actions)
        self.dismiss_button = control("Dismiss from queue", self.dismiss, actions)
        actions.addStretch()
        if sys.platform == "win32":
            self.startup_button = control("Enable scanning at sign-in", self.enable_startup, actions)
        control("Close", self.close, actions)
        self.listing.itemDoubleClicked.connect(lambda *_: self.review())
        self.other.toggled.connect(self.refresh)
        self.worker = QProcess(self)
        self.worker.setWorkingDirectory(str(Path(__file__).resolve().parents[3]))
        self.worker.setStandardErrorFile(QProcess.nullDevice())
        self.worker.setStandardOutputFile(QProcess.nullDevice())
        self.worker.start(sys.executable, ["-m", "workflows.check_scanning.watch"])
        self.timer = QTimer(self, interval=3000)
        self.timer.timeout.connect(self.refresh)
        self.timer.start()
        self.refresh()

    def enable_startup(self):
        executable = shutil.which("powershell.exe")
        if not executable:
            QMessageBox.warning(self, "Setup unavailable", "Windows PowerShell could not be found.")
            return
        installer = Path(__file__).resolve().parents[3] / "setup" / "setup_report_filing_watcher.ps1"
        self.installer = QProcess(self)
        self.installer.setStandardOutputFile(QProcess.nullDevice())
        self.installer.setStandardErrorFile(QProcess.nullDevice())
        self.startup_button.setEnabled(False)
        self.installer.finished.connect(self.startup_result)
        self.installer.errorOccurred.connect(lambda _: self.startup_result(1))
        self.installer.start(executable, ["-NoProfile", "-NonInteractive", "-File", str(installer), "-CheckScans"])

    def startup_result(self, code, *_):
        self.startup_button.setEnabled(True)
        if code:
            QMessageBox.warning(self, "Setup failed", "Check that Windows permits a scheduled task for this login.")
        else:
            QMessageBox.information(self, "Watcher enabled", "Check recognition will also run while this window is closed.")

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
                item = QListWidgetItem(f"{record['status']}    {record['name']}", self.listing)
                item.setData(Qt.ItemDataRole.UserRole, dict(record))
                if record["name"] == name:
                    self.listing.setCurrentItem(item)
            if self.listing.currentRow() < 0 and records:
                self.listing.setCurrentRow(0)
        if not self.queue.inbox.is_dir():
            self.status.setText("The intake folder is unavailable. Check business OneDrive sync.")
        elif self.worker.state() == QProcess.ProcessState.NotRunning and self.worker.exitCode() != 0:
            self.status.setText("Scan recognition stopped. Rerun setup and reopen the queue.")
        else:
            self.status.setText(f"{len(records)} shown. New scans are checked automatically.")
        self.open_button.setEnabled(bool(records))
        self.dismiss_button.setEnabled(bool(records))

    def dismiss(self):
        item = self.listing.currentItem()
        if item:
            self.queue.dismiss(item.data(Qt.ItemDataRole.UserRole))
            self.refresh()

    def review(self):
        while item := self.listing.currentItem():
            record = item.data(Qt.ItemDataRole.UserRole)
            if record["status"] == "Filed":
                QMessageBox.information(self, "Already filed", "This scan already has a filed copy.")
                return
            if decode_finding(record).status == "Multiple check pages":
                QMessageBox.information(self, "Multiple check faces",
                                        "Verify and separate the packet or redact it manually in Acrobat.")
                return
            try:
                viewer = CheckReview(self, self.queue, record)
            except (OSError, ValueError, RuntimeError):
                QMessageBox.warning(self, "Scan unavailable", "Check whether the complete PDF is synced and readable.")
                return
            approved = viewer.exec() == QDialog.DialogCode.Accepted
            viewer.deleteLater()
            self.refresh()
            if not approved and self.listing.count():
                self.listing.setCurrentRow((self.listing.currentRow()+1) % self.listing.count())
            if not approved or self.other.isChecked():
                return

    def done(self, result):
        self.timer.stop()
        if self.worker.state() != QProcess.ProcessState.NotRunning:
            self.worker.kill()
            self.worker.waitForFinished(3000)
        super().done(result)


def main():
    app = QApplication(sys.argv)
    apply_theme(app)
    inbox = CheckInbox(ScanQueue(get_papercut_scan_directory(), queue_path()))
    inbox.exec()
    return 0


if __name__ == "__main__":
    sys.exit(main())
