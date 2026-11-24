"""Exercise the shared nonpayment SQL and app export with synthetic Banner rows."""

import re
import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

import pandas as pd
from openpyxl import load_workbook

from app.gui.models import WorkflowContext, WorkflowMode
from app.gui.services.insights import run_insights_connection
from shared.insights.query_catalog import get_query


QUERY = get_query("prior_term_nonpayment")
SCHEMA = """
    CREATE TABLE saturn.sfrstcr (sfrstcr_pidm integer, sfrstcr_term_code text,
        sfrstcr_crn text, sfrstcr_rsts_code text);
    CREATE TABLE saturn.stvrsts (stvrsts_code text, stvrsts_incl_sect_enrl text);
    INSERT INTO saturn.stvrsts VALUES ('RE', 'Y'), ('RW', ' y '), ('WL', 'N'), ('DW', 'N');
    CREATE TABLE taismgr.tbraccd (tbraccd_pidm integer, tbraccd_term_code text,
        tbraccd_detail_code text, tbraccd_amount numeric, tbraccd_balance numeric);
    CREATE TABLE taismgr.tbbdetc (tbbdetc_detail_code text, tbbdetc_type_ind text);
    INSERT INTO taismgr.tbbdetc VALUES ('CHARGE', 'C'), ('PAYMENT', 'P'), ('DUP', 'C'), ('DUP', 'C');
    CREATE TABLE saturn.spriden (spriden_pidm integer, spriden_id text,
        spriden_first_name text, spriden_last_name text, spriden_change_ind text);
    CREATE TABLE saturn.sprhold (sprhold_pidm integer, sprhold_hldd_code text,
        sprhold_from_date timestamp, sprhold_to_date timestamp);
"""


class SortedCodes:
    def __init__(self):
        self.codes = set()

    def step(self, code):
        self.codes.add(code)

    def finalize(self):
        return ", ".join(sorted(self.codes))


class PriorTermNonpaymentTests(unittest.TestCase):
    def setUp(self):
        self.db = sqlite3.connect(":memory:")
        self.addCleanup(self.db.close)
        self.db.execute("ATTACH DATABASE ':memory:' AS saturn")
        self.db.execute("ATTACH DATABASE ':memory:' AS taismgr")
        self.db.executescript(SCHEMA)
        self.db.create_function("REGEXP", 2, lambda pattern, value: bool(re.search(pattern, value)))
        self.db.create_function("LPAD", 3, lambda value, size, fill: value.rjust(size, fill))
        self.db.create_function("GREATEST", 2, max)
        self.db.create_aggregate("SORTED_CODES", 1, SortedCodes)

    def register(self, pidm, term="209980", status="RE", section="10001", *, identity=True):
        self.db.execute("INSERT INTO saturn.sfrstcr VALUES (?, ?, ?, ?)", (pidm, term, section, status))
        if identity:
            self.db.execute("INSERT INTO saturn.spriden VALUES (?, ?, 'Synthetic', 'Student', NULL)",
                            (pidm, f"TEST-{pidm}"))

    def transaction(self, pidm, term, balance, code="CHARGE", amount=100):
        self.db.execute("INSERT INTO taismgr.tbraccd VALUES (?, ?, ?, ?, ?)",
                        (pidm, term, code, amount, balance))

    def run_sql(self, sql):
        # Adapt PostgreSQL functions and the clock while executing the report itself.
        sql = sql.replace("registration_term ~", "registration_term REGEXP")
        sql = sql.replace("CURRENT_DATE", "'2099-08-01'")
        sql = re.sub(r"CAST\((h\.sprhold_(?:from|to)_date) AS date\)", r"date(\1)", sql)
        sql = re.sub(r"STRING_AGG\(DISTINCT UPPER\(TRIM\(h\.sprhold_hldd_code\)\), ', '\s*"
                     r"ORDER BY UPPER\(TRIM\(h\.sprhold_hldd_code\)\)\)",
                     "SORTED_CODES(UPPER(TRIM(h.sprhold_hldd_code)))", sql)
        return pd.read_sql_query(sql, self.db)

    def report(self, term="209980"):
        frame = self.run_sql(QUERY.render_sql(term))
        self.assertEqual(frame["Report Row Count"].tolist(), [len(frame)] * len(frame))
        return frame

    def test_fall_balances_use_remaining_charges_and_active_registration(self):
        self.register(1)
        self.register(1, status="RW", section="10002", identity=False)
        self.register(1, status="DW", section="10003", identity=False)
        self.register(1, status="RE", section="10001", identity=False)
        self.transaction(1, "209910", 40)
        self.transaction(1, "209955", 30)
        self.transaction(1, "209955", -5, amount=-5)
        self.transaction(1, "209910", 0, "PAYMENT", 60)
        for term in ("209880", "209980", "210010"):
            self.transaction(1, term, 95)

        for pidm, status in ((2, "WL"), (3, "DW"), (4, "UNKNOWN")):
            self.register(pidm, status=status)
            self.transaction(pidm, "209955", 100)
        self.register(5)
        self.transaction(5, "209955", 0)
        self.transaction(5, "209980", 0, "PAYMENT")
        self.register(6)
        self.transaction(6, "209980", 200)

        report = self.report()
        self.assertEqual(report["CWID"].tolist(), ["TEST-1"])
        row = report.iloc[0]
        self.assertEqual(row["Registration Term"], "209980")
        self.assertEqual(row["Registered Sections"], 2)
        self.assertEqual(row["Prior Spring Balance"], 40)
        self.assertEqual(row["Prior Summer Balance"], 25)
        self.assertIsNone(row["Prior Fall Balance"])
        self.assertEqual(row["Prior Balance Owed"], 65)
        self.assertEqual(row["Unapplied Payment Found"], "No")

    def test_spring_crosses_calendar_year_and_checks_only_prior_fall(self):
        self.register(1, term="210010")
        self.transaction(1, "209980", 0.01)
        self.transaction(1, "209955", 75)
        self.transaction(1, "210010", 50)
        self.transaction(1, "210080", 60)
        self.register(2, term="210010")
        self.transaction(2, "209955", 10)
        self.assertEqual(self.report("210010")[["CWID", "Prior Fall Balance", "Prior Balance Owed"]]
                         .values.tolist(), [["TEST-1", 0.01, 0.01]])

    def test_holds_and_unapplied_credits_never_remove_a_candidate(self):
        for pidm in (1, 2):
            self.register(pidm)
            self.transaction(pidm, "209955", 100)
        self.transaction(1, "209980", -100, "PAYMENT")
        self.db.executemany("INSERT INTO saturn.sprhold VALUES (1, ?, ?, ?)", [
            ("PP", "2099-07-01", "2099-08-02"),
            (" pp ", "2099-07-01", "2099-08-02"),
            ("AU", "2099-08-01 15:00:00", "2099-08-02"),
            ("CO", None, "9999-12-31"),
            ("OLD", "2099-07-01", "2099-08-01 23:59:59"),
            ("FUTURE", "2099-08-02", "2099-12-31"),
            ("OPEN", "2099-07-01", None),
        ])
        report = self.report().set_index("CWID")
        self.assertEqual(report.loc["TEST-1", "Active Holds"], "AU, CO, PP")
        self.assertIsNone(report.loc["TEST-2", "Active Holds"])
        self.assertEqual(report["Prior Balance Owed"].tolist(), [100, 100])
        self.assertEqual(report.loc["TEST-1", "Prior Spring Balance"], 0)
        self.assertEqual(report.loc["TEST-1", "Unapplied Payment Found"], "Yes")
        self.assertIn("Verify unapplied payments", report.loc["TEST-1", "Review Notes"])

    def test_unknown_financial_data_and_current_identity_are_visible(self):
        self.register(1)
        self.db.execute("INSERT INTO saturn.spriden VALUES (1, 'Z-TEST', 'Extra', 'Identity', NULL)")
        self.register(2, identity=False)
        self.transaction(1, "209910", None)
        self.transaction(1, "209955", 25)
        self.transaction(2, "209955", 20, "DUP")
        self.transaction(2, "209910", 50, "UNKNOWN")
        report = self.report().set_index("CWID")
        self.assertEqual(report.index.tolist(), ["TEST-1", None])
        self.assertTrue(report["Prior Balance Owed"].isna().all())
        self.assertTrue(report["Prior Spring Balance"].isna().all())
        self.assertEqual(report.loc["TEST-1", "Prior Summer Balance"], 25)
        self.assertTrue(all("Incomplete prior-term balance" in note for note in report["Review Notes"]))
        self.assertTrue(all("Missing or duplicate current identity" in note for note in report["Review Notes"]))

    def test_bad_terms_in_native_question_and_app(self):
        self.register(1)
        self.transaction(1, "209955", 20)
        template = QUERY.sql_path.read_text(encoding="utf-8")
        for term in ("209955", "2099809", "20XX80", ""):
            with self.subTest(term=term):
                self.assertTrue(self.run_sql(template.replace("{{registration_term}}", f"'{term}'")).empty)
                with self.assertRaises(ValueError):
                    QUERY.render_sql(term)

    def test_app_runs_shared_sql_and_refuses_an_incomplete_export(self):
        self.register(1)
        self.transaction(1, "209955", 25)
        with tempfile.TemporaryDirectory() as directory, patch(
            "app.gui.services.insights.get_shared_gui_access_path",
            return_value=Path(directory) / "access.json",
        ), patch("app.gui.services.insights.load_access_configuration") as policy, patch(
            "app.gui.services.insights.build_authenticated_client"
        ) as build:
            policy.return_value.is_administrator.return_value = True
            client = MagicMock()
            client.__enter__.return_value = client
            build.return_value = (client, "cached session")
            client.run_sql.side_effect = self.run_sql
            output = Path(directory) / "nonpayment.xlsx"
            params = {"action": "query_export", "query_id": QUERY.query_id,
                      "term_code": "209980", "output_path": str(output)}
            result = run_insights_connection(WorkflowContext("insights_query_export", params, WorkflowMode.TEST))
            self.assertTrue(result.success, result.message)
            client.run_sql.assert_called_once_with(QUERY.render_sql("209980"))
            client.run_sql_file.assert_not_called()
            workbook = load_workbook(output, read_only=True)
            try:
                headings, values = list(workbook.active.values)
                self.assertNotIn("Report Row Count", headings)
                self.assertEqual(dict(zip(headings, values))["Prior Balance Owed"], 25)
            finally:
                workbook.close()

            client.run_sql.side_effect = None
            client.run_sql.return_value = self.report().assign(**{"Report Row Count": 2})
            params["output_path"] = str(Path(directory) / "capped.xlsx")
            result = run_insights_connection(WorkflowContext("insights_query_export", params, WorkflowMode.TEST))
            self.assertFalse(result.success)
            self.assertFalse(Path(params["output_path"]).exists())
