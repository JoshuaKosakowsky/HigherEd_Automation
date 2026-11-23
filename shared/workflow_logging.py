"""Report names shared by workflow runners and integration logs."""

from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar


current_report_name = ContextVar("current_report_name", default="Native SQL")


@contextmanager
def report_log_context(name: str) -> Iterator[None]:
    """Use a configured report title for logs in the current execution context."""
    token = current_report_name.set(name)
    try:
        yield
    finally:
        current_report_name.reset(token)
