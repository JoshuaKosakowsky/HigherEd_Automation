"""Registry-driven Qt workflow form with review and asynchronous execution."""

from __future__ import annotations

import queue
from pathlib import Path
from typing import Callable

from PySide6.QtCore import QTimer, Signal
from PySide6.QtWidgets import (
    QComboBox, QDialog, QDialogButtonBox, QFormLayout, QHBoxLayout,
    QLineEdit, QMessageBox, QPlainTextEdit, QProgressBar,
    QScrollArea, QVBoxLayout, QWidget,
)

from app.gui.models import ParameterKind, WorkflowContext, WorkflowDefinition, WorkflowMode
from app.gui.services.drag_drop import FileInput
from app.gui.services.execution import WorkflowExecutor
from app.gui.services.parameters import parse_parameters
from app.gui.services.textbook_recon import MANUAL_SOURCE, SQL_SOURCE
from app.gui.services.system import open_path
from app.gui.theme import button, card, label


class WorkflowDetailPage(QScrollArea):
    busy_changed = Signal(bool)

    def __init__(
        self, parent, definition: WorkflowDefinition, executor: WorkflowExecutor,
        go_home: Callable[[], None], authorize: Callable[[], bool] | None = None,
        is_administrator: bool = False,
    ) -> None:
        super().__init__(parent)
        self.definition = definition
        self.executor = executor
        self.authorize = authorize or (lambda: True)
        self.result_queue = None
        self.active_context: WorkflowContext | None = None
        self.output_path: Path | None = None
        self.inputs = {}
        self.manual_banner_widgets = []
        self.recon_source = None
        self.textbook_step = None
        self.setWidgetResizable(True)
        body = QWidget()
        body.setObjectName("page")
        self.setWidget(body)
        layout = QVBoxLayout(body)
        layout.setContentsMargins(36, 30, 36, 30)
        layout.setSpacing(16)
        self.back_button = button("←  All workflows", go_home)
        row = QHBoxLayout()
        row.addWidget(self.back_button)
        row.addStretch()
        row.addWidget(label(definition.category.upper(), "eyebrow"))
        layout.addLayout(row)
        layout.addWidget(label(definition.name, "title"))
        layout.addWidget(label(definition.description, "muted"))
        layout.addWidget(label("01  INPUTS     /     02  REVIEW & RUN     /     03  RESULTS", "eyebrow"))
        self.form, form_layout = card()
        form_layout.addWidget(label(
            "Prepare your inputs" if definition.parameters else "Ready to set up", "section"
        ))
        if not definition.parameters:
            form_layout.addWidget(label("No files or additional inputs are needed. Review the details before running.", "muted"))
        for parameter in definition.parameters:
            field_label = label(parameter.label, "field")
            form_layout.addWidget(field_label)
            if parameter.kind in (
                ParameterKind.INPUT_FILE, ParameterKind.MULTI_INPUT_FILE, ParameterKind.OUTPUT_FILE
            ):
                control = FileInput(parameter)
                field_label.setBuddy(control.editor)
            elif parameter.kind == ParameterKind.NAME_LIST:
                control = QPlainTextEdit("\n".join(str(name) for name in parameter.default or ()))
                control.setFixedHeight(112)
                field_label.setBuddy(control)
            else:
                control = QLineEdit(str(parameter.default) if parameter.default is not None else "")
                field_label.setBuddy(control)
            control.setAccessibleName(parameter.label)
            self.inputs[parameter.key] = control
            form_layout.addWidget(control)
            if parameter.key in ("frst_file", "book_file") and definition.workflow_id == "textbook_recon_manual":
                self.manual_banner_widgets.extend((field_label, control))
            if parameter.help_text:
                help_label = label(parameter.help_text, "muted")
                form_layout.addWidget(help_label)
                if parameter.key in ("frst_file", "book_file") and definition.workflow_id == "textbook_recon_manual":
                    self.manual_banner_widgets.append(help_label)
            form_layout.addSpacing(8)
            if parameter.key == "brokers_file" and definition.workflow_id == "textbook_recon_manual":
                form_layout.addWidget(label("Banner data source", "field"))
                self.recon_source = QComboBox()
                self.recon_source.setAccessibleName("Banner data source")
                self.recon_source.addItem("Upload BOOK/FRST files manually", MANUAL_SOURCE)
                if is_administrator:
                    self.recon_source.addItem("Run SQL from PROD Insights", SQL_SOURCE)
                form_layout.addWidget(self.recon_source)
                form_layout.addSpacing(8)
        if definition.workflow_id == "textbook_brokers":
            form_layout.addWidget(label("Workflow step", "field"))
            self.textbook_step = QComboBox()
            self.textbook_step.setAccessibleName("Workflow step")
            self.textbook_step.addItem("1. Prepare TSPLOAD", "prepare")
            self.textbook_step.addItem("2. Archive after TSPLOAD", "archive")
            form_layout.addWidget(self.textbook_step)
            form_layout.addWidget(label(
                "Complete TSPLOAD in Banner and verify the transactions before step 2. "
                "To resume later, select step 2 with the same Banner term.", "muted"
            ))
        self.mode = QComboBox()
        for mode in definition.supported_modes:
            self.mode.addItem("Test" if mode == WorkflowMode.TEST else "Production", mode.value)
        if definition.default_mode:
            self.mode.setCurrentIndex(self.mode.findData(definition.default_mode.value))
        self.mode.setAccessibleName("Execution mode")
        if definition.supported_modes:
            form_layout.addWidget(label("Execution mode", "field"))
            form_layout.addWidget(self.mode)
        self.production_warning = label(definition.production_warning, "warning")
        form_layout.addWidget(self.production_warning)
        self.mode.currentIndexChanged.connect(self._update_production_warning)
        if self.recon_source is not None:
            self.recon_source.currentIndexChanged.connect(self._update_recon_source)
            self._update_recon_source()
        self._update_production_warning()
        layout.addWidget(self.form)
        self.error = label("", "error")
        self.error.hide()
        layout.addWidget(self.error)
        actions = QHBoxLayout()
        self.run_button = button("Review & run  →", self._run, "primary")
        actions.addWidget(self.run_button)
        actions.addStretch()
        actions.addWidget(button("Open log folder", lambda: self._open(self.executor.log_directory)))
        layout.addLayout(actions)
        self.progress = QProgressBar()
        self.progress.setRange(0, 0)
        self.progress.setTextVisible(False)
        self.progress.hide()
        layout.addWidget(self.progress)
        self.status_label = label("Ready when you are. Review your inputs before starting.", "status")
        layout.addWidget(self.status_label)
        results = QHBoxLayout()
        self.output_button = button("Open result", self._open_output, "primary")
        self.folder_button = button("Open output folder", self._open_output_folder)
        for widget in (self.output_button, self.folder_button):
            widget.hide()
            results.addWidget(widget)
        results.addStretch()
        layout.addLayout(results)
        layout.addStretch()
        self.timer = QTimer(self)
        self.timer.setInterval(100)
        self.timer.timeout.connect(self._poll_result)

    def _update_production_warning(self) -> None:
        self.production_warning.setVisible(
            self.mode.currentData() == WorkflowMode.PRODUCTION.value or
            (self.recon_source is not None and self.recon_source.currentData() == SQL_SOURCE)
        )

    def _update_recon_source(self) -> None:
        manual = self.recon_source.currentData() == MANUAL_SOURCE
        for widget in self.manual_banner_widgets:
            widget.setVisible(manual)
        self._update_production_warning()

    def _parse_parameters(self) -> dict:
        values = {
            key: control.toPlainText() if isinstance(control, QPlainTextEdit) else control.text()
            for key, control in self.inputs.items()
        }
        definitions = self.definition.parameters
        if self.recon_source is not None:
            source = self.recon_source.currentData()
            if source == SQL_SOURCE:
                definitions = tuple(parameter for parameter in definitions
                                    if parameter.key not in ("frst_file", "book_file"))
            parsed = parse_parameters(definitions, values)
            parsed["banner_source"] = source
            return parsed
        parsed = parse_parameters(definitions, values)
        if self.textbook_step is not None:
            parsed["step"] = self.textbook_step.currentData()
        return parsed

    def _confirm(self, context: WorkflowContext) -> bool:
        dialog = QDialog(self)
        dialog.setWindowTitle("Review workflow")
        dialog.resize(620, 480)
        layout = QVBoxLayout(dialog)
        layout.addWidget(label("Ready to run?", "title"))
        layout.addWidget(label(self.definition.name, "section"))
        layout.addWidget(label(self.definition.description, "muted"))
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        summary = QWidget()
        form = QFormLayout(summary)
        form.setRowWrapPolicy(QFormLayout.RowWrapPolicy.WrapAllRows)
        if self.recon_source is not None:
            source_label = "Run SQL from PROD Insights" if context.parameters["banner_source"] == SQL_SOURCE else "Upload BOOK/FRST files manually"
            form.addRow(label("Banner data source", "field"), label(source_label))
        if self.textbook_step is not None:
            form.addRow(label("Workflow step", "field"), label(self.textbook_step.currentText()))
        for parameter in self.definition.parameters:
            if parameter.key not in context.parameters:
                continue
            value = context.parameters[parameter.key]
            text = "\n".join(str(item) for item in value) if isinstance(value, tuple) else str(value)
            form.addRow(label(parameter.label, "field"), label(text))
        scroll.setWidget(summary)
        layout.addWidget(scroll)
        if context.mode == WorkflowMode.PRODUCTION:
            layout.addWidget(label("PRODUCTION MODE\n" + self.definition.production_warning, "warning"))
        elif context.mode is not None:
            layout.addWidget(label("TEST MODE", "eyebrow"))
        controls = QDialogButtonBox(QDialogButtonBox.StandardButton.Cancel)
        run = controls.addButton(
            "Run in production" if context.mode == WorkflowMode.PRODUCTION else "Run workflow",
            QDialogButtonBox.ButtonRole.AcceptRole,
        )
        run.setObjectName("primary")
        run.setAutoDefault(False)
        controls.button(QDialogButtonBox.StandardButton.Cancel).setDefault(True)
        controls.accepted.connect(dialog.accept)
        controls.rejected.connect(dialog.reject)
        layout.addWidget(controls)
        return dialog.exec() == QDialog.DialogCode.Accepted

    def _run(self) -> None:
        if self.result_queue is not None or self.executor.is_running:
            return
        self.error.hide()
        try:
            parameters = self._parse_parameters()
        except ValueError as error:
            self.error.setText(str(error))
            self.error.show()
            self.ensureWidgetVisible(self.error)
            return
        value = self.mode.currentData()
        mode = (WorkflowMode.PRODUCTION if parameters.get("banner_source") == SQL_SOURCE else
                WorkflowMode(value) if value else None)
        context = WorkflowContext(self.definition.workflow_id, parameters, mode)
        if not self._confirm(context) or not self.authorize():
            return
        if parameters.get("step") == "archive" and self.textbook_step is not None:
            answer = QMessageBox.question(
                self, "Confirm TSPLOAD completion",
                f"For Banner term {parameters['term_code']}, have you uploaded TSPLOAD.csv "
                "through GJAJFLU, completed TSPLOAD, and verified that the transactions "
                "applied successfully?\n\nYes will archive the pending local and remote "
                "source files and TSPLOAD output. Select No to leave them pending.",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.No,
            )
            if answer != QMessageBox.StandardButton.Yes or not self.authorize():
                return
            parameters = {**parameters, "banner_upload_confirmed": True}
            context = WorkflowContext(self.definition.workflow_id, parameters, mode)
        self.active_context = context
        try:
            self.result_queue = self.executor.run_async(self.definition, context)
        except RuntimeError as error:
            self.error.setText(str(error))
            self.error.show()
            return
        self.form.setEnabled(False)
        self.run_button.setEnabled(False)
        self.back_button.setEnabled(False)
        self.output_button.hide()
        self.folder_button.hide()
        self.output_path = None
        self.progress.show()
        self.status_label.setText("Running… Keep this window open. Your result will appear here.")
        self.busy_changed.emit(True)
        self.timer.start()

    def _poll_result(self) -> None:
        if self.result_queue is None:
            return
        try:
            result = self.result_queue.get_nowait()
        except queue.Empty:
            return
        self.result_queue = None
        self.timer.stop()
        self.progress.hide()
        self.form.setEnabled(True)
        self.run_button.setEnabled(True)
        self.back_button.setEnabled(True)
        self.status_label.setText(("Completed\n" if result.success else "Could not complete\n") + result.message)
        self.output_path = result.output_path
        self.output_button.setVisible(bool(result.success and result.output_path))
        self.folder_button.setVisible(bool(result.success and result.output_path))
        self.busy_changed.emit(False)
        self.ensureWidgetVisible(self.status_label)
        if (self.textbook_step is not None and self.active_context is not None
                and result.success and result.output_path
                and self.active_context.parameters.get("step") == "prepare"):
            self.inputs["term_code"].setText(str(self.active_context.parameters["term_code"]))
            self.textbook_step.setCurrentIndex(self.textbook_step.findData("archive"))
            QMessageBox.information(
                self, "Next step: complete TSPLOAD, then archive",
                "TSPLOAD.csv is ready. Complete TSPLOAD in Banner and verify that the "
                "transactions applied successfully. Then use Review & run for step 2 "
                "to archive this term's files. Files remain pending until you confirm.",
            )
        if not result.success:
            QMessageBox.warning(self, "Workflow could not be completed",
                                result.message + "\n\nTechnical details were written to the GUI log.")

    def _open(self, path: Path) -> None:
        try:
            open_path(path)
        except OSError:
            QMessageBox.warning(self, "Could not open location", "The file or folder is unavailable.")

    def _open_output(self) -> None:
        if self.output_path:
            self._open(self.output_path)

    def _open_output_folder(self) -> None:
        if self.output_path:
            self._open(self.output_path.parent)
