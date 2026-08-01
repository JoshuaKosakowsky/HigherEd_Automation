from __future__ import annotations

from pathlib import Path
from typing import Any

import pandas as pd
import requests
from requests.exceptions import JSONDecodeError, RequestException, Timeout


class InsightsAPIError(RuntimeError):
    """Raised when an Ellucian Insights API request fails."""


class InsightsClient:
    """Execute native SQL through the Ellucian Insights API."""

    def __init__(
        self,
        base_url: str,
        database_id: int,
        *,
        api_key: str | None = None,
        session_token: str | None = None,
        timeout: int = 120,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.database_id = database_id
        self.api_key = api_key.strip() if api_key else None
        self.session_token = (
            session_token.strip() if session_token else None
        )
        self.timeout = timeout

        if not self.api_key and not self.session_token:
            raise ValueError(
                "Either an API key or a session token must be supplied."
            )

        if self.api_key and self.session_token:
            raise ValueError(
                "Supply either an API key or a session token, not both."
            )

    def _headers(self) -> dict[str, str]:
        headers = {
            "Accept": "application/json",
            "Content-Type": "application/json",
        }

        if self.api_key:
            headers["X-API-Key"] = self.api_key
        else:
            headers["X-Metabase-Session"] = self.session_token or ""

        return headers

    def _build_payload(self, sql: str) -> dict[str, Any]:
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

        try:
            response = requests.post(
                f"{self.base_url}/api/dataset",
                headers=self._headers(),
                json=self._build_payload(sql),
                timeout=self.timeout,
            )
        except Timeout as error:
            raise InsightsAPIError(
                "The Insights query timed out."
            ) from error
        except RequestException as error:
            raise InsightsAPIError(
                "Could not connect to the Insights API."
            ) from error

        if response.status_code not in {200, 202}:
            raise InsightsAPIError(
                "Insights rejected the query.\n"
                f"HTTP status: {response.status_code}\n"
                f"Response: {response.text}"
            )

        try:
            result = response.json()
        except JSONDecodeError as error:
            raise InsightsAPIError(
                "Insights returned a non-JSON response."
            ) from error

        if result.get("status") != "completed":
            raise InsightsAPIError(
                "Insights did not complete the query.\n"
                f"Query status: {result.get('status')!r}"
            )

        data = result.get("data")

        if not isinstance(data, dict):
            raise InsightsAPIError(
                "Insights returned no query result data."
            )

        rows = data.get("rows", [])
        metadata = data.get("cols", [])

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

        return pd.DataFrame(rows, columns=columns)

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