"""Cooperative workflow cancellation with a protected final publication step."""

from __future__ import annotations

from collections.abc import Callable
from threading import Event, Lock


class WorkflowCancelled(RuntimeError):
    """The user stopped a workflow before its output was published."""

    def __init__(self) -> None:
        super().__init__("Workflow cancelled. No output was published.")


class CancellationToken:
    def __init__(self) -> None:
        self._requested = Event()
        self._publication_lock = Lock()
        self._published = False

    def request(self) -> bool:
        with self._publication_lock:
            if self._published:
                return False
            self._requested.set()
            return True

    def check(self) -> None:
        if self._requested.is_set():
            raise WorkflowCancelled()

    @property
    def is_requested(self) -> bool:
        return self._requested.is_set()

    def publish(self, action: Callable[[], None]) -> None:
        """Accept cancellation up to, but never during, final output publication."""
        with self._publication_lock:
            self.check()
            action()
            self._published = True
