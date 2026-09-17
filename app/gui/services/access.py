"""Load, validate, and safely update staff GUI access policy."""

from __future__ import annotations

import base64
import getpass
import hashlib
import hmac
import json
import os
import secrets
import shutil
import tempfile
from dataclasses import dataclass, replace
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable, Mapping

from app.gui.models import WorkflowDefinition
from shared.mines_paths import ensure_hidden_directory


WORKFLOW_WILDCARD = "*"
ADMINISTRATOR_VIEW = "administrator"
SCHEMA_VERSION = 3
PASSWORD_ALGORITHM = "pbkdf2_sha256"
PASSWORD_ITERATIONS = 600_000
MINIMUM_OWNER_PASSWORD_LENGTH = 12


class AccessConfigurationError(RuntimeError):
    """Raised when GUI access configuration is unsafe or malformed."""


class AccessConfigurationConflictError(AccessConfigurationError):
    """Raised when another administrator changed the policy first."""


class OwnerProtectionError(AccessConfigurationError):
    """Raised when a protected owner operation is not authorized."""


@dataclass(frozen=True)
class OwnerProtection:
    algorithm: str
    iterations: int
    salt: str
    digest: str


@dataclass(frozen=True)
class UserAccessProfile:
    """Descriptive staff information plus the explicitly assigned GUI view."""

    login: str
    display_name: str
    job_title: str
    view: str
    active: bool = True


@dataclass(frozen=True)
class AccessConfiguration:
    """Validated login profiles and workflow allow-lists by GUI view."""

    users: Mapping[str, UserAccessProfile]
    workflows_by_view: Mapping[str, frozenset[str]]
    owner_login: str | None = None
    owner_protection: OwnerProtection | None = None
    updated_at: str | None = None
    updated_by: str | None = None
    source_digest: str | None = None

    def profile_for_login(self, login: str | None) -> UserAccessProfile | None:
        profile = self.raw_profile_for_login(login)
        return profile if profile is not None and profile.active else None

    def raw_profile_for_login(self, login: str | None) -> UserAccessProfile | None:
        if not login:
            return None
        return self.users.get(login.strip().casefold())

    def is_administrator(self, login: str | None) -> bool:
        profile = self.profile_for_login(login)
        return profile is not None and profile.view == ADMINISTRATOR_VIEW


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


def _optional_text(value: object, description: str) -> str | None:
    return None if value is None else _required_text(value, description)


def _parse_owner_protection(value: object) -> OwnerProtection | None:
    if value is None:
        return None
    if not isinstance(value, dict):
        raise AccessConfigurationError("Owner protection must be an object.")
    algorithm = _required_text(value.get("algorithm"), "owner algorithm")
    iterations = value.get("iterations")
    salt = _required_text(value.get("salt"), "owner password salt")
    digest = _required_text(value.get("digest"), "owner password digest")
    if algorithm != PASSWORD_ALGORITHM:
        raise AccessConfigurationError("Unsupported owner password algorithm.")
    if not isinstance(iterations, int) or iterations < 100_000:
        raise AccessConfigurationError("Owner password iteration count is invalid.")
    try:
        base64.b64decode(salt, validate=True)
        base64.b64decode(digest, validate=True)
    except (ValueError, TypeError) as error:
        raise AccessConfigurationError("Owner password data is invalid.") from error
    return OwnerProtection(algorithm, iterations, salt, digest)


def _parse_access_payload(payload: object, source_digest: str) -> AccessConfiguration:
    if not isinstance(payload, dict) or payload.get("schemaVersion") not in (2, 3):
        raise AccessConfigurationError("Unsupported GUI access configuration schema.")

    raw_views = payload.get("views")
    if not isinstance(raw_views, dict) or not raw_views:
        raise AccessConfigurationError("GUI access configuration has no view map.")
    workflows_by_view: dict[str, frozenset[str]] = {}
    for raw_view_name, raw_view in raw_views.items():
        view_name = _required_text(raw_view_name, "view name").casefold()
        if view_name in workflows_by_view:
            raise AccessConfigurationError(f"Duplicate GUI view: {raw_view_name}.")
        if not isinstance(raw_view, dict):
            raise AccessConfigurationError(f"GUI view {raw_view_name} must be an object.")
        workflow_ids = raw_view.get("workflows")
        if not isinstance(workflow_ids, list):
            raise AccessConfigurationError(f"GUI view {raw_view_name} has no workflow list.")
        normalized_ids = [
            _required_text(item, f"workflow ID for {raw_view_name}")
            for item in workflow_ids
        ]
        if len(normalized_ids) != len(set(normalized_ids)):
            raise AccessConfigurationError(f"GUI view {raw_view_name} has duplicates.")
        if WORKFLOW_WILDCARD in normalized_ids and len(normalized_ids) != 1:
            raise AccessConfigurationError(
                f"GUI view {raw_view_name} cannot mix '*' with workflow IDs."
            )
        workflows_by_view[view_name] = frozenset(normalized_ids)
    if ADMINISTRATOR_VIEW not in workflows_by_view:
        raise AccessConfigurationError("GUI access requires an administrator view.")
    if workflows_by_view[ADMINISTRATOR_VIEW] != frozenset({WORKFLOW_WILDCARD}):
        raise AccessConfigurationError(
            "The administrator view must include every registered workflow."
        )

    raw_users = payload.get("users")
    if not isinstance(raw_users, dict):
        raise AccessConfigurationError("GUI access configuration has no user map.")
    users: dict[str, UserAccessProfile] = {}
    for raw_login, raw_profile in raw_users.items():
        login = _required_text(raw_login, "user login")
        normalized_login = login.casefold()
        if normalized_login in users:
            raise AccessConfigurationError(f"Duplicate GUI user login: {login}.")
        if not isinstance(raw_profile, dict):
            raise AccessConfigurationError(f"Profile for {login} must be an object.")
        display_name = _required_text(raw_profile.get("displayName"), f"display name for {login}")
        job_title = _required_text(raw_profile.get("jobTitle"), f"job title for {login}")
        view = _required_text(raw_profile.get("view"), f"view for {login}").casefold()
        if view not in workflows_by_view:
            raise AccessConfigurationError(f"Profile for {login} uses unknown view: {view}.")
        active = raw_profile.get("active", True)
        if not isinstance(active, bool):
            raise AccessConfigurationError(f"Profile for {login} has an invalid active flag.")
        users[normalized_login] = UserAccessProfile(
            login, display_name, job_title, view, active
        )
    if not any(p.active and p.view == ADMINISTRATOR_VIEW for p in users.values()):
        raise AccessConfigurationError("GUI access requires at least one active administrator.")

    owner_login = owner_protection = updated_at = updated_by = None
    if payload["schemaVersion"] == SCHEMA_VERSION:
        metadata = payload.get("metadata")
        if not isinstance(metadata, dict):
            raise AccessConfigurationError("GUI access metadata is missing.")
        owner_login = _required_text(metadata.get("ownerLogin"), "owner login")
        if owner_login.casefold() not in users:
            raise AccessConfigurationError("GUI access owner has no user profile.")
        updated_at = _optional_text(metadata.get("updatedAt"), "updated timestamp")
        updated_by = _optional_text(metadata.get("updatedBy"), "updating login")
        owner_protection = _parse_owner_protection(payload.get("ownerProtection"))

    return AccessConfiguration(
        users, workflows_by_view, owner_login, owner_protection,
        updated_at, updated_by, source_digest
    )


def load_access_configuration(config_path: Path) -> AccessConfiguration:
    """Read and validate a GUI access policy."""
    try:
        raw = config_path.read_bytes()
        payload = json.loads(raw.decode("utf-8-sig"))
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise AccessConfigurationError(f"GUI access configuration could not be read: {config_path}") from error
    return _parse_access_payload(payload, hashlib.sha256(raw).hexdigest())


def create_owner_protection(password: str) -> OwnerProtection:
    """Create a salted verifier; the password itself is never stored."""
    if len(password) < MINIMUM_OWNER_PASSWORD_LENGTH:
        raise OwnerProtectionError(
            f"The owner password must be at least {MINIMUM_OWNER_PASSWORD_LENGTH} characters."
        )
    salt = secrets.token_bytes(32)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode(), salt, PASSWORD_ITERATIONS)
    return OwnerProtection(
        PASSWORD_ALGORITHM, PASSWORD_ITERATIONS,
        base64.b64encode(salt).decode("ascii"),
        base64.b64encode(digest).decode("ascii"),
    )


def verify_owner_password(protection: OwnerProtection, password: str) -> bool:
    salt = base64.b64decode(protection.salt)
    expected = base64.b64decode(protection.digest)
    actual = hashlib.pbkdf2_hmac(
        "sha256", password.encode(), salt, protection.iterations
    )
    return hmac.compare_digest(expected, actual)


def upgrade_legacy_configuration(
    configuration: AccessConfiguration, *, owner_login: str
) -> AccessConfiguration:
    """Promote a validated v2 policy into the shared v3 format."""
    owner = configuration.raw_profile_for_login(owner_login)
    if owner is None or not owner.active or owner.view != ADMINISTRATOR_VIEW:
        raise AccessConfigurationError(
            "The first shared-policy launch must be performed by a configured administrator."
        )
    return replace(configuration, owner_login=owner.login, source_digest=None)


def _configuration_payload(configuration: AccessConfiguration, *, updated_by: str) -> dict[str, object]:
    if configuration.owner_login is None:
        raise AccessConfigurationError("The shared GUI access policy requires an owner.")
    protection = configuration.owner_protection
    return {
        "schemaVersion": SCHEMA_VERSION,
        "metadata": {
            "ownerLogin": configuration.owner_login,
            "updatedAt": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "updatedBy": updated_by,
        },
        "ownerProtection": ({
            "algorithm": protection.algorithm,
            "iterations": protection.iterations,
            "salt": protection.salt,
            "digest": protection.digest,
        } if protection else None),
        "users": {
            profile.login: {
                "displayName": profile.display_name,
                "jobTitle": profile.job_title,
                "view": profile.view,
                "active": profile.active,
            }
            for profile in sorted(configuration.users.values(), key=lambda p: p.login.casefold())
        },
        "views": {
            view: {"workflows": sorted(workflows)}
            for view, workflows in sorted(configuration.workflows_by_view.items())
        },
    }


def _write_payload(config_path: Path, payload: Mapping[str, object]) -> None:
    ensure_hidden_directory(config_path.parent)
    encoded = (json.dumps(payload, indent=2) + "\n").encode()
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{config_path.name}.", suffix=".tmp", dir=config_path.parent
    )
    try:
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(encoded)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary_name, config_path)
    finally:
        try:
            Path(temporary_name).unlink()
        except FileNotFoundError:
            pass


def create_shared_access_configuration(
    config_path: Path, configuration: AccessConfiguration, *, actor_login: str
) -> AccessConfiguration:
    """Create the first shared policy without overwriting an existing file."""
    if config_path.exists():
        raise AccessConfigurationConflictError(
            "The shared access policy was created by another user. Reload the app."
        )
    payload = _configuration_payload(configuration, updated_by=actor_login)
    _parse_access_payload(payload, "")
    _write_payload(config_path, payload)
    return load_access_configuration(config_path)


def save_access_configuration(
    config_path: Path,
    configuration: AccessConfiguration,
    *,
    actor_login: str,
    owner_password: str | None = None,
) -> AccessConfiguration:
    """Validate and atomically save an administrator policy update."""
    current = load_access_configuration(config_path)
    if current.source_digest != configuration.source_digest:
        raise AccessConfigurationConflictError(
            "Another administrator changed access. Reload before trying again."
        )
    if not current.is_administrator(actor_login):
        raise AccessConfigurationError("Only an active administrator can update access.")

    owner_key = current.owner_login.casefold() if current.owner_login else None
    owner_changed = (
        configuration.owner_login != current.owner_login
        or configuration.owner_protection != current.owner_protection
        or (owner_key is not None and configuration.users.get(owner_key) != current.users.get(owner_key))
    )
    if owner_changed:
        if current.owner_protection is None:
            establishing_protection = (
                actor_login.casefold() == owner_key
                and configuration.owner_login == current.owner_login
                and configuration.users.get(owner_key) == current.users.get(owner_key)
                and configuration.owner_protection is not None
            )
            if not establishing_protection:
                raise OwnerProtectionError("Only the policy owner can establish owner protection.")
        elif owner_password is None or not verify_owner_password(current.owner_protection, owner_password):
            raise OwnerProtectionError("The owner password is incorrect.")

    payload = _configuration_payload(configuration, updated_by=actor_login)
    _parse_access_payload(payload, "")
    backup_path = config_path.with_name(f".{config_path.stem}.backup.json")
    shutil.copy2(config_path, backup_path)
    _write_payload(config_path, payload)
    return load_access_configuration(config_path)


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
    return tuple(d for d in definitions if d.workflow_id in allowed_ids)
