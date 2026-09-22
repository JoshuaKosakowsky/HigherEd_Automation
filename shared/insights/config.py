from __future__ import annotations

import os
import json
from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path
from urllib.parse import urlsplit


class InsightsConfigurationError(RuntimeError):
    """Raised when Insights environment configuration is invalid."""


@dataclass(frozen=True)
class InsightsSettings:
    """Connection settings for one explicitly selected Insights environment."""

    environment: str
    base_url: str
    database_id: int
    api_key: str | None = field(default=None, repr=False)
    sso_start_url: str | None = None

    @classmethod
    def from_environment(
        cls,
        environ: Mapping[str, str] | None = None,
    ) -> InsightsSettings:
        values = os.environ if environ is None else environ
        environment = values.get("INSIGHTS_ENV", "TEST").strip().upper()

        if environment not in {"TEST", "PROD"}:
            raise InsightsConfigurationError(
                "INSIGHTS_ENV must be either TEST or PROD."
            )

        prefix = f"INSIGHTS_{environment}"
        base_url = _required(values, f"{prefix}_BASE_URL").rstrip("/")
        parsed_url = urlsplit(base_url)

        if (
            parsed_url.scheme != "https"
            or not parsed_url.netloc
            or parsed_url.username
            or parsed_url.password
            or parsed_url.query
            or parsed_url.fragment
        ):
            raise InsightsConfigurationError(
                f"{prefix}_BASE_URL must be an HTTPS URL without credentials, "
                "a query string, or a fragment."
            )

        database_id_text = _required(values, f"{prefix}_DATABASE_ID")

        try:
            database_id = int(database_id_text)
        except ValueError as error:
            raise InsightsConfigurationError(
                f"{prefix}_DATABASE_ID must be a positive integer."
            ) from error

        if database_id <= 0:
            raise InsightsConfigurationError(
                f"{prefix}_DATABASE_ID must be a positive integer."
            )

        api_key = values.get(f"{prefix}_API_KEY", "").strip() or None
        sso_start_url = values.get(f"{prefix}_SSO_START_URL", "").strip() or None
        if sso_start_url:
            try:
                start = urlsplit(sso_start_url)
                valid_start = (
                    start.scheme == "https"
                    and bool(start.hostname)
                    and not start.username
                    and not start.password
                    and not start.query
                    and not start.fragment
                    and (start.port is None or 1 <= start.port <= 65535)
                )
            except ValueError:
                valid_start = False
            if not valid_start:
                raise InsightsConfigurationError(
                    f"{prefix}_SSO_START_URL must be an HTTPS starting page "
                    "without credentials, a query string, or a fragment. "
                    "Do not configure a token-bearing SSO redirect URL."
                )

        return cls(
            environment=environment,
            base_url=base_url,
            database_id=database_id,
            api_key=api_key,
            sso_start_url=sso_start_url,
        )


def _required(values: Mapping[str, str], name: str) -> str:
    value = values.get(name, "").strip()

    if not value:
        raise InsightsConfigurationError(
            f"Required environment variable is missing: {name}"
        )

    return value


DEPARTMENT_CONFIG_PATH = (
    Path(__file__).resolve().parents[2] / "config" / "institutions" / "mines" / "insights.json"
)


@dataclass(frozen=True)
class InsightsDepartmentProfile:
    settings: InsightsSettings
    experience_url: str


def load_department_profiles(
    path: Path = DEPARTMENT_CONFIG_PATH,
) -> dict[str, InsightsDepartmentProfile | None]:
    """Load deployment-wide, non-secret GUI settings, without reading .env.

    A null profile is deliberately unavailable. Do not infer PROD from TEST
    or discover/trust a different API destination from a browser redirect.
    """
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
        if (
            not isinstance(payload, dict)
            or set(payload) != {"schemaVersion", "environments"}
            or payload["schemaVersion"] != 1
            or set(payload["environments"]) != {"TEST", "PROD"}
        ):
            raise ValueError
        profiles = {}
        for environment, entry in payload["environments"].items():
            if entry is None:
                profiles[environment] = None
                continue
            keys = {"base_url", "database_id", "sso_start_url", "experience_url"}
            if not isinstance(entry, dict) or set(entry) != keys:
                raise ValueError
            if type(entry["database_id"]) is not int:
                raise ValueError
            if any(not isinstance(entry[key], str) or not entry[key].strip()
                   for key in keys - {"database_id"}):
                raise ValueError
            prefix = f"INSIGHTS_{environment}"
            values = {
                "INSIGHTS_ENV": environment,
                f"{prefix}_BASE_URL": entry["base_url"],
                f"{prefix}_DATABASE_ID": str(entry["database_id"]),
                f"{prefix}_SSO_START_URL": entry["sso_start_url"],
            }
            settings = InsightsSettings.from_environment(values)
            # Use the same credential-free URL validation for the launch link.
            values[f"{prefix}_SSO_START_URL"] = entry["experience_url"]
            experience = InsightsSettings.from_environment(values).sso_start_url
            base = urlsplit(settings.base_url)
            if base.path or base.port not in (None, 443):
                raise ValueError
            profiles[environment] = InsightsDepartmentProfile(settings, experience or "")
        return profiles
    except (OSError, UnicodeError, ValueError, TypeError, AttributeError, KeyError):
        raise InsightsConfigurationError(
            "Department Insights settings are unavailable or invalid. "
            "Contact the application owner; no personal .env setup is needed."
        ) from None


def load_configured_settings(
    *,
    environment: str | None = None,
    environ: Mapping[str, str] | None = None,
    path: Path = DEPARTMENT_CONFIG_PATH,
) -> InsightsSettings:
    """Load one environment from department config with optional local overrides.

    Department URLs and database IDs are non-secret deployment configuration.
    A local environment may still select TEST/PROD, supply an API key, or fully
    override both endpoint fields for a different deployment.
    """
    values = os.environ if environ is None else environ
    selected = (
        environment if environment is not None else values.get("INSIGHTS_ENV", "TEST")
    ).strip().upper()
    if selected not in {"TEST", "PROD"}:
        raise InsightsConfigurationError(
            "Insights environment must be either TEST or PROD."
        )

    prefix = f"INSIGHTS_{selected}"
    endpoint_names = (f"{prefix}_BASE_URL", f"{prefix}_DATABASE_ID")
    if any(values.get(name, "").strip() for name in endpoint_names):
        explicit_values = dict(values)
        explicit_values["INSIGHTS_ENV"] = selected
        return InsightsSettings.from_environment(explicit_values)

    profile = load_department_profiles(path)[selected]
    if profile is None:
        raise InsightsConfigurationError(
            f"Insights {selected} is not configured for the department."
        )

    configured_values = {
        "INSIGHTS_ENV": selected,
        f"{prefix}_BASE_URL": profile.settings.base_url,
        f"{prefix}_DATABASE_ID": str(profile.settings.database_id),
        f"{prefix}_SSO_START_URL": (
            values.get(f"{prefix}_SSO_START_URL", "").strip()
            or profile.settings.sso_start_url
            or ""
        ),
        f"{prefix}_API_KEY": values.get(f"{prefix}_API_KEY", "").strip(),
    }
    return InsightsSettings.from_environment(configured_values)
