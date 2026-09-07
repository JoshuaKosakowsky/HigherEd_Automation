"""Resolve staff GUI views from a repository-controlled access policy."""

from __future__ import annotations

import getpass
import json
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Mapping

from app.gui.models import WorkflowDefinition


WORKFLOW_WILDCARD = "*"


class AccessConfigurationError(RuntimeError):
    """Raised when GUI access configuration is unsafe or malformed."""


@dataclass(frozen=True)
class UserAccessProfile:
    """Descriptive staff information plus the explicitly assigned GUI view."""

    login: str
    display_name: str
    job_title: str
    view: str


@dataclass(frozen=True)
class AccessConfiguration:
    """Validated login profiles and workflow allow-lists by GUI view."""

    users: Mapping[str, UserAccessProfile]
    workflows_by_view: Mapping[str, frozenset[str]]

    def profile_for_login(self, login: str | None) -> UserAccessProfile | None:
        if not login:
            return None
        return self.users.get(login.strip().casefold())


def get_current_login(environment: Mapping[str, str] | None = None) -> str | None:
    """Return the signed-in account name without trusting setup display data."""
    values = os.environ if environment is None else environment
    for variable in ("USERNAME", "USER"):
        value = values.get(variable, "").strip()
        if value:
            return value

    try:
        value = getpass.getuser().strip()
    except (ImportError, KeyError, OSError):
        return None
    return value or None


def _required_text(value: object, description: str) -> str:
    if not isinstance(value, str):
        raise AccessConfigurationError(f"GUI access contains an invalid {description}.")
    cleaned = value.strip()
    if not cleaned or len(cleaned) > 150 or "\n" in cleaned or "\r" in cleaned:
        raise AccessConfigurationError(f"GUI access contains an invalid {description}.")
    return cleaned


def load_access_configuration(config_path: Path) -> AccessConfiguration:
    """Read and validate the complete version 2 GUI access policy."""
    try:
        payload = json.loads(config_path.read_text(encoding="utf-8-sig"))
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise AccessConfigurationError(
            f"GUI access configuration could not be read: {config_path}"
        ) from error

    if not isinstance(payload, dict) or payload.get("schemaVersion") != 2:
        raise AccessConfigurationError("Unsupported GUI access configuration schema.")

    raw_views = payload.get("views")
    if not isinstance(raw_views, dict) or not raw_views:
        raise AccessConfigurationError("GUI access configuration has no view map.")

    workflows_by_view: dict[str, frozenset[str]] = {}
    for raw_view_name, raw_view in raw_views.items():
        view_name = _required_text(raw_view_name, "view name").casefold()
        if view_name in workflows_by_view:
            raise AccessConfigurationError(
                f"GUI access contains a duplicate view: {raw_view_name}."
            )
        if not isinstance(raw_view, dict):
            raise AccessConfigurationError(
                f"GUI access view {raw_view_name} must be an object."
            )
        workflow_ids = raw_view.get("workflows")
        if not isinstance(workflow_ids, list):
            raise AccessConfigurationError(
                f"GUI access view {raw_view_name} has no workflow list."
            )
        normalized_ids = [
            _required_text(item, f"workflow ID for {raw_view_name}")
            for item in workflow_ids
        ]
        if len(normalized_ids) != len(set(normalized_ids)):
            raise AccessConfigurationError(
                f"GUI access view {raw_view_name} contains duplicate workflows."
            )
        if WORKFLOW_WILDCARD in normalized_ids and len(normalized_ids) != 1:
            raise AccessConfigurationError(
                f"GUI access view {raw_view_name} cannot mix '*' with workflow IDs."
            )
        workflows_by_view[view_name] = frozenset(normalized_ids)

    raw_users = payload.get("users")
    if not isinstance(raw_users, dict):
        raise AccessConfigurationError("GUI access configuration has no user map.")

    users: dict[str, UserAccessProfile] = {}
    for raw_login, raw_profile in raw_users.items():
        login = _required_text(raw_login, "user login")
        normalized_login = login.casefold()
        if normalized_login in users:
            raise AccessConfigurationError(
                f"GUI access contains a duplicate user login: {login}."
            )
        if not isinstance(raw_profile, dict):
            raise AccessConfigurationError(
                f"GUI access profile for {login} must be an object."
            )
        display_name = _required_text(
            raw_profile.get("displayName"), f"display name for {login}"
        )
        job_title = _required_text(
            raw_profile.get("jobTitle"), f"job title for {login}"
        )
        view = _required_text(raw_profile.get("view"), f"view for {login}").casefold()
        if view not in workflows_by_view:
            raise AccessConfigurationError(
                f"GUI access profile for {login} refers to unknown view: {view}."
            )
        users[normalized_login] = UserAccessProfile(
            login=login,
            display_name=display_name,
            job_title=job_title,
            view=view,
        )

    return AccessConfiguration(users=users, workflows_by_view=workflows_by_view)


def filter_workflows_for_view(
    workflows: Iterable[WorkflowDefinition],
    configuration: AccessConfiguration,
    view: str | None,
) -> tuple[WorkflowDefinition, ...]:
    """Return only workflows explicitly granted to a GUI view."""
    definitions = tuple(workflows)
    if view is None:
        return ()

    allowed_ids = configuration.workflows_by_view.get(view.casefold())
    if allowed_ids is None:
        return ()
    if WORKFLOW_WILDCARD in allowed_ids:
        return definitions

    registered_ids = {definition.workflow_id for definition in definitions}
    unknown_ids = allowed_ids - registered_ids
    if unknown_ids:
        raise AccessConfigurationError(
            "GUI access refers to unknown workflows: " + ", ".join(sorted(unknown_ids))
        )
    return tuple(
        definition
        for definition in definitions
        if definition.workflow_id in allowed_ids
    )
