"""Complete ordered report extraction without relying on the API's row limit."""
from __future__ import annotations

from numbers import Integral
import re

import pandas as pd

from shared.insights.banner_activity import SQLExecutor
from shared.insights.client import InsightsAPIError
from shared.progress import ProgressReporter


ROW_NUMBER = "__Report Row Number"
ROW_COUNT = "Report Row Count"


def _integer(value: object) -> int:
    if isinstance(value, Integral) and not isinstance(value, bool):
        return int(value)
    if isinstance(value, str) and re.fullmatch(r"[0-9]{1,18}", value):
        return int(value)
    raise InsightsAPIError("The report returned an invalid completeness guard. No workbook was saved.")


def extract_paged_report(
    executor: SQLExecutor, sql: str, *, progress: ProgressReporter | None = None,
    page_size: int = 1000,
) -> pd.DataFrame:
    """Read a deterministic report ordinal and check every page and total.

    The query must emit unique, contiguous ROW_NUMBER and a global ROW_COUNT.
    Counts/ordinals catch truncation and many concurrent changes, but pages are
    separate database reads, not a transactionally consistent snapshot.
    """
    if isinstance(page_size, bool) or not isinstance(page_size, int) or page_size < 1:
        raise ValueError("Report page size must be a positive integer.")
    query = sql.strip().removesuffix(";")
    parts: list[pd.DataFrame] = []
    expected: int | None = None
    columns: list[str] | None = None
    received = 0
    while True:
        if progress:
            progress.report(f"Reading report details: {received:,} rows received")
        page = executor.run_sql(
            f'SELECT * FROM (\n{query}\n) AS report_page '
            f'WHERE "{ROW_NUMBER}" > {received} '
            f'ORDER BY "{ROW_NUMBER}" LIMIT {page_size}'
        )
        if list(page.columns).count(ROW_NUMBER) != 1 or list(page.columns).count(ROW_COUNT) != 1:
            raise InsightsAPIError("The report omitted its completeness guards. No workbook was saved.")
        if columns is not None and list(page.columns) != columns:
            raise InsightsAPIError("Report columns changed during extraction. No workbook was saved.")
        columns = list(page.columns)
        if page.empty:
            if received:
                raise InsightsAPIError("The report ended before all rows arrived. Retry; no workbook was saved.")
            return page.drop(columns=[ROW_NUMBER])
        counts = {_integer(value) for value in page[ROW_COUNT]}
        if len(counts) != 1:
            raise InsightsAPIError("Report row counts are inconsistent. No workbook was saved.")
        total = counts.pop()
        if total < received + len(page) or (expected is not None and total != expected):
            raise InsightsAPIError("The report changed during extraction. Retry; no workbook was saved.")
        if total > 1_048_575:
            raise InsightsAPIError("The report exceeds one Excel sheet. No workbook was saved.")
        expected = total
        ordinals = [_integer(value) for value in page[ROW_NUMBER]]
        if len(page) > page_size or ordinals != list(range(received + 1, received + len(page) + 1)):
            raise InsightsAPIError("Report rows are missing, repeated or unordered. No workbook was saved.")
        parts.append(page.drop(columns=[ROW_NUMBER]))
        received += len(page)
        if received == expected:
            return pd.concat(parts, ignore_index=True)
