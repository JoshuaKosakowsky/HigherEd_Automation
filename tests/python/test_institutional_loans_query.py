"""Execute the delivered SQL against synthetic data; no Banner credentials."""
from __future__ import annotations

import re
import sqlite3
import tempfile
import unittest
from datetime import date, timedelta
from pathlib import Path
from unittest.mock import MagicMock, patch

import pandas as pd
from openpyxl import load_workbook

from app.gui.models import WorkflowContext, WorkflowMode
from app.gui.services.insights import run_insights_connection
from shared.insights.query_catalog import QUERIES, get_query

REPORT_DATE = date(2026, 10, 18)
QUERY = get_query("loan_all_enrollment")


class InstitutionalLoansQueryTests(unittest.TestCase):
    def setUp(self):
        self.db = sqlite3.connect(":memory:")
        self.addCleanup(self.db.close)
        self.db.row_factory = sqlite3.Row
        self.db.create_function("BTRIM", 1, lambda v: None if v is None else v.strip())
        self.db.create_function("CONCAT", -1, lambda *v: "".join(str(x) for x in v if x is not None))
        self.db.create_function("CONCAT_WS", -1, lambda sep, *v: sep.join(str(x) for x in v if x is not None))
        for schema in ("saturn", "taismgr", "general"):
            self.db.execute(f"ATTACH DATABASE ':memory:' AS {schema}")
        schemas = {
            "saturn.sfrstcr": "pidm INTEGER, term_code TEXT, rsts_code TEXT, credit_hr NUMERIC, bill_hr NUMERIC",
            "saturn.stvrsts": "code TEXT, incl_sect_enrl TEXT",
            "taismgr.tbraccd": "pidm INTEGER, term_code TEXT, detail_code TEXT, amount NUMERIC, activity_date TEXT",
            "saturn.sgbstdn": "pidm INTEGER, term_code_eff TEXT, levl_code TEXT, styp_code TEXT, exp_grad_date TEXT",
            "saturn.shrlgpa": "pidm INTEGER, levl_code TEXT, gpa_type_ind TEXT, hours_earned NUMERIC",
            "saturn.spriden": "pidm INTEGER, id TEXT, last_name TEXT, first_name TEXT, change_ind TEXT",
            "saturn.stvstyp": "code TEXT, desc TEXT",
            "taismgr.tbbdetc": "detail_code TEXT, desc TEXT, type_ind TEXT",
            "saturn.spraddr": "pidm INTEGER, atyp_code TEXT, seqno INTEGER, street_line1 TEXT, street_line2 TEXT, street_line3 TEXT, city TEXT, stat_code TEXT, zip TEXT, status_ind TEXT, from_date TEXT, to_date TEXT",
            "general.goremal": "pidm INTEGER, emal_code TEXT, email_address TEXT, status_ind TEXT, preferred_ind TEXT, activity_date TEXT",
            "saturn.sprtele": "pidm INTEGER, seqno INTEGER, phone_area TEXT, phone_number TEXT, phone_ext TEXT, primary_ind TEXT, status_ind TEXT",
            "saturn.shrdgmr": "pidm INTEGER, seq_no INTEGER, grad_date TEXT, degc_code TEXT, levl_code TEXT, degs_code TEXT",
            "saturn.stvdegs": "code TEXT, desc TEXT, award_status_ind TEXT",
            "saturn.sfbetrm": "pidm INTEGER, term_code TEXT, ests_code TEXT, ests_date TEXT",
            "saturn.stvests": "code TEXT, desc TEXT, third_party_wd_ind TEXT",
            "saturn.sfrwdrl": "pidm INTEGER, term_code TEXT, seq_no INTEGER, ests_code TEXT, eff_wdrl_date TEXT",
            "saturn.stvterm": "code TEXT, start_date TEXT, end_date TEXT",
        }
        for table, columns in schemas.items():
            name = table.split(".")[1]
            definitions = ", ".join(f"{name}_{column}" for column in columns.split(", "))
            self.db.execute(f"CREATE TABLE {table} ({definitions})")
        self.insert("saturn.stvrsts", "RE", "Y")
        self.insert("saturn.stvrsts", "WD", "N")
        self.insert("saturn.stvdegs", "ZZ", "Synthetic Awarded", "A")
        self.insert("saturn.stvdegs", "AW", "Synthetic Pending", "P")
        self.insert("saturn.stvests", "ZZ", "Synthetic Withdrawal", "Y")
        self.insert("saturn.stvests", "EL", "Eligible", "N")
        self.insert("saturn.stvstyp", "C", "Continuing")
        self.insert("saturn.stvstyp", "X", "Returning Student")
        for code in ("PERK", "CFDN", "CPAR", "CCOM", "CWLC", "L001", "LEWL", "CLTL"):
            self.insert("taismgr.tbbdetc", code, f"Synthetic {code}", "P")
        for term, start, end in (
            ("202480", "2024-08-15", "2024-12-20"),
            ("202580", "2025-08-15", "2025-12-20"),
            ("202610", "2026-01-10", "2026-05-15"),
            ("202655", "2026-05-20", "2026-08-01"),
            ("202680", "2026-08-15", "2026-12-20"),
            ("202710", "2027-01-10", "2027-05-15"),
        ):
            self.insert("saturn.stvterm", term, start, end)

    def insert(self, table, *values):
        self.db.execute(f"INSERT INTO {table} VALUES ({', '.join('?' for _ in values)})", values)

    def day(self, days_ago):
        return (REPORT_DATE - timedelta(days=days_ago)).isoformat()

    def borrower(self, pidm=1, level="UG", code="LEWL", amount=100):
        self.insert("saturn.spriden", pidm, f"TEST-{pidm}", "Synthetic", f"Person{pidm}", None)
        self.insert("saturn.sgbstdn", pidm, "202210", level, "C", self.day(20))
        self.loan(pidm, code, amount)

    def loan(self, pidm, code="LEWL", amount=100, term="202210"):
        self.insert("taismgr.tbraccd", pidm, term, code, amount, "2022-01-01")

    def graduate(self, pidm=1, days=30, status="ZZ", seq=1, level="UG"):
        self.insert("saturn.shrdgmr", pidm, seq, self.day(days), "BS", level, status)

    def register(self, pidm=1, term="202680", hours=6, status="RE", bill=None):
        self.insert("saturn.sfrstcr", pidm, term, status, hours, hours if bill is None else bill)

    def withdraw(self, pidm=1, days=20, term="202655", effective=True, status="ZZ", seq=1):
        self.insert("saturn.sfbetrm", pidm, term, status, self.day(days + 5 if effective else days))
        if effective:
            self.insert("saturn.sfrwdrl", pidm, term, seq, status, self.day(days))

    def rows(self, term="202680"):
        sql = QUERY.render_sql(term)
        # Execute every CTE/join/window/filter unchanged. Adapt only PostgreSQL
        # casts/date syntax and freeze CURRENT_DATE for deterministic boundaries.
        sql = re.sub(r"::varchar\(\d+\)", "", sql)
        sql = sql.replace("CURRENT_DATE - INTERVAL '365 days'", "date(CURRENT_DATE, '-365 days')")
        sql = re.sub(r"CAST\((COALESCE\([^()]+\)|[a-z_]+\.[a-z_]+) AS date\)", r"date(\1)", sql)
        sql = sql.replace("CURRENT_DATE", f"'{REPORT_DATE.isoformat()}'")
        return [dict(row) for row in self.db.execute(sql)]

    def test_old_loans_all_seven_codes_and_reversals_are_retained(self):
        for pidm, code in enumerate(("PERK", "CFDN", "CPAR", "CCOM", "CWLC", "L001", "LEWL", "CLTL"), 1):
            self.borrower(pidm, code=code)
            self.graduate(pidm)
        self.loan(7, amount=-100)
        self.loan(6, code="L001", amount=-150)
        rows = self.rows()
        self.assertEqual(len(rows), 7)
        amounts = {r["Detail Code"]: r["Detail Code Loan Activity"] for r in rows}
        self.assertEqual(amounts["LEWL"], 0)
        self.assertEqual(amounts["L001"], -50)
        self.assertNotIn("CLTL", amounts)
        self.assertTrue(all(r["Credit Hours"] == 0 for r in rows))
        self.assertTrue(all(r["__loan_row_count"] == 7 for r in rows))

    def test_awarded_indicator_and_calendar_day_window(self):
        for pidm, days, status in ((1, 0, "ZZ"), (2, 365, "ZZ"), (3, 366, "ZZ"),
                                  (4, -1, "ZZ"), (5, 10, "AW")):
            self.borrower(pidm)
            self.graduate(pidm, days, status)
        self.assertEqual({r["ID"] for r in self.rows()}, {"TEST-1", "TEST-2"})
        # A stale/expected graduation date alone never qualifies a borrower.
        self.borrower(6)
        self.assertEqual(len(self.rows()), 2)

    def test_multiple_awards_contacts_and_codes_do_not_multiply(self):
        self.borrower()
        self.graduate(seq=1)
        self.graduate(days=10, seq=2, level="GR")
        self.graduate(days=10, seq=3, level="UG")
        self.loan(1, "PERK", 50)
        self.insert("saturn.spraddr", 1, "PR", 1, "1 Permanent Rd", None, None, "Golden", "CO", "80401", None, "2020-01-01", None)
        self.insert("saturn.spraddr", 1, "MA", 2, "2 Mailing St", "Apt 3", None, "Denver", "CO", "80202", None, "2020-01-01", None)
        self.insert("general.goremal", 1, "UNIV", "old@example.edu", "A", "N", "2020-01-01")
        self.insert("general.goremal", 1, "UNIV", "preferred@example.edu", "A", "Y", "2020-01-01")
        self.insert("saturn.sprtele", 1, 1, "303", "5550101", None, "Y", None)
        self.insert("saturn.sprtele", 1, 2, "720", "5550102", None, "N", None)
        self.insert("saturn.spriden", 1, "OLD-ID", "Old", "Identity", "N")
        rows = self.rows()
        self.assertEqual(len(rows), 2)
        self.assertEqual({r["Graduation Date"] for r in rows}, {self.day(10)})
        self.assertEqual({r["Graduated Level"] for r in rows}, {"UG"})
        self.assertEqual(rows[0]["Street"], "2 Mailing St, Apt 3")
        self.assertEqual(rows[0]["School Email"], "preferred@example.edu")
        self.assertEqual(rows[0]["Phone Number"], "(303) 5550101")

    def test_enrollment_boundaries_for_every_term_and_level(self):
        cases = (("UG", 0, "Less Than Half Time"), ("UG", 5.5, "Less Than Half Time"),
                 ("UG", 6, "Half Time but Less Than Full Time"), ("UG", 11.5, "Half Time but Less Than Full Time"),
                 ("UG", 12, "Full Time and Above"), ("GR", 4, "Less Than Half Time"),
                 ("GR", 4.5, "Half Time but Less Than Full Time"), ("GR", 4.6, "Half Time but Less Than Full Time"),
                 ("GR", 8.5, "Half Time but Less Than Full Time"), ("GR", 9, "Full Time and Above"))
        for pidm, (level, hours, category) in enumerate(cases, 1):
            self.borrower(pidm, level)
            self.graduate(pidm)
            for term in ("202610", "202655", "202680"):
                self.register(pidm, term, hours)
        for term in ("202610", "202655", "202680"):
            rows = {r["ID"]: r for r in self.rows(term)}
            for pidm, (_, hours, category) in enumerate(cases, 1):
                with self.subTest(term=term, pidm=pidm):
                    self.assertEqual(rows[f"TEST-{pidm}"]["Enrollment Load Category"], category)
                    self.assertEqual(rows[f"TEST-{pidm}"]["Credit Hours"], hours)

    def test_graduate_continuing_in_new_program_uses_term_effective_level(self):
        self.borrower()
        self.graduate(level="UG")
        self.insert("saturn.sgbstdn", 1, "202680", "GR", "X", None)
        self.insert("saturn.sgbstdn", 1, "202710", "UG", "C", None)
        self.register(hours=4.5)
        row = self.rows()[0]
        self.assertEqual(row["Level"], "GR")
        self.assertEqual(row["Graduated Level"], "UG")
        self.assertEqual(row["Enrollment Load Category"], "Half Time but Less Than Full Time")
        self.assertEqual(row["Returning Student Type Check"], "Yes - X (Returning Student)")

    def test_withdrawals_prefer_effective_date_and_fall_back_to_header(self):
        self.borrower(1)
        self.withdraw(1, days=365)
        self.borrower(2)
        self.withdraw(2, days=20, effective=False)
        rows = {r["ID"]: r for r in self.rows("202655")}
        self.assertEqual(rows["TEST-1"]["Withdrawal Date"], self.day(365))
        self.assertEqual(rows["TEST-1"]["Withdrawal Date Source"], "SFAWDRL effective date")
        self.assertEqual(rows["TEST-2"]["Withdrawal Date Source"], "SFAREGS enrollment status date")
        self.assertTrue(all(r["Selection Reason"] == "Recorded Withdrawal" for r in rows.values()))

    def test_old_future_retracted_and_future_term_withdrawals_do_not_qualify(self):
        for pidm in range(1, 5):
            self.borrower(pidm)
        self.withdraw(1, days=366)
        self.withdraw(2, days=-1)
        self.withdraw(3, days=10)
        self.db.execute("UPDATE saturn.sfbetrm SET sfbetrm_ests_code = 'EL' WHERE sfbetrm_pidm = 3")
        self.withdraw(4, days=10, term="202710")
        self.assertEqual(self.rows(), [])

    def test_latest_withdrawal_record_is_selected_without_fanout(self):
        self.borrower()
        self.withdraw(days=30)
        self.insert("saturn.sfrwdrl", 1, "202655", 2, "ZZ", self.day(10))
        self.withdraw(days=5, term="202680")
        rows = self.rows()
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["Withdrawal Date"], self.day(5))

    def test_stop_out_in_regular_term_but_never_summer_or_future_term(self):
        self.borrower()
        self.register(term="202610", hours=6)
        rows = self.rows()
        self.assertEqual(rows[0]["Selection Reason"], "Possible Stop-Out - Review")
        self.assertEqual(rows[0]["Last Enrolled Term End - Proxy"], "2026-05-15")
        self.assertEqual(self.rows("202655"), [])
        self.assertEqual(self.rows("202710"), [])

    def test_summer_attendance_can_precede_a_fall_stop_out(self):
        self.borrower()
        self.register(term="202655", hours=3)
        row = self.rows()[0]
        self.assertEqual(row["Last Enrolled Term"], "202655")
        self.assertEqual(row["Selection Reason"], "Possible Stop-Out - Review")

    def test_stop_out_proxy_window_and_missing_dates(self):
        for pidm, days in ((1, 365), (2, 366), (3, -1), (4, None)):
            self.borrower(pidm)
            term = f"2026{pidm:02}"
            self.register(pidm, term, hours=3)
            self.insert("saturn.stvterm", term, "2026-01-01", None if days is None else self.day(days))
        self.assertEqual([r["ID"] for r in self.rows()], ["TEST-1"])
        self.db.execute("DELETE FROM saturn.stvterm WHERE stvterm_code = '202680'")
        self.assertEqual(self.rows(), [])

    def test_active_or_unknown_registration_never_establishes_absence(self):
        for pidm, hours, status in ((1, 0, "RE"), (2, None, "RE"), (3, 3, "UNKNOWN")):
            self.borrower(pidm)
            self.register(pidm, "202610", 6)
            self.register(pidm, hours=hours, status=status)
        self.assertEqual(self.rows(), [])
        self.graduate(2)
        self.graduate(3)
        self.assertTrue(all(r["Enrollment Load Category"] == "Needs Review" for r in self.rows()))

    def test_dropped_courses_remain_billable_but_not_enrolled(self):
        self.borrower()
        self.graduate()
        self.register(hours=3, status="WD", bill=3)
        row = self.rows()[0]
        self.assertEqual(row["Credit Hours"], 0)
        self.assertEqual(row["Billable Hours"], 3)

    def test_metadata_gaps_are_retained_and_flagged(self):
        self.borrower()
        self.graduate()
        self.db.execute("DELETE FROM saturn.spriden")
        self.db.execute("DELETE FROM saturn.sgbstdn")
        self.db.execute("DELETE FROM taismgr.tbbdetc")
        row = self.rows()[0]
        self.assertIsNone(row["ID"])
        self.assertEqual(row["Banner PIDM"], 1)
        self.assertEqual(row["Enrollment Load Category"], "Needs Review")
        self.assertIn("Missing current identity", row["Review Notes"])
        self.assertIn("Missing term-effective student record", row["Review Notes"])
        self.assertIn("Missing detail-code metadata", row["Review Notes"])

    def test_multiple_qualifying_reasons_still_produce_one_code_row(self):
        self.borrower()
        self.graduate()
        self.withdraw()
        self.register(term="202610", hours=6)
        rows = self.rows()
        self.assertEqual(len(rows), 1)
        for reason in ("Recent Graduate", "Recorded Withdrawal", "Possible Stop-Out - Review"):
            self.assertIn(reason, rows[0]["Selection Reason"])

    def test_earned_credits_remain_overall_only(self):
        self.borrower()
        self.graduate()
        for level, kind, hours in (("UG", "I", 15), ("UG", "T", 5), ("UG", "O", 20), ("GR", "O", 2)):
            self.insert("saturn.shrlgpa", 1, level, kind, hours)
        self.assertEqual(self.rows()[0]["Total Earned Credit Hours"], 22)

    def test_one_catalog_entry_validates_terms_and_uses_one_source(self):
        self.assertEqual([q.query_id for q in QUERIES if q.group == "Institutional loans"], ["loan_all_enrollment"])
        for term in ("202610", "202655", "202680"):
            self.assertNotIn("{{", QUERY.render_sql(term))
        for term in (None, "202699", "2026800", "2026ab", "202680'; SELECT 1; --"):
            with self.subTest(term=term), self.assertRaises(ValueError):
                QUERY.render_sql(term)

    def test_schema_inventory_covers_every_synthetic_source_column(self):
        schema = QUERY.sql_path.with_name("validate_loan_schema.sql").read_text(encoding="utf-8")
        expected = set(re.findall(r"\('([A-Z]+)', '([A-Z]+)', '([A-Z_0-9]+)'\)", schema))
        for database in ("saturn", "taismgr", "general"):
            for row in self.db.execute(f"SELECT name FROM {database}.sqlite_master WHERE type = 'table'"):
                table = row[0]
                for column in self.db.execute(f"PRAGMA {database}.table_info({table})"):
                    suffix = column[1][len(table) + 1:]
                    self.assertIn((database.upper(), table.upper(), suffix.upper()), expected)

    def test_app_export_checks_completeness_and_preserves_ids_and_zero_amount(self):
        self.borrower()
        self.graduate()
        self.loan(1, amount=-100)
        frame = pd.DataFrame(self.rows())
        settings = MagicMock()
        client = MagicMock()
        client.__enter__.return_value = client
        client.run_sql.return_value = frame
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "loans.xlsx"
            context = WorkflowContext("insights_query_export", {
                "action": "query_export", "query_id": "loan_all_enrollment",
                "term_code": "202680", "output_path": str(output)}, WorkflowMode.TEST)
            with patch("app.gui.services.insights.load_department_profiles", return_value={"TEST": settings}), patch(
                "app.gui.services.insights.build_authenticated_client", return_value=(client, "synthetic")):
                result = run_insights_connection(context)
                self.assertTrue(result.success, result.message)
                workbook = load_workbook(output)
                try:
                    values = list(workbook.active.values)
                    headings = values[0]
                    self.assertNotIn("__loan_row_count", headings)
                    self.assertEqual(values[1][headings.index("ID")], "TEST-1")
                    self.assertEqual(values[1][headings.index("Detail Code Loan Activity")], 0)
                finally:
                    workbook.close()
                output.unlink()
                capped = frame.copy()
                capped["__loan_row_count"] = 2
                for bad in (capped, frame.drop(columns=["__loan_row_count"])):
                    client.run_sql.return_value = bad
                    result = run_insights_connection(context)
                    self.assertFalse(result.success)
                    self.assertFalse(output.exists())
                client.run_sql.return_value = frame.iloc[0:0]
                result = run_insights_connection(context)
                self.assertTrue(result.success, result.message)
                self.assertTrue(output.exists())


if __name__ == "__main__":
    unittest.main()
