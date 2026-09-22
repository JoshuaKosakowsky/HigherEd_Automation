"""Small GUI adapter for department-configured Insights connections."""

from __future__ import annotations

import shutil
import tempfile
from pathlib import Path

import pandas as pd

from app.gui.models import WorkflowContext, WorkflowResult
from shared.insights.auth import InsightsAuthenticationError
from shared.insights.browser_auth import InsightsBrowserAuthenticationError
from shared.insights.client import InsightsAPIError
from shared.insights.config import InsightsConfigurationError, load_department_profiles
from shared.insights.query_catalog import get_query
from shared.insights.session_auth import (
    InsightsSessionError, build_authenticated_client, clear_cached_session,
)
from shared.insights.session_cache import DailyInsightsSessionCache, InsightsCredentialError


CONNECTION_SQL = Path(__file__).resolve().parents[3] / "query/insights_testing/connection_check.sql"
EXCEL_MAX_DATA_ROWS = 1_048_575


def _login_required() -> str:
    raise InsightsSessionError("Sign-in is required. Click Connect and sign in.")


def _export_query(dataframe: pd.DataFrame, output_path: Path) -> None:
    """Write a complete workbook at the selected location without replacing a file."""
    if output_path.suffix.lower() != ".xlsx" or not output_path.is_absolute():
        raise InsightsConfigurationError("Choose an absolute .xlsx output path.")
    if not output_path.parent.is_dir():
        raise InsightsConfigurationError("The selected output folder does not exist.")
    if output_path.exists():
        raise InsightsConfigurationError("That workbook already exists. Choose a new filename.")
    if len(dataframe) > EXCEL_MAX_DATA_ROWS:
        raise InsightsConfigurationError(
            "The query returned too many rows for one Excel sheet. Narrow the query before exporting."
        )

    temporary_path = None
    created_destination = False
    try:
        with tempfile.NamedTemporaryFile(
            prefix=".insights-query-", suffix=".xlsx", dir=output_path.parent,
            delete=False,
        ) as temporary:
            temporary_path = Path(temporary.name)
        dataframe.to_excel(temporary_path, index=False)
        # Exclusive creation protects an existing workbook if the destination
        # appeared while the query or Excel writer was running.
        with output_path.open("xb") as destination:
            created_destination = True
            with temporary_path.open("rb") as source:
                shutil.copyfileobj(source, destination)
    except Exception:
        if created_destination:
            output_path.unlink(missing_ok=True)
        raise
    finally:
        if temporary_path is not None:
            temporary_path.unlink(missing_ok=True)


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
        if action not in {"connect", "reconnect", "check", "logout", "query_export"}:
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
        output_path = None
        if action == "query_export":
            selected_query = context.parameters.get("query_id")
            if not isinstance(selected_query, str):
                raise InsightsConfigurationError("Select an available Insights query.")
            try:
                query = get_query(selected_query)
            except ValueError:
                raise InsightsConfigurationError("Select an available Insights query.") from None
            term_code = context.parameters.get("term_code")
            if term_code is not None and not isinstance(term_code, str):
                raise InsightsConfigurationError("Enter a valid Banner term.")
            try:
                rendered_sql = query.render_sql(term_code)
            except ValueError as error:
                raise InsightsConfigurationError(str(error)) from None
            selected_path = context.parameters.get("output_path")
            if not isinstance(selected_path, (str, Path)):
                raise InsightsConfigurationError("Choose an Excel output file.")
            output_path = Path(selected_path)
            if output_path.suffix.lower() != ".xlsx" or not output_path.is_absolute():
                raise InsightsConfigurationError("Choose an absolute .xlsx output path.")
            if output_path.exists():
                raise InsightsConfigurationError("That workbook already exists. Choose a new filename.")
        client, method = build_authenticated_client(
            settings,
            browser="chrome",
            force_login=action == "reconnect",
            acquire_session=_login_required if action == "check" else None,
        )
        with client:
            if action == "query_export":
                result = (
                    client.run_sql(rendered_sql)
                    if query.term_variable else client.run_sql_file(query.sql_path)
                )
                _export_query(result, output_path)
                return WorkflowResult(
                    True,
                    f"{settings.environment}: exported {len(result):,} rows from {query.title}. "
                    f"Workbook: {output_path}",
                    output_path=output_path,
                )
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
    except (OSError, ValueError, ImportError):
        return WorkflowResult(
            False,
            "The Excel export could not be saved. Check the destination, close any open workbook, and try again."
        )
    except Exception:
        # Intentional auth boundary: never log an unexpected exception that
        # could contain a credential-bearing browser URL or response body.
        return WorkflowResult(False, "Connection could not be completed. No technical authentication details were logged. Try again or contact the application owner.")
