from __future__ import annotations

import re
import sqlite3
import unittest
from pathlib import Path


QUERY_ROOT = Path(__file__).resolve().parents[2] / "query" / "AR" / "activity"


class TgiaccdQueryTests(unittest.TestCase):
    """Execute source selection with synthetic data; adapt date syntax/tags."""

    def setUp(self) -> None:
        self.db = sqlite3.connect(":memory:")
        self.addCleanup(self.db.close)
        self.db.executescript("""
            ATTACH DATABASE ':memory:' AS taismgr;
            ATTACH DATABASE ':memory:' AS saturn;
            CREATE TABLE taismgr.tbraccd (
                tbraccd_pidm INTEGER, tbraccd_detail_code TEXT,
                tbraccd_desc TEXT, tbraccd_amount NUMERIC,
                tbraccd_balance NUMERIC, tbraccd_term_code TEXT,
                tbraccd_aidy_code TEXT, tbraccd_tran_number INTEGER,
                tbraccd_feed_doc_code TEXT,
                tbraccd_feed_date TEXT, tbraccd_effective_date TEXT,
                tbraccd_activity_date TEXT, tbraccd_user TEXT
            );
            CREATE TABLE saturn.spriden (
                spriden_pidm INTEGER, spriden_id TEXT,
                spriden_last_name TEXT, spriden_first_name TEXT,
                spriden_change_ind TEXT
            );
            CREATE TABLE taismgr.tbbdetc (
                tbbdetc_detail_code TEXT, tbbdetc_desc TEXT,
                tbbdetc_type_ind TEXT
            );
            INSERT INTO saturn.spriden VALUES
                (1, 'TPS-TEST', 'Synthetic Sponsor', NULL, NULL),
                (1, 'OLD-TEST', 'Historical Name', NULL, 'I');
            INSERT INTO taismgr.tbbdetc VALUES
                ('TPDT', 'Detail metadata', 'P'),
                ('TDLE', 'Living expenses', 'P'),
                ('Z0LE', 'Fellowship', 'P');
        """)
        self.query = (QUERY_ROOT / "tgiaccd_transactions.sql").read_text()

    def add_transaction(
        self, number: int, feed_date: str | None, code: str = "TPDT",
        amount: float | None = 10, pidm: int = 1,
    ) -> None:
        self.db.execute(
            "INSERT INTO taismgr.tbraccd VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (pidm, code, "Synthetic student reference RA", amount, 0, "209910",
             None, number, "TEST-FEED", feed_date, "2099-01-01", "2099-01-01",
             "SYNTHETIC_USER"),
        )

    def results(
        self, start: str, end: str, codes: tuple[str, ...] = ("TPDT", "TDLE", "Z0LE"),
    ) -> tuple[list[str], list[tuple]]:
        # Metabase supplies the field-filter predicate. Bind synthetic selections
        # here; these tests do not emulate or validate its UI/template engine.
        query = re.sub(r"/\*.*?\*/", "", self.query, flags=re.DOTALL)
        query = query.replace(
            "CAST({{end_date}} AS date) + INTERVAL '1 day'",
            "datetime(:end, '+1 day')",
        ).replace("CAST({{start_date}} AS date)", "date(:start)").replace(
            "CAST({{end_date}} AS date)", "date(:end)"
        )
        placeholders = ", ".join(f":code_{index}" for index in range(len(codes)))
        query = query.replace("{{detail_codes}}", f"t.tbraccd_detail_code IN ({placeholders})")
        params = {"start": start, "end": end}
        params.update({f"code_{index}": code for index, code in enumerate(codes)})
        cursor = self.db.execute(query, params)
        return [item[0] for item in cursor.description], cursor.fetchall()

    def test_inclusive_end_date_and_timestamp_boundaries(self) -> None:
        for number, feed_date in enumerate([
            "2099-01-31 23:59:59", "2099-02-01 00:00:00",
            "2099-02-28 23:59:59.999", "2099-03-01 00:00:00",
        ], 1):
            self.add_transaction(number, feed_date)
        _, rows = self.results("2099-02-01", "2099-02-28")
        self.assertEqual([row[9] for row in rows], [
            "2099-02-01 00:00:00", "2099-02-28 23:59:59.999",
        ])

    def test_app_extract_matches_manual_selection_with_api_cap(self) -> None:
        import pandas as pd
        from shared.insights.banner_activity import BannerActivityParameters, extract_banner_activity

        for number, day, code, amount in (
            (1, "2103-12-31 23:59:59", "TPDT", 100),
            (2, "2104-02-28 00:00:00", "TPDT", 10),
            (3, "2104-02-28 23:59:59", "TDLE", -5),
            (4, "2104-02-29 12:00:00", "Z0LE", 0),
            (5, "2104-02-29 12:00:00", "Z0LE", 0),
            (6, "2104-03-31 23:59:59.999", "TPDT", 20),
            (7, "2104-03-31 12:00:00", "HLTH", 50),
            (8, "2104-04-01 00:00:00", "TPDT", 100),
        ):
            self.add_transaction(number, day, code, amount)
        db = self.db

        class CappedExecutor:
            calls = 0

            def run_sql(self, sql):
                self.calls += 1
                # Adapt PostgreSQL date syntax only, after real app rendering.
                sql = re.sub(
                    r"CAST\('([0-9-]+)' AS date\) \+ INTERVAL '1 day'",
                    r"datetime('\1', '+1 day')", sql,
                )
                sql = re.sub(r"CAST\('([0-9-]+)' AS date\)", r"date('\1')", sql)
                return pd.read_sql_query(sql, db).iloc[:2]

        params = BannerActivityParameters.from_inputs("2104-01-01", "2104-03-31", "TPDT, TDLE, Z0LE")
        executor = CappedExecutor()
        actual = extract_banner_activity(executor, params, sql_template=self.query)
        columns, rows = self.results("2104-01-01", "2104-03-31")
        self.assertEqual(list(actual.columns), columns)
        self.assertEqual(list(actual.itertuples(index=False, name=None)), rows)
        self.assertEqual(actual["'Amount'"].sum(), 25)
        self.assertGreater(executor.calls, 1)

    def test_single_day_leap_year_and_multi_year_ranges(self) -> None:
        for number, day in enumerate([
            "2099-12-31 23:00:00", "2100-01-01 00:00:00",
            "2104-02-29 23:59:59", "2105-01-01 00:00:00",
        ], 1):
            self.add_transaction(number, day)
        _, rows = self.results("2104-02-29", "2104-02-29")
        self.assertEqual([row[9] for row in rows], ["2104-02-29 23:59:59"])
        _, rows = self.results("2099-12-31", "2104-12-31")
        self.assertEqual([row[9] for row in rows], [
            "2099-12-31 23:00:00", "2100-01-01 00:00:00", "2104-02-29 23:59:59",
        ])

    def test_multi_select_is_replaceable_and_preserves_signs(self) -> None:
        for number, code, amount in [(1, "TPDT", -12.34), (2, "TDLE", 0),
                                     (3, "Z0LE", 25), (4, "OTHER", 99)]:
            self.add_transaction(number, "2099-02-02", code, amount)
        _, rows = self.results("2099-02-01", "2099-02-28")
        self.assertEqual([row[4] for row in rows], [-12.34, 0, 25])
        _, rows = self.results("2099-02-01", "2099-02-28", ("OTHER",))
        self.assertEqual([row[2] for row in rows], ["OTHER"])

    def test_sponsor_transaction_description_and_missing_metadata_survive(self) -> None:
        self.add_transaction(1, "2099-02-02")
        self.add_transaction(2, "2099-02-02", "UNKNOWN", None, pidm=2)
        columns, rows = self.results("2099-02-01", "2099-02-28", ("TPDT", "UNKNOWN"))
        self.assertEqual(columns[3], "'Description'")
        self.assertEqual(rows[0][0], "TPS-TEST")
        self.assertEqual(rows[0][3], "Synthetic student reference RA")
        self.assertEqual(columns, [
            "'ID'", "'Name'", "'Detail Code'", "'Description'", "'Amount'",
            "'Balance'", "'Term'", "'Aid Year'", "'Feed Document'", "'Feed Date'",
            "detail_code_description", "Transaction User",
        ])
        self.assertEqual(rows[0][8], "TEST-FEED")
        self.assertEqual(rows[0][10], "Detail metadata")
        self.assertEqual(rows[0][-1], "SYNTHETIC_USER")
        self.assertIsNone(rows[1][0])
        self.assertIsNone(rows[1][4])
        self.assertIsNone(rows[1][10])
        self.assertEqual(len(rows), 2)  # Historical identity must not duplicate it.

    def test_reversed_dates_and_unfed_transactions_are_not_selected(self) -> None:
        self.add_transaction(1, "2099-02-02")
        self.add_transaction(2, None)
        self.assertEqual(self.results("2099-02-28", "2099-02-01")[1], [])
        self.assertEqual(len(self.results("2099-02-01", "2099-02-28")[1]), 1)

    def test_schema_inventory_covers_every_referenced_banner_column(self) -> None:
        inventory = (QUERY_ROOT / "validate_activity_schema.sql").read_text().upper()
        for table, suffix in re.findall(
            r"\b(tbraccd|tbbdetc|spriden)_([a-z_]+)\b", self.query.lower()
        ):
            schema = "SATURN" if table == "spriden" else "TAISMGR"
            self.assertIn(f"('{schema}', '{table.upper()}', '{suffix.upper()}')", inventory)


if __name__ == "__main__":
    unittest.main()
