"""Bounded, completeness-checked Insights extraction for annual trends."""
from __future__ import annotations

import csv
from dataclasses import dataclass
from datetime import date
from pathlib import Path

import pandas as pd

from shared.cancellation import CancellationToken
from shared.insights.banner_activity import SQLExecutor
from shared.insights.client import InsightsAPIError
from shared.progress import ProgressReporter
from .config import REQUIRED_COLUMNS, TrendsConfig
from shared.insights.detail_codes import refresh_detail_codes
from .pipeline import run_trends_review

QUERY_PATH = Path(__file__).resolve().parents[2] / "query" / "AR" / "trends" / "transactions_extract.sql"


@dataclass(frozen=True)
class TrendsExtractSettings:
    first_fiscal_year: int
    last_fiscal_year: int
    extract_directory: Path
    page_size: int = 1000

    def __post_init__(self) -> None:
        if any(type(year) is not int or not 1900 <= year <= 9998
               for year in (self.first_fiscal_year, self.last_fiscal_year)):
            raise ValueError("Fiscal years must be four-digit years from 1900 through 9998.")
        if self.first_fiscal_year > self.last_fiscal_year:
            raise ValueError("Last fiscal year must be on or after first fiscal year.")
        if type(self.page_size) is not int or not 1 <= self.page_size <= 10000:
            raise ValueError("Page size must be between 1 and 10000.")


def _integer(value: object) -> int:
    """Reject fractional, null and malformed guard/key values."""
    if isinstance(value, bool):
        raise InsightsAPIError("Insights returned an invalid trends completeness guard.")
    try:
        number = int(value)
        if str(value) not in (str(number), f"{number}.0") or number < 0:
            raise ValueError
        return number
    except (TypeError, ValueError, OverflowError):
        raise InsightsAPIError("Insights returned an invalid trends completeness guard.") from None


def extract_trends(
    executor: SQLExecutor, settings: TrendsExtractSettings, *,
    cancellation: CancellationToken | None = None,
    progress: ProgressReporter | None = None,
) -> list[Path]:
    """Save complete years atomically, streaming pages rather than full years.

    When Insights applies a smaller result cap, retry the same cursor with a
    smaller LIMIT. Never advance a cursor based on a truncated page.
    """
    template = QUERY_PATH.read_text(encoding="utf-8")
    directory = settings.extract_directory
    directory.mkdir(parents=True, exist_ok=False)
    files = []
    for year in range(settings.first_fiscal_year, settings.last_fiscal_year + 1):
        output = directory / f"TGIACCD_fy{year}.csv"
        # Keep in-progress student data covered by the existing *.csv ignore,
        # and outside the annual TGIACCD_fy*.csv discovery pattern.
        temporary = output.with_name(f".{output.stem}.tmp.csv")
        try:
            with temporary.open("x", encoding="utf-8", newline="") as stream:
                writer = csv.DictWriter(stream, fieldnames=REQUIRED_COLUMNS)
                writer.writeheader()
                for month_offset in range(12):
                    month = (6 + month_offset) % 12 + 1
                    calendar_year = year - 1 if month >= 7 else year
                    start = date(calendar_year, month, 1)
                    end = date(calendar_year + (month == 12), month % 12 + 1, 1)
                    cursor = None
                    page_size = settings.page_size
                    remaining = None
                    while True:
                        if cancellation:
                            cancellation.check()
                        if progress:
                            progress.report(f"Extracting FY{year}, {start:%Y-%m} in checked pages")
                        predicate = "TRUE" if cursor is None else (
                            f"(t.tbraccd_pidm, t.tbraccd_tran_number) > ({cursor[0]}, {cursor[1]})"
                        )
                        sql = (template.replace("__START_DATE__", start.isoformat())
                               .replace("__END_DATE__", end.isoformat())
                               .replace("__CURSOR_FILTER__", predicate)
                               .replace("__PAGE_SIZE__", str(page_size)))
                        frame = executor.run_sql(sql)
                        if cancellation:
                            cancellation.check()
                        required = set(REQUIRED_COLUMNS) | {"extract_pidm", "extract_transaction", "extract_remaining_count"}
                        if required - set(frame.columns):
                            raise InsightsAPIError("Insights omitted required trends columns or completeness guards.")
                        if frame.empty:
                            if remaining not in (None, 0):
                                raise InsightsAPIError("Insights returned an incomplete trends month. No report was saved.")
                            break
                        totals = {_integer(value) for value in frame["extract_remaining_count"]}
                        if len(totals) != 1:
                            raise InsightsAPIError("Insights returned inconsistent trends row counts.")
                        total = totals.pop()
                        if remaining is not None and total != remaining:
                            raise InsightsAPIError("Insights trends row counts changed between pages. Retry with a new output filename.")
                        remaining = total
                        expected = min(total, page_size)
                        if len(frame) > expected:
                            raise InsightsAPIError("Insights returned more trends rows than expected.")
                        if len(frame) < expected:
                            page_size = len(frame)
                            continue
                        keys = [(_integer(pidm), _integer(transaction)) for pidm, transaction in
                                zip(frame["extract_pidm"], frame["extract_transaction"])]
                        if any(a >= b for a, b in zip(keys, keys[1:])) or (cursor is not None and keys[0] <= cursor):
                            raise InsightsAPIError("Insights returned duplicate or unordered trends transaction keys.")
                        # CSV preserves identifiers as strings; SQL nulls become empty
                        # cells, matching blank cells in historical TGIACCD exports.
                        data = frame[list(REQUIRED_COLUMNS)].astype(object)
                        writer.writerows(data.where(pd.notna(data), "").to_dict("records"))
                        cursor = keys[-1]
                        remaining -= len(frame)
                        if remaining == 0:
                            break
            if cancellation:
                cancellation.check()
            temporary.replace(output)
            files.append(output)
        finally:
            temporary.unlink(missing_ok=True)
    return files


def run_sql_trends_pipeline(
    executor: SQLExecutor, settings: TrendsExtractSettings, config: TrendsConfig, *,
    cancellation: CancellationToken | None = None,
    progress: ProgressReporter | None = None,
) -> Path:
    """Keep annual sources; publish the existing analysis only after completion."""
    output = config.output_file
    if output.suffix.lower() != ".xlsx" or output.exists():
        raise ValueError("Choose a new .xlsx output filename; existing results are never overwritten.")
    refresh_detail_codes(executor, config.detail_codes_file, cancellation=cancellation, progress=progress)
    output.parent.mkdir(parents=True, exist_ok=True)
    files = extract_trends(executor, settings, cancellation=cancellation, progress=progress)
    return run_trends_review(config, files=files, cancellation=cancellation, progress=progress)
