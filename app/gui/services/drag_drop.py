"""Native file-drop registration kept separate from form business logic."""

from __future__ import annotations

from pathlib import Path
from typing import Callable

try:
    from tkinterdnd2 import DND_FILES
except ModuleNotFoundError:
    DND_FILES = None


DropCallback = Callable[[tuple[Path, ...]], None]


def is_file_drop_available() -> bool:
    return DND_FILES is not None


def parse_dropped_files(widget, event_data: str) -> tuple[Path, ...]:
    """Use Tcl list parsing so paths containing spaces or braces stay intact."""
    return tuple(Path(value) for value in widget.tk.splitlist(event_data))


def register_file_drop(widget, callback: DropCallback) -> bool:
    if DND_FILES is None:
        return False

    widget.drop_target_register(DND_FILES)

    def handle_drop(event):
        callback(parse_dropped_files(widget, event.data))
        return event.action

    widget.dnd_bind("<<Drop>>", handle_drop)
    return True
