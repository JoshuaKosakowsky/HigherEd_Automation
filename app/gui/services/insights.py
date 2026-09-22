"""Small GUI adapter for department-configured Insights connections."""

from __future__ import annotations

from pathlib import Path

from app.gui.models import WorkflowContext, WorkflowResult
from shared.insights.auth import InsightsAuthenticationError
from shared.insights.browser_auth import InsightsBrowserAuthenticationError
from shared.insights.client import InsightsAPIError
from shared.insights.config import InsightsConfigurationError, load_department_profiles
from shared.insights.session_auth import (
    InsightsSessionError, build_authenticated_client, clear_cached_session,
)
from shared.insights.session_cache import DailyInsightsSessionCache, InsightsCredentialError


CONNECTION_SQL = Path(__file__).resolve().parents[3] / "query/insights_testing/connection_check.sql"


def _login_required() -> str:
    raise InsightsSessionError("Sign-in is required. Click Connect and sign in.")


def run_insights_connection(context: WorkflowContext) -> WorkflowResult:
    """Keep credentials/results out of the GUI's general traceback logger."""
    try:
        if context.mode is None:
            raise InsightsConfigurationError("Choose TEST or PROD explicitly.")
        profile = load_department_profiles()[context.mode.value]
        if profile is None:
            return WorkflowResult(False, "This environment is not configured for the department yet.")
        settings = profile.settings
        action = context.parameters.get("action")
        if action not in {"connect", "reconnect", "check", "logout"}:
            raise InsightsConfigurationError("Unknown connection action.")
        if action == "logout":
            removed = clear_cached_session(settings)
            return WorkflowResult(True, (
                f"{settings.environment}: cached API session revoked and removed."
                if removed else f"{settings.environment}: no cached session was found."
            ) + " Your MyMines browser sign-in is separate.")
        if action == "check":
            cached = DailyInsightsSessionCache(settings).load()
            if not cached or not cached.matches(settings) or not cached.is_valid():
                _login_required()
        client, method = build_authenticated_client(
            settings,
            browser="chrome",
            force_login=action == "reconnect",
            acquire_session=_login_required if action == "check" else None,
        )
        with client:
            principal = client.get_current_user()
            result = client.run_sql_file(CONNECTION_SQL)
            if principal.id is None or result.shape != (1, 1) or result.iloc[0, 0] != 1:
                raise InsightsAPIError("The connection check did not return the expected result.")
        return WorkflowResult(True, (
            f"{settings.environment} verified — account ID {principal.id}; {method}. "
            "SELECT 1 succeeded. No student data queried or saved. "
            "Sign-in may be needed tomorrow or earlier if the server expires your session."
        ))
    except (
        InsightsAuthenticationError, InsightsBrowserAuthenticationError,
        InsightsAPIError, InsightsConfigurationError, InsightsSessionError,
        InsightsCredentialError,
    ) as error:
        return WorkflowResult(False, str(error))
    except Exception:
        # Intentional auth boundary: never log an unexpected exception that
        # could contain a credential-bearing browser URL or response body.
        return WorkflowResult(False, "Connection could not be completed. No technical authentication details were logged. Try again or contact the application owner.")
