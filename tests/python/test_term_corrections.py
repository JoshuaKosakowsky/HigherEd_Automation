"""Run the actual report against synthetic accounts; no live Banner access."""
import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

import pandas as pd

from app.gui.models import WorkflowContext, WorkflowMode
from app.gui.services.insights import run_insights_connection
from shared.insights.query_catalog import get_query


class TermCorrectionQueryTests(unittest.TestCase):
    def setUp(self):
        self.db = sqlite3.connect(":memory:")
        self.addCleanup(self.db.close)
        self.db.executescript("""
            ATTACH DATABASE ':memory:' AS taismgr;
            ATTACH DATABASE ':memory:' AS saturn;
            CREATE TABLE taismgr.tbraccd (
                tbraccd_pidm INTEGER, tbraccd_term_code TEXT,
                tbraccd_tran_number INTEGER, tbraccd_detail_code TEXT,
                tbraccd_desc TEXT, tbraccd_amount NUMERIC,
                tbraccd_balance NUMERIC, tbraccd_feed_date TEXT,
                tbraccd_effective_date TEXT
            );
            CREATE TABLE taismgr.tbbdetc (
                tbbdetc_detail_code TEXT, tbbdetc_type_ind TEXT,
                tbbdetc_dcat_code TEXT, tbbdetc_desc TEXT
            );
            INSERT INTO taismgr.tbbdetc VALUES
                ('CASH', ' p ', ' csh ', 'Cash payment'),
                ('CHARGE', 'C', 'FEE', 'Charge'),
                ('AID', 'P', 'FA', 'Aid'),
                ('UNKNOWN', 'X', 'CSH', 'Unknown');
            CREATE TABLE saturn.spriden (
                spriden_pidm INTEGER, spriden_id TEXT,
                spriden_first_name TEXT, spriden_last_name TEXT,
                spriden_change_ind TEXT
            );
            CREATE TABLE saturn.sgbstdn (sgbstdn_pidm INTEGER);
        """)
        self.query = get_query("payments_without_charges").render_sql("209955")

    def account(self, pidm, student=True):
        self.db.execute("INSERT INTO saturn.spriden VALUES (?, ?, 'Synthetic', 'Student', NULL)",
                        (pidm, f"TEST-{pidm}"))
        if student:
            self.db.execute("INSERT INTO saturn.sgbstdn VALUES (?)", (pidm,))

    def transaction(self, pidm, code="CASH", amount=100, balance=-100,
                    term="209955", number=1):
        self.db.execute("INSERT INTO taismgr.tbraccd VALUES (?, ?, ?, ?, 'Synthetic', ?, ?, NULL, NULL)",
                        (pidm, term, number, code, amount, balance))

    def rows(self):
        return self.db.execute(self.query).fetchall()

    def test_future_student_and_other_term_charges_do_not_exclude(self):
        self.account(1)
        self.transaction(1, balance=-25)
        self.transaction(1, "CHARGE", balance=100, term="209980")
        self.db.execute("INSERT INTO saturn.sgbstdn VALUES (1)")
        self.db.execute("INSERT INTO saturn.spriden VALUES (1, 'OLD', 'Old', 'Name', 'N')")
        rows = self.rows()
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0][0], "TEST-1")
        self.assertEqual(rows[0][8:11], (100, -25, 25))

    def test_any_charge_history_excludes_even_zero_or_fully_reversed(self):
        for pidm, amount in [(1, 100), (2, 0), (3, -100)]:
            self.account(pidm)
            self.transaction(pidm)
            self.transaction(pidm, "CHARGE", amount=amount, balance=0)
        self.transaction(3, "CHARGE", amount=100, balance=0, number=3)
        self.assertEqual(self.rows(), [])

    def test_applied_reversed_noncash_missing_and_nonstudent_excluded(self):
        for pidm in range(1, 9):
            self.account(pidm, student=pidm != 8)
        self.transaction(1, balance=0)
        self.transaction(2, amount=-100)
        self.transaction(3, amount=0)
        self.transaction(4, "AID")
        self.transaction(5)
        self.transaction(5, "MISSING", number=2)
        self.transaction(6)
        self.transaction(6, "UNKNOWN", number=2)
        self.transaction(7, balance=None)
        self.transaction(8)
        self.assertEqual(self.rows(), [])

    def test_multiple_payments_and_term_filter_preserve_transaction_rows(self):
        self.account(1)
        self.transaction(1)
        self.transaction(1, number=2)
        self.transaction(1, term="209980", number=3)
        rows = self.rows()
        self.assertEqual([row[4] for row in rows], [1, 2])
        self.assertEqual([row[-1] for row in rows], [2, 2])


class TermCorrectionServiceTests(unittest.TestCase):
    def test_access_count_and_export(self):
        for administrator, count, success in [(False, 1, False), (True, 2, False),
                                              (True, None, False), (True, True, False),
                                              (True, 1, True)]:
            with self.subTest(administrator=administrator, count=count):
                client = MagicMock()
                client.__enter__.return_value = client
                client.run_sql.return_value = pd.DataFrame({
                    "CWID": ["TEST-1"], "Available Credit": [25],
                    "Report Row Count": [count],
                })
                policy = MagicMock()
                policy.is_administrator.return_value = administrator
                profile = MagicMock()
                with tempfile.TemporaryDirectory() as directory, patch(
                    "app.gui.services.insights.load_department_profiles", return_value={"TEST": profile}
                ), patch(
                    "app.gui.services.insights.load_access_configuration", return_value=policy
                ), patch(
                    "app.gui.services.insights.get_shared_gui_access_path", return_value=Path(directory) / "access.json"
                ), patch(
                    "app.gui.services.insights.build_authenticated_client", return_value=(client, "cached")
                ) as build:
                    output = Path(directory) / "review.xlsx"
                    result = run_insights_connection(WorkflowContext(
                        "insights_query_export", {"action": "query_export",
                        "query_id": "payments_without_charges", "term_code": "209955",
                        "output_path": str(output)}, WorkflowMode.TEST,
                    ))
                    self.assertEqual(result.success, success, result.message)
                    self.assertEqual(output.exists(), success)
                    if not administrator:
                        self.assertIn("administrator", result.message)
                        build.assert_not_called()
                    if success:
                        self.assertNotIn("{{", client.run_sql.call_args.args[0])
                        exported = pd.read_excel(output)
                        self.assertEqual(list(exported.columns), ["CWID", "Available Credit"])

    def test_catalog_rejects_missing_and_injected_terms(self):
        query = get_query("payments_without_charges")
        for term in (None, "202655'; DELETE FROM tbraccd; --", "20265"):
            with self.subTest(term=term), self.assertRaises(ValueError):
                query.render_sql(term)


if __name__ == "__main__":
    unittest.main()
