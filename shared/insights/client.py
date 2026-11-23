from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any, TypeVar

import pandas as pd
import requests
from requests.exceptions import RequestException, Timeout

from shared.insights.diagnostics import DATASET_PATH, log_query_success, log_request_failure


_Result = TypeVar("_Result")


class InsightsAPIError(RuntimeError):
    """Raised when an Ellucian Insights API request fails."""

    def __init__(
        self,
        message: str,
        *,
        status_code: int | None = None,
        code: str | None = None,
    ) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.code = code


@dataclass(frozen=True)
class InsightsUser:
    """Safe identity fields for the currently authenticated API principal."""

    id: int | None
    first_name: str | None
    last_name: str | None
    email: str | None
    is_superuser: bool


@dataclass(frozen=True)
class InsightsDatabase:
    """Non-secret metadata for a database visible to the current principal."""

    id: int
    name: str
    engine: str | None
    initial_sync_status: str | None
    is_sample: bool


@dataclass(frozen=True)
class InsightsServerInfo:
    """Allow-listed version fields from the Metabase server properties."""

    version_tag: str | None
    version_date: str | None
    version_hash: str | None


class InsightsClient:
    """Execute native SQL through the Ellucian Insights API."""

    def __init__(
        self,
        base_url: str,
        database_id: int | None = None,
        *,
        api_key: str | None = None,
        session_token: str | None = None,
        timeout: int = 120,
        http_session: requests.Session | None = None,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.database_id = database_id
        self._api_key = api_key.strip() if api_key else None
        self._session_token = (
            session_token.strip() if session_token else None
        )
        self.timeout = timeout
        self._http_session = http_session or requests.Session()
        self._owns_http_session = http_session is None

        if not self._api_key and not self._session_token:
            raise ValueError(
                "Either an API key or a session token must be supplied."
            )

        if self._api_key and self._session_token:
            raise ValueError(
                "Supply either an API key or a session token, not both."
            )

    def _headers(self) -> dict[str, str]:
        headers = {
            "Accept": "application/json",
            "Content-Type": "application/json",
        }

        if self._api_key:
            headers["X-API-Key"] = self._api_key
        else:
            headers["X-Metabase-Session"] = self._session_token or ""

        return headers

    def close(self) -> None:
        """Close the underlying HTTP session when the client owns it."""

        if self._owns_http_session:
            self._http_session.close()

    def __enter__(self) -> InsightsClient:
        return self

    def __exit__(self, *args: object) -> None:
        self.close()

    def _request(
        self,
        method: str,
        path: str,
        *,
        payload: dict[str, Any] | None = None,
    ) -> requests.Response:
        try:
            response = self._http_session.request(
                method,
                f"{self.base_url}{path}",
                headers=self._headers(),
                json=payload,
                timeout=self.timeout,
                allow_redirects=False,
            )
        except Timeout as error:
            log_request_failure(method, path, "timeout", response=error.response,
                                request=error.request, timeout=self.timeout)
            raise InsightsAPIError(
                f"The Insights request timed out: {method} {path}", code="timeout",
            ) from None
        except RequestException as error:
            log_request_failure(method, path, "connection", response=error.response,
                                request=error.request, timeout=self.timeout)
            raise InsightsAPIError(
                f"Could not connect to the Insights API: {method} {path}", code="connection",
            ) from None

        if not 200 <= response.status_code < 300:
            log_request_failure(method, path, "http", response=response)
            raise InsightsAPIError(
                f"Insights rejected {method} {path} "
                f"(HTTP {response.status_code}).",
                status_code=response.status_code,
                code="http",
            )

        return response

    def _request_json(
        self, method: str, path: str, parse: Callable[[Any], _Result], *,
        payload: dict[str, Any] | None = None,
    ) -> _Result:
        response = self._request(method, path, payload=payload)
        try:
            result = response.json()
        except (ValueError, RecursionError):
            log_request_failure(method, path, "invalid_json", response=response)
            raise InsightsAPIError(
                f"Insights returned non-JSON data for {method} {path}.", code="invalid_response",
            ) from None

        try:
            parsed = parse(result)
        except InsightsAPIError as error:
            log_request_failure(method, path, error.code or "invalid_response",
                                response=response, result=result)
            raise
        if path == DATASET_PATH:
            log_query_success(response)
        return parsed

    def logout(self) -> None:
        """Revoke the current Metabase session token."""

        if self._api_key:
            raise ValueError("API keys cannot be logged out as sessions.")

        self._request("DELETE", "/api/session")

    def _build_payload(self, sql: str) -> dict[str, Any]:
        if self.database_id is None:
            raise InsightsAPIError(
                "Select a verified database ID before executing SQL. "
                "This client is configured for metadata discovery only."
            )
        sql = sql.strip()

        if not sql:
            raise ValueError("The SQL query is empty.")

        return {
            "lib/type": "mbql/query",
            "database": self.database_id,
            "parameters": [],
            "stages": [
                {
                    "native": sql,
                    "lib/type": "mbql.stage/native",
                    "template-tags": {},
                }
            ],
        }

    def run_sql(self, sql: str) -> pd.DataFrame:
        """Execute SQL and return the results as a pandas DataFrame."""

        return self._request_json(
            "POST", DATASET_PATH, self._query_frame, payload=self._build_payload(sql),
        )

    @staticmethod
    def _query_frame(result: Any) -> pd.DataFrame:
        if not isinstance(result, dict):
            raise InsightsAPIError(
                "Insights returned an unexpected query response."
            )

        if result.get("status") != "completed":
            raise InsightsAPIError(
                "Insights did not complete the query. Check the SQL in the "
                "Insights editor; server error details are withheld.", code="query_failed",
            )

        data = result.get("data")

        if not isinstance(data, dict):
            raise InsightsAPIError(
                "Insights returned no query result data."
            )

        rows = data.get("rows")
        metadata = data.get("cols", [])

        if not isinstance(rows, list) or not isinstance(metadata, list):
            raise InsightsAPIError(
                "Insights returned malformed row or column data."
            )

        if any(not isinstance(column, dict) for column in metadata):
            raise InsightsAPIError(
                "Insights returned malformed column metadata."
            )

        columns = [
            column.get("display_name")
            or column.get("name")
            or f"column_{index + 1}"
            for index, column in enumerate(metadata)
        ]

        if rows and not columns:
            raise InsightsAPIError(
                "Insights returned rows without column metadata."
            )

        try:
            frame = pd.DataFrame(rows, columns=columns)
        except (ValueError, TypeError):
            raise InsightsAPIError(
                "Insights returned rows incompatible with its column metadata.", code="invalid_response",
            ) from None
        # Some callers subdivide capped results. Single-query reports can use
        # this Metabase flag to reject a partial workbook before publication.
        if data.get("rows_truncated"):
            frame.attrs["rows_truncated"] = True
        return frame

    def get_current_user(self) -> InsightsUser:
        """Return allow-listed fields for the authenticated principal."""

        return self._request_json("GET", "/api/user/current", self._current_user)

    @staticmethod
    def _current_user(result: Any) -> InsightsUser:
        if not isinstance(result, dict):
            raise InsightsAPIError(
                "Insights returned unexpected current-user metadata."
            )

        return InsightsUser(
            id=_optional_int(result.get("id")),
            first_name=_optional_string(result.get("first_name")),
            last_name=_optional_string(result.get("last_name")),
            email=_optional_string(result.get("email")),
            is_superuser=bool(result.get("is_superuser", False)),
        )

    def list_databases(self) -> list[InsightsDatabase]:
        """List non-secret metadata for databases visible to this principal."""

        return self._request_json("GET", "/api/database", self._databases)

    @staticmethod
    def _databases(result: Any) -> list[InsightsDatabase]:
        if isinstance(result, dict):
            databases = result.get("data")
        else:
            databases = result

        if not isinstance(databases, list):
            raise InsightsAPIError(
                "Insights returned unexpected database metadata."
            )

        summaries: list[InsightsDatabase] = []

        for database in databases:
            if not isinstance(database, dict):
                raise InsightsAPIError(
                    "Insights returned malformed database metadata."
                )

            database_id = _optional_int(database.get("id"))
            database_name = _optional_string(database.get("name"))

            if database_id is None or database_name is None:
                raise InsightsAPIError(
                    "Insights database metadata is missing an ID or name."
                )

            summaries.append(
                InsightsDatabase(
                    id=database_id,
                    name=database_name,
                    engine=_optional_string(database.get("engine")),
                    initial_sync_status=_optional_string(
                        database.get("initial_sync_status")
                    ),
                    is_sample=bool(database.get("is_sample", False)),
                )
            )

        return summaries

    def get_server_info(self) -> InsightsServerInfo:
        """Return only version fields from the public server properties."""

        return self._request_json("GET", "/api/session/properties", self._server_info)

    @staticmethod
    def _server_info(result: Any) -> InsightsServerInfo:
        if not isinstance(result, dict):
            raise InsightsAPIError(
                "Insights returned unexpected server metadata."
            )

        version = result.get("version", {})

        if not isinstance(version, dict):
            raise InsightsAPIError(
                "Insights returned malformed version metadata."
            )

        return InsightsServerInfo(
            version_tag=_optional_string(version.get("tag")),
            version_date=_optional_string(version.get("date")),
            version_hash=_optional_string(version.get("hash")),
        )

    def run_sql_file(
        self,
        sql_path: str | Path,
    ) -> pd.DataFrame:
        """Read a SQL file and execute its contents."""

        path = Path(sql_path)

        if not path.is_file():
            raise FileNotFoundError(
                f"SQL file was not found: {path}"
            )

        sql = path.read_text(encoding="utf-8")

        return self.run_sql(sql)


def _optional_string(value: object) -> str | None:
    return value if isinstance(value, str) else None


def _optional_int(value: object) -> int | None:
    return value if isinstance(value, int) and not isinstance(value, bool) else None
