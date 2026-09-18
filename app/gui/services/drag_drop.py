"""Native Qt file input with path entry, browsing, and local file drops."""

from pathlib import Path

from PySide6.QtCore import QEvent, Signal
from PySide6.QtWidgets import QFrame, QVBoxLayout, QHBoxLayout, QLineEdit, QPlainTextEdit, QFileDialog

from app.gui.models import ParameterDefinition, ParameterKind
from app.gui.theme import button, label


def dropped_local_paths(mime_data) -> tuple[Path, ...]:
    """Never turn remote URLs into local input paths."""
    return tuple(Path(url.toLocalFile()) for url in mime_data.urls() if url.isLocalFile())


class FileInput(QFrame):
    changed = Signal()

    def __init__(self, parameter: ParameterDefinition, parent=None) -> None:
        super().__init__(parent)
        self.parameter = parameter
        self.multiple = parameter.kind == ParameterKind.MULTI_INPUT_FILE
        self.output = parameter.kind == ParameterKind.OUTPUT_FILE
        self.setObjectName("fileInput")
        self.setAcceptDrops(not self.output)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(14, 12, 14, 12)
        layout.setSpacing(8)
        row = QHBoxLayout()
        row.addWidget(label(
            "OUTPUT LOCATION" if self.output else
            "DROP FILES HERE" if self.multiple else "DROP A FILE HERE", "eyebrow"
        ), 1)
        row.addWidget(button("Browse…", self._browse))
        layout.addLayout(row)
        if self.multiple:
            self.editor = QPlainTextEdit()
            self.editor.setFixedHeight(94)
            self.editor.setPlaceholderText("Or paste one file path per line")
            if parameter.default:
                self.editor.setPlainText("\n".join(str(item) for item in parameter.default))
        else:
            self.editor = QLineEdit(str(parameter.default or ""))
            self.editor.setPlaceholderText("Or paste a file path")
            self.editor.setClearButtonEnabled(True)
        self.editor.setAccessibleName(parameter.label)
        # Editors otherwise consume external drops as text instead of file URLs.
        self.editor.installEventFilter(self)
        if self.multiple:
            self.editor.viewport().installEventFilter(self)
        self.editor.setAcceptDrops(not self.output)
        self.editor.textChanged.connect(lambda *args: self.changed.emit())
        layout.addWidget(self.editor)
        self.error = label("", "error")
        self.error.hide()
        layout.addWidget(self.error)

    def text(self) -> str:
        return self.editor.toPlainText() if self.multiple else self.editor.text()

    def setText(self, value: str) -> None:
        if self.multiple:
            self.editor.setPlainText(value)
        else:
            self.editor.setText(value)

    def _highlight(self, active: bool) -> None:
        self.setProperty("dragging", active)
        self.style().unpolish(self)
        self.style().polish(self)

    def eventFilter(self, watched, event) -> bool:
        if event.type() in (QEvent.Type.DragEnter, QEvent.Type.DragMove, QEvent.Type.Drop):
            if self.output:
                return False
            if event.type() == QEvent.Type.Drop:
                self.dropEvent(event)
            else:
                self.dragEnterEvent(event)
            return True
        if event.type() == QEvent.Type.DragLeave:
            self._highlight(False)
        return super().eventFilter(watched, event)

    def dragEnterEvent(self, event) -> None:
        if not self.output and dropped_local_paths(event.mimeData()):
            event.acceptProposedAction()
            self._highlight(True)
        else:
            event.ignore()

    def dragMoveEvent(self, event) -> None:
        self.dragEnterEvent(event)

    def dragLeaveEvent(self, event) -> None:
        self._highlight(False)
        event.accept()

    def dropEvent(self, event) -> None:
        self._highlight(False)
        if self.accept_paths(dropped_local_paths(event.mimeData())):
            event.acceptProposedAction()
        else:
            event.ignore()

    def accept_paths(self, paths: tuple[Path, ...]) -> bool:
        if self.output or not paths or any(not path.is_file() for path in paths):
            self.error.setText("Choose local files, not folders or web links.")
            self.error.show()
            return False
        if not self.multiple and len(paths) != 1:
            self.error.setText("This input accepts one file at a time.")
            self.error.show()
            return False
        if self.multiple:
            existing = [line.strip().strip('"') for line in self.text().splitlines() if line.strip()]
            keys = {Path(line).expanduser().resolve() for line in existing}
            for path in paths:
                resolved = path.expanduser().resolve()
                if resolved not in keys:
                    existing.append(str(path))
                    keys.add(resolved)
            self.setText("\n".join(existing))
        else:
            self.setText(str(paths[0]))
        self.error.hide()
        return True

    def _browse(self) -> None:
        filters = ";;".join(
            f"{name} ({patterns})"
            for name, patterns in (self.parameter.file_types or (("All files", "*"),))
        )
        current = self.text().strip().strip('"')
        if self.multiple:
            paths, _ = QFileDialog.getOpenFileNames(self, self.parameter.label, "", filters)
            if paths:
                self.accept_paths(tuple(Path(path) for path in paths))
        elif self.output:
            dialog = QFileDialog(self, self.parameter.label, current, filters)
            dialog.setAcceptMode(QFileDialog.AcceptMode.AcceptSave)
            dialog.setDefaultSuffix(self.parameter.default_extension.lstrip("."))
            if dialog.exec():
                self.setText(dialog.selectedFiles()[0])
        else:
            path, _ = QFileDialog.getOpenFileName(self, self.parameter.label, current, filters)
            if path:
                self.accept_paths((Path(path),))
