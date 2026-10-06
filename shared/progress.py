"""Thread-safe workflow progress, independent of GUI and business rules."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from threading import Lock


@dataclass(frozen=True)
class ProgressUpdate:
    stage: str
    completed: int | None = None
    total: int | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.stage, str) or not self.stage.strip():
            raise ValueError("Progress needs a readable stage name.")
        if (self.completed is None) != (self.total is None):
            raise ValueError("Progress needs both completed and total counts.")
        if self.total is not None:
            if type(self.total) is not int or type(self.completed) is not int:
                raise ValueError("Progress counts must be integers.")
            if not 0 <= self.completed <= self.total:
                raise ValueError("Progress counts must satisfy 0 <= completed <= total.")

    @property
    def percent(self) -> int | None:
        if self.total is None:
            return None
        return self.completed * 100 // self.total if self.total else 100


class ProgressReporter:
    """Keep only the latest update so fast producers cannot flood the GUI."""

    def __init__(self, on_update: Callable[[ProgressUpdate], None] | None = None) -> None:
        self._lock = Lock()
        self._latest: ProgressUpdate | None = None
        self._on_update = on_update

    def report(self, stage: str, *, completed: int | None = None, total: int | None = None) -> None:
        """Report a phase; counts describe this phase, never estimated runtime."""
        update = ProgressUpdate(stage, completed, total)
        with self._lock:
            self._latest = update
        if self._on_update:
            self._on_update(update)

    @property
    def snapshot(self) -> ProgressUpdate | None:
        with self._lock:
            return self._latest
