from __future__ import annotations

from collections.abc import Callable

from shared.insights.browser_auth import login_and_exchange_sso
from shared.insights.client import InsightsAPIError, InsightsClient
from shared.insights.config import InsightsSettings
from shared.insights.session_cache import (
    CachedInsightsSession,
    DailyInsightsSessionCache,
    InsightsCredentialError,
)


class InsightsSessionError(RuntimeError):
    """Raised when a cached daily Insights session cannot be managed safely."""


def build_authenticated_client(
    settings: InsightsSettings,
    *,
    browser: str = "edge",
    force_login: bool = False,
    cache: DailyInsightsSessionCache | None = None,
    acquire_session: Callable[[], str] | None = None,
) -> tuple[InsightsClient, str]:
    """Build a client using an API key or a validated daily SSO session."""

    if settings.api_key:
        return (
            InsightsClient(
                settings.base_url,
                settings.database_id,
                api_key=settings.api_key,
            ),
            "API key",
        )

    session_cache = cache or DailyInsightsSessionCache(settings)
    cached = session_cache.load()

    if cached and not cached.matches(settings):
        session_cache.delete()
        cached = None

    if cached and cached.principal_id is None:
        _revoke_cached_session(settings, cached)
        session_cache.delete()
        cached = None

    if cached and (force_login or not cached.is_valid()):
        _revoke_cached_session(settings, cached)
        session_cache.delete()
        cached = None

    if cached:
        client = InsightsClient(
            settings.base_url,
            settings.database_id,
            session_token=cached.session_token,
        )

        try:
            user = client.get_current_user()
        except InsightsAPIError as error:
            client.close()

            if error.status_code == 401:
                session_cache.delete()
                cached = None
            else:
                raise
        else:
            if (
                cached.principal_id is not None
                and user.id != cached.principal_id
            ):
                client.close()
                _revoke_cached_session(settings, cached)
                session_cache.delete()
                raise InsightsSessionError(
                    "The cached Insights session resolved to a different "
                    "principal and was revoked."
                )

            return client, "cached daily SSO session"

    session_token = (
        acquire_session()
        if acquire_session is not None
        else login_and_exchange_sso(settings, browser=browser)
    )
    client = InsightsClient(
        settings.base_url,
        settings.database_id,
        session_token=session_token,
    )

    try:
        user = client.get_current_user()

        if user.id is None:
            raise InsightsSessionError(
                "Insights did not identify the authenticated principal. The "
                "session will not be cached."
            )

        session_cache.save(
            CachedInsightsSession.create(
                settings,
                session_token,
                user.id,
            )
        )
    except (
        InsightsAPIError,
        InsightsCredentialError,
        InsightsSessionError,
    ):
        try:
            client.logout()
        finally:
            client.close()
        raise

    return client, "new daily SSO session"


def clear_cached_session(
    settings: InsightsSettings,
    *,
    cache: DailyInsightsSessionCache | None = None,
) -> bool:
    """Revoke and delete the selected environment's cached session."""

    session_cache = cache or DailyInsightsSessionCache(settings)
    cached = session_cache.load()

    if cached is None:
        return False

    if cached.base_url != settings.base_url:
        session_cache.delete()
        return True

    _revoke_cached_session(settings, cached)
    session_cache.delete()
    return True


def _revoke_cached_session(
    settings: InsightsSettings,
    cached: CachedInsightsSession,
) -> None:
    client = InsightsClient(
        settings.base_url,
        settings.database_id,
        session_token=cached.session_token,
    )

    try:
        client.logout()
    except InsightsAPIError as error:
        if error.status_code not in {401, 404}:
            raise InsightsSessionError(
                "The cached Insights session could not be revoked. It was "
                "not removed from the OS credential vault."
            ) from error
    finally:
        client.close()
