from __future__ import annotations

import os
from collections.abc import Mapping
from dataclasses import dataclass, field
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
