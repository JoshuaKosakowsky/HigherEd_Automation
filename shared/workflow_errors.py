"""Errors that can be shown directly to workflow users."""


class WorkflowUserError(RuntimeError):
    """An operational error with a staff-safe message and no sensitive details."""
