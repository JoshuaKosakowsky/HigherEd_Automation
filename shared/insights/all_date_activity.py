"""Complete all-history transaction extraction under native API row caps."""
from __future__ import annotations

import math
import re
from numbers import Integral, Real

import pandas as pd

from shared.insights.banner_activity import BannerDetailCodeParameters, SQLExecutor
from shared.insights.client import InsightsAPIError
from shared.insights.report_results import InsightsReportResultError, checked_report_result


_COUNT = 'Report Row Count'
_KEYS = ('t.tbraccd_pidm', 't.tbraccd_tran_number')


def _integer(value: object) -> int:
    if not isinstance(value, bool):
        if isinstance(value, Integral):
            return int(value)
        if isinstance(value, Real) and math.isfinite(value) and value == int(value):
            return int(value)
        if isinstance(value, str) and re.fullmatch(r'[+-]?[0-9]{1,18}', value):
            return int(value)
    raise InsightsAPIError('Insights returned invalid source-key bounds.', code='invalid_response')


def extract_all_date_activity(
    executor: SQLExecutor, parameters: BannerDetailCodeParameters, *, sql_template: str,
) -> pd.DataFrame:
    """Split only proven capped results using disjoint integer source-key ranges.

    Never filter by feed date. Include NULL keys explicitly; preserve legitimate
    duplicate rows. Every leaf must pass the same completeness check, and each
    joined result must match its parent count. This is not a database snapshot.
    """
    predicate = parameters.render_sql('{{detail_codes}}')

    def fetch(
        prefix: tuple[str, ...] = (), axis: int = 0, bounds: tuple[int, int] | None = None,
    ) -> pd.DataFrame:
        conditions = list(prefix)
        if bounds is not None:
            conditions.append(f'{_KEYS[axis]} BETWEEN {bounds[0]} AND {bounds[1]}')
        template = sql_template.replace(
            '{{detail_codes}}', '({{detail_codes}})' + ''.join(f' AND ({part})' for part in conditions),
        )
        result = executor.run_sql(parameters.render_sql(template))
        try:
            return checked_report_result(result, _COUNT)
        except InsightsReportResultError as error:
            if error.reason != 'incomplete':
                raise
            expected = error.expected_rows
        if axis >= len(_KEYS):
            raise InsightsAPIError(
                'A single source-key group exceeds the API row limit. Use the full Insights export.',
                code='key_group_cap',
            )
        key = _KEYS[axis]
        parts = []
        if bounds is None:
            scope = predicate + ''.join(f' AND ({part})' for part in prefix)
            limits = executor.run_sql(
                f'SELECT MIN({key}) AS "__min_key", MAX({key}) AS "__max_key", '
                f'SUM(CASE WHEN {key} IS NULL THEN 1 ELSE 0 END) AS "__null_count" '
                f'FROM taismgr.tbraccd t WHERE {scope}'
            )
            if len(limits) != 1 or not {'__min_key', '__max_key', '__null_count'}.issubset(limits.columns):
                raise InsightsAPIError('Insights omitted source-key bounds.', code='invalid_response')
            low, high, nulls = (limits.iloc[0][column] for column in ('__min_key', '__max_key', '__null_count'))
            if not pd.isna(nulls) and _integer(nulls) > 0:
                parts.append(fetch((*prefix, f'{key} IS NULL'), axis + 1))
            if not pd.isna(low) and not pd.isna(high):
                bounds = (_integer(low), _integer(high))
            elif not (pd.isna(low) and pd.isna(high)):
                raise InsightsAPIError('Insights returned inconsistent source-key bounds.', code='invalid_response')
        if bounds is not None:
            low, high = bounds
            if low > high:
                raise InsightsAPIError('Insights returned reversed source-key bounds.', code='invalid_response')
            if low == high:
                parts.append(fetch((*prefix, f'{key} = {low}'), axis + 1))
            else:
                midpoint = low + (high - low) // 2
                parts.append(fetch(prefix, axis, (low, midpoint)))
                parts.append(fetch(prefix, axis, (midpoint + 1, high)))
        if not parts:
            raise InsightsAPIError('Source changed during extraction.', code='source_changed')
        complete = pd.concat(parts, ignore_index=True)
        if len(complete) != expected:
            raise InsightsAPIError('Source counts changed during extraction.', code='source_changed')
        return complete

    result = fetch()
    # Restore primary presentation order after disjoint source-key batches.
    sort_columns = [column for column in result.columns if isinstance(column, str)
                    and column.strip("'\"") in {'Feed Date', 'Feed Document'}]
    sort_columns.sort(key=lambda column: 0 if column.strip("'\"") == 'Feed Date' else 1)
    return (result.sort_values(sort_columns, kind='stable', na_position='last').reset_index(drop=True)
            if sort_columns else result.reset_index(drop=True))
