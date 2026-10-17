"""Refresh generated form values until staff explicitly choose a value."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from PySide6.QtCore import QDate, QSignalBlocker
from PySide6.QtWidgets import QDateEdit, QLineEdit, QSpinBox

from app.gui.services.drag_drop import FileInput


DefaultControl = QDateEdit | QLineEdit | QSpinBox | FileInput


@dataclass
class _TrackedDefault:
    control: DefaultControl
    factory: Callable[[], Any]
    edited: bool = False


class ParameterDefaults:
    """Track explicit choices, including browsing and returning to an old default."""

    def __init__(self) -> None:
        self._fields: dict[str, _TrackedDefault] = {}

    def track(self, key: str, control: DefaultControl, factory: Callable[[], Any]) -> None:
        """Register a control after its initial generated value has been set."""
        self._fields[key] = _TrackedDefault(control, factory)
        if isinstance(control, FileInput):
            signal = control.changed
        elif isinstance(control, QDateEdit):
            signal = control.dateChanged
        elif isinstance(control, QSpinBox):
            signal = control.valueChanged
        else:
            signal = control.textChanged
        signal.connect(lambda *args: self.preserve(key))

    def preserve(self, key: str) -> None:
        """Pin a staff choice or the input scope of a multi-step workflow."""
        self._fields[key].edited = True

    def refresh(self) -> None:
        """Recalculate untouched defaults without treating refreshes as edits."""
        for field in self._fields.values():
            if field.edited:
                continue
            value = field.factory()
            control = field.control
            with QSignalBlocker(control):
                if isinstance(control, QDateEdit):
                    control.setDate(QDate.fromString(str(value), "yyyy-MM-dd"))
                elif isinstance(control, QSpinBox):
                    control.setValue(int(value))
                else:
                    control.setText(str(value))
