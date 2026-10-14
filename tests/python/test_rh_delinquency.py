"""Verify RH selection and the shared export path without live Banner access."""
import sqlite3
import tempfile
import unittest
from datetime import datetime
from pathlib import Path
from unittest.mock import MagicMock, patch

import pandas as pd
from openpyxl import load_workbook

from app.gui.models import WorkflowContext, WorkflowMode
from app.gui.services.insights import _export_query, run_insights_connection
from shared.insights.config import InsightsConfigurationError
from shared.insights.query_catalog import get_query


class RHDelinquencyQueryTests(unittest.TestCase):
    def setUp(self):
        self.db = sqlite3.connect(":memory:")
        self.addCleanup(self.db.close)
        self.db.executescript("""
            ATTACH DATABASE ':memory:' AS taismgr;
            ATTACH DATABASE ':memory:' AS saturn;
            CREATE TABLE taismgr.tbbacct (
                tbbacct_pidm INTEGER, tbbacct_deli_code TEXT,
                tbbacct_activity_date TEXT
            );
            CREATE TABLE saturn.spriden (
                spriden_pidm INTEGER, spriden_id TEXT,
                spriden_first_name TEXT, spriden_last_name TEXT,
                spriden_change_ind TEXT
            );
            CREATE TABLE saturn.sgbstdn (sgbstdn_pidm INTEGER);
        """)
        # SQLite does not implement PostgreSQL's CAST(... AS date).
        self.query = get_query("rh_delinquency").render_sql().replace(
            "CAST(MAX(a.tbbacct_activity_date) AS date)",
            "date(MAX(a.tbbacct_activity_date))",
        )

    def account(self, pidm, code="RH", activity=None, student=True):
        self.db.execute(
            "INSERT INTO saturn.spriden VALUES (?, ?, 'Synthetic', 'Student', NULL)",
            (pidm, f"TEST-{pidm}"),
        )
        if student:
            self.db.execute("INSERT INTO saturn.sgbstdn VALUES (?)", (pidm,))
        self.db.execute("INSERT INTO taismgr.tbbacct VALUES (?, ?, ?)",
                        (pidm, code, activity))

    def test_all_rh_students_without_date_balance_or_enrollment_filter(self):
        self.account(1, activity="2000-01-01")
        self.account(2, " rh ", "2099-12-31")
        self.account(3)  # Unknown date must remain in the review list.
        self.account(4, "PP")
        self.account(5, None)
        self.account(6, student=False)
        self.account(7, "")
        self.assertEqual(self.db.execute(self.query).fetchall(), [
            ("TEST-1", "Synthetic", "Student", "RH", "2000-01-01", 3),
            ("TEST-2", "Synthetic", "Student", "RH", "2099-12-31", 3),
            ("TEST-3", "Synthetic", "Student", "RH", None, 3),
        ])

    def test_multiple_controls_history_and_old_identity_do_not_duplicate(self):
        self.account(1, activity="2099-01-01")
        self.db.executescript("""
            INSERT INTO taismgr.tbbacct VALUES (1, ' rh ', '2099-02-01 14:30:00');
            INSERT INTO taismgr.tbbacct VALUES (1, 'RH', NULL);
            INSERT INTO taismgr.tbbacct VALUES (1, 'PP', '2099-03-01');
            INSERT INTO saturn.sgbstdn VALUES (1);
            INSERT INTO saturn.spriden VALUES (1, 'OLD', 'Old', 'Name', 'N');
        """)
        self.assertEqual(self.db.execute(self.query).fetchall(), [
            ("TEST-1", "Synthetic", "Student", "RH", "2099-02-01", 1),
        ])

    def test_no_rh_returns_empty_result_with_expected_columns(self):
        self.account(1, "PP")
        cursor = self.db.execute(self.query)
        self.assertEqual(cursor.fetchall(), [])
        self.assertEqual([column[0] for column in cursor.description], [
            "CWID", "First Name", "Last Name", "Delinquency Code",
            "Account Activity Date", "Report Row Count",
        ])


class RHDelinquencyExportTests(unittest.TestCase):
    def test_account_activity_exports_real_date_cells_and_preserves_blanks(self):
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "dates.xlsx"
            _export_query(pd.DataFrame({
                "Account Activity Date": ["2099-02-01", None],
                "Feed Date": ["2099-02-01T14:30:00Z", None],
            }), output)
            workbook = load_workbook(output)
            self.addCleanup(workbook.close)
            sheet = workbook.active
            self.assertTrue(sheet["A2"].is_date)
            self.assertEqual(sheet["A2"].value, datetime(2099, 2, 1))
            self.assertEqual(sheet["A2"].number_format.lower(), "yyyy-mm-dd")
            self.assertIsNone(sheet["A3"].value)
            self.assertEqual(sheet["B2"].value, datetime(2099, 2, 1, 14, 30))

    def test_invalid_activity_date_does_not_save_workbook(self):
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "invalid.xlsx"
            with self.assertRaises(InsightsConfigurationError):
                _export_query(pd.DataFrame({"Account Activity Date": ["invalid"]}), output)
            self.assertFalse(output.exists())

    def test_access_completeness_empty_export_and_existing_file(self):
        for administrator, count, empty, existing, success in (
            (False, 1, False, False, False),
            (True, 2, False, False, False),
            (True, None, False, False, False),
            (True, True, False, False, False),
            (True, 1, False, False, True),
            (True, 0, True, False, True),
            (True, 1, False, True, False),
        ):
            with self.subTest(administrator=administrator, count=count,
                              empty=empty, existing=existing):
                client = MagicMock()
                client.__enter__.return_value = client
                frame = pd.DataFrame({
                    "CWID": ["TEST-1"], "Delinquency Code": ["RH"],
                    "Account Activity Date": [None], "Report Row Count": [count],
                })
                client.run_sql_file.return_value = frame.iloc[:0] if empty else frame
                policy = MagicMock()
                policy.is_administrator.return_value = administrator
                with tempfile.TemporaryDirectory() as directory, patch(
                    "app.gui.services.insights.load_department_profiles",
                    return_value={"TEST": MagicMock()},
                ), patch(
                    "app.gui.services.insights.load_access_configuration", return_value=policy,
                ), patch(
                    "app.gui.services.insights.get_shared_gui_access_path",
                    return_value=Path(directory) / "access.json",
                ), patch(
                    "app.gui.services.insights.build_authenticated_client",
                    return_value=(client, "cached"),
                ) as build:
                    output = Path(directory) / "rh.xlsx"
                    if existing:
                        output.write_bytes(b"preserve existing workbook")
                    result = run_insights_connection(WorkflowContext(
                        "insights_query_export", {"action": "query_export",
                        "query_id": "rh_delinquency", "output_path": str(output)},
                        WorkflowMode.TEST,
                    ))
                    self.assertEqual(result.success, success, result.message)
                    if existing:
                        self.assertEqual(output.read_bytes(), b"preserve existing workbook")
                        build.assert_not_called()
                    else:
                        self.assertEqual(output.exists(), success)
                    if not administrator:
                        self.assertIn("administrator", result.message)
                        build.assert_not_called()
                    if success:
                        client.run_sql_file.assert_called_once_with(
                            get_query("rh_delinquency").sql_path,
                        )
                        exported = pd.read_excel(output)
                        self.assertNotIn("Report Row Count", exported.columns)
                        self.assertEqual(len(exported), 0 if empty else 1)


if __name__ == "__main__":
    unittest.main()
