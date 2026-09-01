from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import date, datetime, time, timedelta, timezone
from typing import Protocol

from shared.insights.config import InsightsSettings


CACHE_FORMAT_VERSION = 1
CREDENTIAL_USERNAME = "metabase-session"


class InsightsCredentialError(RuntimeError):
    """Raised when the operating-system credential vault cannot be used."""


class CredentialStore(Protocol):
    def get_password(self, service: str, username: str) -> str | None: ...

    def set_password(self, service: str, username: str, password: str) -> None: ...

    def delete_password(self, service: str, username: str) -> None: ...


class SystemCredentialStore:
    """Store secrets in Windows Credential Manager or the native OS keychain."""

    def get_password(self, service: str, username: str) -> str | None:
        keyring = _load_keyring()

        try:
            return keyring.get_password(service, username)
        except keyring.errors.KeyringError as error:
            raise InsightsCredentialError(
                "Windows Credential Manager could not read the cached "
                "Insights session."
            ) from error

    def set_password(self, service: str, username: str, password: str) -> None:
        keyring = _load_keyring()

        try:
            keyring.set_password(service, username, password)
        except keyring.errors.KeyringError as error:
            raise InsightsCredentialError(
                "Windows Credential Manager could not save the Insights "
                "session."
            ) from error

    def delete_password(self, service: str, username: str) -> None:
        keyring = _load_keyring()

        try:
            keyring.delete_password(service, username)
        except keyring.errors.PasswordDeleteError:
            return
        except keyring.errors.KeyringError as error:
            raise InsightsCredentialError(
                "Windows Credential Manager could not delete the cached "
                "Insights session."
            ) from error


@dataclass(frozen=True)
class CachedInsightsSession:
    environment: str
    base_url: str
    database_id: int
    principal_id: int | None
    local_date: str
    created_at: datetime
    expires_at: datetime
    session_token: str = field(repr=False)

    @classmethod
    def create(
        cls,
        settings: InsightsSettings,
        session_token: str,
        principal_id: int | None,
        *,
        now: datetime | None = None,
    ) -> CachedInsightsSession:
        now_local = _aware_local_datetime(now)
        tomorrow = now_local.date() + timedelta(days=1)
        next_midnight = datetime.combine(
            tomorrow,
            time.min,
            tzinfo=now_local.tzinfo,
        )

        return cls(
            environment=settings.environment,
            base_url=settings.base_url,
            database_id=settings.database_id,
            principal_id=principal_id,
            local_date=now_local.date().isoformat(),
            created_at=now_local.astimezone(timezone.utc),
            expires_at=next_midnight.astimezone(timezone.utc),
            session_token=session_token,
        )

    def is_valid(self, *, now: datetime | None = None) -> bool:
        now_local = _aware_local_datetime(now)
        return (
            self.local_date == now_local.date().isoformat()
            and now_local.astimezone(timezone.utc) < self.expires_at
        )

    def matches(self, settings: InsightsSettings) -> bool:
        return (
            self.environment == settings.environment
            and self.base_url == settings.base_url
            and self.database_id == settings.database_id
        )

    def to_secret(self) -> str:
        return json.dumps(
            {
                "version": CACHE_FORMAT_VERSION,
                "environment": self.environment,
                "base_url": self.base_url,
                "database_id": self.database_id,
                "principal_id": self.principal_id,
                "local_date": self.local_date,
                "created_at": self.created_at.isoformat(),
                "expires_at": self.expires_at.isoformat(),
                "session_token": self.session_token,
            },
            separators=(",", ":"),
        )

    @classmethod
    def from_secret(cls, secret: str) -> CachedInsightsSession:
        try:
            value = json.loads(secret)
            if not isinstance(value, dict):
                raise TypeError
            if value.get("version") != CACHE_FORMAT_VERSION:
                raise ValueError

            environment = value["environment"]
            base_url = value["base_url"]
            database_id = value["database_id"]
            principal_id = value["principal_id"]
            local_date = value["local_date"]
            created_at = datetime.fromisoformat(value["created_at"])
            expires_at = datetime.fromisoformat(value["expires_at"])
            session_token = value["session_token"]
        except (KeyError, TypeError, ValueError, json.JSONDecodeError) as error:
            raise InsightsCredentialError(
                "The cached Insights credential has an invalid format."
            ) from error

        if (
            environment not in {"TEST", "PROD"}
            or not isinstance(base_url, str)
            or not base_url.startswith("https://")
            or not isinstance(database_id, int)
            or isinstance(database_id, bool)
            or database_id <= 0
            or (
                principal_id is not None
                and (
                    not isinstance(principal_id, int)
                    or isinstance(principal_id, bool)
                )
            )
            or not isinstance(local_date, str)
            or not isinstance(session_token, str)
            or not session_token
            or created_at.tzinfo is None
            or expires_at.tzinfo is None
        ):
            raise InsightsCredentialError(
                "The cached Insights credential has invalid fields."
            )

        try:
            date.fromisoformat(local_date)
        except ValueError as error:
            raise InsightsCredentialError(
                "The cached Insights credential has an invalid date."
            ) from error

        return cls(
            environment=environment,
            base_url=base_url,
            database_id=database_id,
            principal_id=principal_id,
            local_date=local_date,
            created_at=created_at,
            expires_at=expires_at,
            session_token=session_token,
        )


class DailyInsightsSessionCache:
    """Persist one environment-specific session in the native credential vault."""

    def __init__(
        self,
        settings: InsightsSettings,
        *,
        store: CredentialStore | None = None,
    ) -> None:
        self.settings = settings
        self.store = store or SystemCredentialStore()
        self.service = (
            "HigherEd_Automation:EllucianInsights:"
            f"{settings.environment}"
        )

    def load(self) -> CachedInsightsSession | None:
        secret = self.store.get_password(
            self.service,
            CREDENTIAL_USERNAME,
        )

        if secret is None:
            return None

        return CachedInsightsSession.from_secret(secret)

    def save(self, session: CachedInsightsSession) -> None:
        if not session.matches(self.settings):
            raise InsightsCredentialError(
                "Refusing to cache a session for a different environment."
            )

        self.store.set_password(
            self.service,
            CREDENTIAL_USERNAME,
            session.to_secret(),
        )

    def delete(self) -> None:
        self.store.delete_password(
            self.service,
            CREDENTIAL_USERNAME,
        )


def _aware_local_datetime(value: datetime | None) -> datetime:
    if value is None:
        return datetime.now().astimezone()

    if value.tzinfo is None:
        raise ValueError("Session-cache timestamps must include a timezone.")

    return value


def _load_keyring() -> object:
    try:
        import keyring
    except ImportError:
        raise InsightsCredentialError(
            "The keyring package is not installed in the active Python "
            "environment. Run setup.ps1 before using session caching."
        ) from None

    return keyring
