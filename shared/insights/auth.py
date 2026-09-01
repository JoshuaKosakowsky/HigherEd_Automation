from __future__ import annotations

import requests
from requests.exceptions import JSONDecodeError, RequestException


class InsightsAuthenticationError(RuntimeError):
    """Raised when authentication with Ellucian Insights fails."""


def exchange_sso_jwt(
    base_url: str,
    jwt_token: str,
    timeout: int = 30,
) -> str:
    """Exchange an Ellucian SSO JWT for a temporary Insights session."""

    jwt_token = jwt_token.strip()

    if not jwt_token:
        raise InsightsAuthenticationError(
            "An SSO JWT was not supplied."
        )

    try:
        response = requests.post(
            f"{base_url.rstrip('/')}/auth/sso/to_session",
            headers={
                "Accept": "application/json",
                "Content-Type": "application/json",
            },
            json={"jwt": jwt_token},
            timeout=timeout,
        )
    except RequestException as error:
        raise InsightsAuthenticationError(
            "Could not connect to the Insights authentication endpoint."
        ) from error

    if not response.ok:
        raise InsightsAuthenticationError(
            "Insights rejected the temporary SSO authentication "
            f"(HTTP {response.status_code})."
        )

    try:
        result = response.json()
    except JSONDecodeError as error:
        raise InsightsAuthenticationError(
            "Insights returned a non-JSON authentication response."
        ) from error

    if not isinstance(result, dict):
        raise InsightsAuthenticationError(
            "Insights returned an unexpected authentication response."
        )

    session_token = result.get("session_token")

    if not isinstance(session_token, str) or not session_token.strip():
        raise InsightsAuthenticationError(
            "Insights responded successfully but did not return "
            "a session_token."
        )

    return session_token.strip()
