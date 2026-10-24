"""Validate complete report results and prepare dates for Excel consumers."""
from __future__ import annotations

from datetime import date, datetime, timezone

import pandas as pd

from shared.insights.client import InsightsAPIError
from shared.insights.config import InsightsConfigurationError


def checked_report_result(frame: pd.DataFrame, count_column: str) -> pd.DataFrame:
    """Reject missing/capped counts before exposing a report to any exporter."""
    if count_column not in frame.columns or any(
        str(value) != str(len(frame)) for value in frame[count_column]
    ):
        raise InsightsAPIError(
            "Insights returned incomplete or invalid report results. "
            "Run and export the report in Insights. No workbook was saved."
        )
    return frame.drop(columns=[count_column])


def _excel_calendar_date(value: object) -> date | None:
    if pd.isna(value):
        return None
    if isinstance(value, datetime):
        parsed = value
    elif isinstance(value, date):
        return value
    elif isinstance(value, str):
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    else:
        raise TypeError("Expected an ISO calendar date.")
    if parsed.tzinfo is not None:
        parsed = parsed.astimezone(timezone.utc)
    return parsed.date()


def prepare_excel_dates(dataframe: pd.DataFrame) -> pd.DataFrame:
    """Preserve calendar dates through year 9999 and UTC feed timestamps."""
    calendar_columns = {"Account Activity Date", "From Date", "To Date"}
    date_columns = [column for column in dataframe.columns if isinstance(column, str) and (
        column.strip("'\"").endswith("Feed Date") or column.strip("'\"") in calendar_columns
    )]
    if not date_columns:
        return dataframe
    export = dataframe.copy()
    for column in date_columns:
        try:
            if column.strip("'\"") in calendar_columns:
                export[column] = pd.Series(
                    [_excel_calendar_date(value) for value in export[column]],
                    index=export.index, dtype=object,
                )
            else:
                dates = pd.to_datetime(export[column], format="ISO8601", utc=True)
                export[column] = dates.dt.tz_localize(None)
        except (TypeError, ValueError):
            raise InsightsConfigurationError(
                f"Insights returned an unreadable {column} value; no workbook was saved."
            ) from None
    return export
