"""Synthetic validation and completeness checks; no live Banner or credentials."""

from datetime import date, datetime
from pathlib import Path
import unittest
from unittest.mock import MagicMock

import pandas as pd

from shared.insights.banner_activity import BannerActivityParameters, extract_banner_activity
from shared.insights.client import InsightsAPIError


TEMPLATE = (Path(__file__).resolve().parents[2] / "query/AR/activity/tgiaccd_transactions.sql").read_text()
COUNT = "__activity_row_count"


class BannerActivityParameterTests(unittest.TestCase):
    def test_normalizes_codes_and_renders_actual_template(self):
        params = BannerActivityParameters.from_inputs("2024-02-29", "2026-12-31", " tpdt, TDLE,z0le, TPDT ")
        self.assertEqual(params.detail_codes, ("TPDT", "TDLE", "Z0LE"))
        sql = params.render_sql(TEMPLATE)
        self.assertNotIn("{{", sql)
        self.assertIn("CAST('2024-02-29' AS date)", sql)
        self.assertIn("CAST('2026-12-31' AS date) + INTERVAL '1 day'", sql)
        self.assertIn("t.tbraccd_detail_code IN ('TPDT', 'TDLE', 'Z0LE')", sql)

    def test_accepts_other_detail_codes_and_single_day(self):
        params = BannerActivityParameters.from_inputs("2026-01-01", "2026-01-01", "HLTH")
        self.assertEqual(params.detail_codes, ("HLTH",))
        self.assertNotIn("'TPDT'", params.render_sql(TEMPLATE))

    def test_rejects_bad_dates_reversed_ranges_and_sql_injection(self):
        cases = [
            (None, "2026-01-01", "TPDT"),
            ("20260101", "2026-01-01", "TPDT"),
            ("2025-02-29", "2026-01-01", "TPDT"),
            ("2026-01-02", "2026-01-01", "TPDT"),
            ("2026-01-01", "9999-12-31", "TPDT"),
            ("2026-01-01'; SELECT 1; --", "2026-01-01", "TPDT"),
            ("2026-01-01", "2026-01-01", "TPDT'); DELETE FROM x; --"),
            ("2026-01-01", "2026-01-01", ""),
            ("2026-01-01", "2026-01-01", "TPDT,"),
            ("2026-01-01", "2026-01-01", ["TPDT"]),
        ]
        for args in cases:
            with self.subTest(args=args), self.assertRaises(ValueError):
                BannerActivityParameters.from_inputs(*args)

    def test_direct_constructor_rejects_unvalidated_values(self):
        for codes in (("tpdt",), ("TPDT'",), (), ["TPDT"]):
            with self.subTest(codes=codes), self.assertRaises(ValueError):
                BannerActivityParameters(date(2026, 1, 1), date(2026, 1, 1), codes)
        with self.assertRaises(ValueError):
            BannerActivityParameters(datetime(2026, 1, 1), date(2026, 1, 1), ("TPDT",))

    def test_rejects_changed_templates_with_unknown_or_missing_tags(self):
        params = BannerActivityParameters.from_inputs("2026-01-01", "2026-01-01", "TPDT")
        for sql in (TEMPLATE.replace("{{start_date}}", "CURRENT_DATE"), TEMPLATE + " {{unknown}}"):
            with self.subTest(sql=sql[-30:]), self.assertRaises(ValueError):
                params.render_sql(sql)


class BannerActivityExtractionTests(unittest.TestCase):
    def setUp(self):
        self.client = MagicMock()
        self.parameters = BannerActivityParameters.from_inputs("2026-01-01", "2026-01-04", "TPDT")

    def extract(self):
        return extract_banner_activity(self.client, self.parameters, sql_template=TEMPLATE)

    def test_splits_capped_range_into_non_overlapping_complete_windows(self):
        # The first two records are legitimately identical: never deduplicate.
        self.client.run_sql.side_effect = [
            pd.DataFrame({"Amount": [10, 10], COUNT: [4, 4]}),
            pd.DataFrame({"Amount": [10, 10], COUNT: [2, 2]}),
            pd.DataFrame({"Amount": [-5, 0], COUNT: [2, 2]}),
        ]
        result = self.extract()
        self.assertEqual(result["Amount"].tolist(), [10, 10, -5, 0])
        self.assertNotIn(COUNT, result.columns)
        calls = [call.args[0] for call in self.client.run_sql.call_args_list]
        self.assertIn("CAST('2026-01-02' AS date) + INTERVAL '1 day'", calls[1])
        self.assertIn("CAST('2026-01-03' AS date)", calls[2])
        self.assertIn("COUNT(*) OVER ()", calls[0])

    def test_complete_and_empty_results_keep_export_columns(self):
        for data in (
            pd.DataFrame({"Amount": [0], COUNT: ["1"]}),
            pd.DataFrame(columns=["Amount", COUNT]),
        ):
            with self.subTest(rows=len(data)):
                self.client.run_sql.return_value = data
                result = self.extract()
                self.assertEqual(list(result.columns), ["Amount"])
                self.assertEqual(len(result), len(data))

    def test_single_day_cap_fails_and_api_errors_propagate(self):
        self.parameters = BannerActivityParameters.from_inputs("2026-01-01", "2026-01-01", "TPDT")
        self.client.run_sql.return_value = pd.DataFrame({"Amount": [10], COUNT: [3]})
        with self.assertRaisesRegex(InsightsAPIError, "Select fewer detail codes"):
            self.extract()
        self.client.run_sql.side_effect = InsightsAPIError("HTTP 403")
        with self.assertRaisesRegex(InsightsAPIError, "403"):
            self.extract()

    def test_missing_or_inconsistent_counts_fail_closed(self):
        for data in (
            pd.DataFrame({"Amount": [1]}),
            pd.DataFrame({"Amount": [1, 2], COUNT: [2, 3]}),
            pd.DataFrame({"Amount": [1], COUNT: [0]}),
            pd.DataFrame({"Amount": [1], COUNT: [None]}),
            pd.DataFrame({"Amount": [1], COUNT: [1.5]}),
        ):
            with self.subTest(data=data.to_dict()), self.assertRaises(InsightsAPIError):
                self.client.run_sql.return_value = data
                self.extract()


if __name__ == "__main__":
    unittest.main()
