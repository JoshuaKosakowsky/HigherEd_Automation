"""Validated Banner activity extraction, independent of GUI and authentication."""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date, timedelta
from numbers import Integral
from typing import Protocol

import pandas as pd

from shared.insights.client import InsightsAPIError


_ROW_COUNT = "__activity_row_count"


class SQLExecutor(Protocol):
    def run_sql(self, sql: str) -> pd.DataFrame: ...


@dataclass(frozen=True)
class BannerActivityParameters:
    """Inclusive feed dates and explicitly selected Banner detail codes."""

    start_date: date
    end_date: date
    detail_codes: tuple[str, ...]

    def __post_init__(self) -> None:
        # Exact date types exclude datetime values with hidden time components.
        if type(self.start_date) is not date or type(self.end_date) is not date:
            raise ValueError("Enter start and end feed dates as YYYY-MM-DD.")
        if self.start_date > self.end_date:
            raise ValueError("End Feed Date must be on or after Start Feed Date.")
        if self.end_date == date.max:
            raise ValueError("End Feed Date must be earlier than 9999-12-31.")
        if not isinstance(self.detail_codes, tuple) or not self.detail_codes:
            raise ValueError("Select at least one detail code.")
        if any(
            not isinstance(code, str) or re.fullmatch(r"[A-Z0-9]{4}", code) is None
            for code in self.detail_codes
        ):
            raise ValueError("Detail codes must contain four letters or digits, separated by commas.")

    @classmethod
    def from_inputs(cls, start_date: str, end_date: str, detail_codes: str) -> BannerActivityParameters:
        """Validate untrusted GUI inputs before building any SQL or signing in."""
        dates = []
        for value in (start_date, end_date):
            if not isinstance(value, str) or re.fullmatch(r"[0-9]{4}-[0-9]{2}-[0-9]{2}", value) is None:
                raise ValueError("Enter start and end feed dates as YYYY-MM-DD.")
            try:
                dates.append(date.fromisoformat(value))
            except ValueError:
                raise ValueError("Enter valid start and end feed dates as YYYY-MM-DD.") from None
        if not isinstance(detail_codes, str):
            raise ValueError("Enter detail codes separated by commas.")
        if not detail_codes.strip():
            raise ValueError("Select at least one detail code.")
        codes = tuple(dict.fromkeys(code.strip().upper() for code in detail_codes.split(",")))
        return cls(dates[0], dates[1], codes)

    def render_sql(self, template: str) -> str:
        """Render the same native template published as an Insights question."""
        replacements = {
            "{{start_date}}": f"'{self.start_date.isoformat()}'",
            "{{end_date}}": f"'{self.end_date.isoformat()}'",
            "{{detail_codes}}": "t.tbraccd_detail_code IN (" + ", ".join(
                f"'{code}'" for code in self.detail_codes
            ) + ")",
        }
        for marker, value in replacements.items():
            if marker not in template:
                raise ValueError("The Banner activity query is missing a required parameter.")
            template = template.replace(marker, value)
        if "{{" in template or "}}" in template or "[[" in template:
            raise ValueError("The Banner activity query has an unsupported parameter.")
        return template


def extract_banner_activity(
    executor: SQLExecutor,
    parameters: BannerActivityParameters,
    *,
    sql_template: str,
) -> pd.DataFrame:
    """Return complete date slices, or fail rather than export a capped result.

    The executor is injected so future workflows can reuse this without the
    GUI, browser login, or coupling to a particular database transport.
    """
    def fetch(window: BannerActivityParameters) -> pd.DataFrame:
        sql = window.render_sql(sql_template).strip().rstrip(";")
        # Count before Insights applies its result cap; keep this out of exports.
        result = executor.run_sql(
            f"SELECT activity.*, COUNT(*) OVER () AS {_ROW_COUNT}\n"
            f"FROM (\n{sql}\n) AS activity"
        )
        if _ROW_COUNT not in result.columns:
            raise InsightsAPIError("Insights omitted the activity completeness check. No workbook was saved.")
        counts = result[_ROW_COUNT]
        if not result.empty:
            if any(
                not (isinstance(value, Integral) and not isinstance(value, bool))
                and not (isinstance(value, str) and re.fullmatch(r"[0-9]+", value))
                for value in counts
            ):
                raise InsightsAPIError("Insights returned an invalid activity row count. No workbook was saved.")
            totals = {int(value) for value in counts}
            if len(totals) != 1 or next(iter(totals)) < len(result):
                raise InsightsAPIError("Insights returned inconsistent activity row counts. No workbook was saved.")
            if next(iter(totals)) > len(result):
                if window.start_date == window.end_date:
                    raise InsightsAPIError(
                        f"Insights limited the results for {window.start_date.isoformat()}. "
                        "Select fewer detail codes for that day. No workbook was saved."
                    )
                midpoint = window.start_date + (window.end_date - window.start_date) // 2
                earlier = fetch(BannerActivityParameters(
                    window.start_date, midpoint, window.detail_codes,
                ))
                later = fetch(BannerActivityParameters(
                    midpoint + timedelta(days=1), window.end_date, window.detail_codes,
                ))
                # Date partitions do not overlap. Preserve legitimate duplicate
                # transactions; the slim export has no stable transaction key.
                return pd.concat([earlier, later], ignore_index=True)
        return result.drop(columns=[_ROW_COUNT]).reset_index(drop=True)

    return fetch(parameters)
