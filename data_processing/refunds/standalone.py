"""Read the account allocations already calculated by the standalone Refunds.sql."""

from datetime import date, datetime
from decimal import Decimal, InvalidOperation

import pandas as pd

from shared.cancellation import CancellationToken
from shared.insights.client import InsightsAPIError
from shared.insights.query_catalog import get_query
from shared.workflow_logging import report_log_context
from .allocation import REPORT_COLUMNS
from .export import COUNT_COLUMNS, CURRENCY_COLUMNS, THIRD_PARTY_COLUMNS
from .extract import RefundExtractError, SQLClient, normalize_refund_columns
from .terms import derive_target_term, validate_term


def _excel_number(value: object) -> Decimal | None:
    if value is None:
        return None
    number = Decimal(str(value))
    if not number.is_finite():
        raise ValueError
    return number


def _excel_date(value: object) -> date | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value.replace(tzinfo=None)
    if isinstance(value, date):
        return value
    return datetime.fromisoformat(str(value).replace("Z", "+00:00")).replace(tzinfo=None)


def read_standalone_refund_report(
    client: SQLClient, target_term: str, run_date: date, cancellation: CancellationToken | None = None,
) -> pd.DataFrame:
    term = validate_term(target_term)
    query = get_query("refund_review")
    sql = query.render_sql()
    # The current-term request is identical to the one in the Connections picker.
    if term != derive_target_term(run_date):
        marker = "CAST(NULL AS varchar(6)) AS target_term_override"
        if sql.count(marker) != 1:
            raise RefundExtractError("Could not set the target term in Refunds.sql.")
        sql = sql.replace(marker, f"CAST('{term}' AS varchar(6)) AS target_term_override")
    if cancellation:
        cancellation.check()
    try:
        with report_log_context(query.title):
            result = client.run_sql(sql)
    except InsightsAPIError as error:
        raise RefundExtractError(f"Standalone Refund Review SQL failed. {error}") from error
    if cancellation:
        cancellation.check()
    if result.attrs.get("rows_truncated"):
        raise RefundExtractError("Insights marked the standalone refund result as truncated. "
                                 "Use the batched extracts for a complete review.")

    report = normalize_refund_columns(result)
    required = set(REPORT_COLUMNS) - THIRD_PARTY_COLUMNS
    if not report.columns.is_unique or not required.issubset(report.columns):
        raise RefundExtractError("The standalone query did not return the expected Refund Review columns.")
    if not report["parent_plus_target_term"].map(str).eq(term).all():
        raise RefundExtractError("The target term returned by Refunds.sql differs from the selected term.")

    report = report.astype(object).where(report.notna(), None)
    for column in report.columns:
        if column in CURRENCY_COLUMNS or column in COUNT_COLUMNS:
            convert = _excel_number
        elif column.endswith("_date"):
            convert = _excel_date
        else:
            continue
        try:
            report[column] = pd.Series([convert(value) for value in report[column]],
                                       index=report.index, dtype=object)
        except (InvalidOperation, TypeError, ValueError, OverflowError):
            raise RefundExtractError(f"Refunds.sql returned an unreadable value for {column}.") from None
    if any(value is None or value <= 0 for value in report["total_refund_amount"]):
        raise RefundExtractError("Refunds.sql returned an invalid account refund total.")
    # Missing sponsor and contract fields are unknown. Preserve nulls rather
    # than fabricating zero totals or clearing a third-party review flag.
    return report.reindex(columns=REPORT_COLUMNS, fill_value=None)
