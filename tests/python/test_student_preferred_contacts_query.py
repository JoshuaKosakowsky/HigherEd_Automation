"""Execute the staff/app SQL with synthetic contacts; no live Banner access."""

import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

import pandas as pd

from app.gui.models import WorkflowContext, WorkflowMode
from app.gui.services.insights import run_insights_connection
from shared.insights.config import InsightsDepartmentProfile, InsightsSettings
from shared.insights.query_catalog import get_query


class StudentPreferredContactsTests(unittest.TestCase):
    def setUp(self):
        self.db = sqlite3.connect(":memory:")
        self.addCleanup(self.db.close)
        self.db.row_factory = sqlite3.Row
        self.query = get_query("contact_lookup")
        self.db.executescript("""
            ATTACH DATABASE ':memory:' AS saturn;
            ATTACH DATABASE ':memory:' AS general;
            ATTACH DATABASE ':memory:' AS taismgr;
            CREATE TABLE taismgr.tbbacct (
                tbbacct_pidm INTEGER, tbbacct_activity_date TEXT
            );
            INSERT INTO taismgr.tbbacct VALUES
                (1, '2099-10-01'), (2, '2099-10-01'), (3, '2099-10-01'),
                (4, '2099-10-01');
            CREATE TABLE saturn.spriden (
                spriden_pidm INTEGER, spriden_id TEXT, spriden_first_name TEXT,
                spriden_last_name TEXT, spriden_change_ind TEXT
            );
            CREATE TABLE saturn.sgbstdn (sgbstdn_pidm INTEGER);
            CREATE TABLE general.goremal (
                goremal_pidm INTEGER, goremal_emal_code TEXT,
                goremal_email_address TEXT, goremal_status_ind TEXT,
                goremal_preferred_ind TEXT, goremal_activity_date TEXT
            );
            CREATE TABLE saturn.sprtele (
                sprtele_pidm INTEGER, sprtele_tele_code TEXT,
                sprtele_phone_area TEXT, sprtele_phone_number TEXT,
                sprtele_phone_ext TEXT, sprtele_primary_ind TEXT,
                sprtele_status_ind TEXT, sprtele_seqno INTEGER
            );
            INSERT INTO saturn.spriden VALUES
                (1, 'TEST-1', 'Synthetic', 'Student', NULL),
                (2, 'TEST-2', 'Former', 'Student', NULL),
                (3, 'TEST-3', 'Missing', 'Contacts', NULL),
                (4, 'TEST-STAFF', 'Staff', 'Only', NULL),
                (1, 'OLD-ID', 'Old', 'Identity', 'I'),
                (1, 'TEST-1', 'Synthetic', 'Student', NULL);
            INSERT INTO saturn.sgbstdn VALUES (1), (1), (2), (3);
        """)

    def results(self):
        # Adapt only PostgreSQL date arithmetic to fixed SQLite date literals.
        # Identity/contact selection and MATERIALIZED scopes run unchanged.
        sql = self.query.render_sql().replace(
            "date_trunc('month', CURRENT_DATE) - INTERVAL '8 years'",
            "'2091-10-01'",
        ).replace("CURRENT_DATE + INTERVAL '1 day'", "'2099-10-17'")
        return [dict(row) for row in self.db.execute(sql)]

    def test_duplicate_flags_do_not_multiply_students_and_ties_are_stable(self):
        self.db.executescript("""
            INSERT INTO general.goremal VALUES
                (1, 'PERS', 'personal@example.invalid', 'A', 'Y', '2099-01-01'),
                (1, 'UNIV', 'old@example.invalid', 'A', 'Y', '2000-01-01'),
                (1, 'UNIV', 'z@example.invalid', 'A', 'Y', '2001-01-01'),
                (1, 'UNIV', 'a@example.invalid', 'A', 'Y', '2001-01-01'),
                (1, 'UNIV', 'null-date@example.invalid', 'A', 'Y', NULL);
            INSERT INTO saturn.sprtele VALUES
                (1, 'HOME', '303', '5550100', NULL, 'Y', NULL, 1),
                (1, 'CELL', '720', '5550102', NULL, 'Y', 'A', 2),
                (1, 'CELL', '720', '5550101', '123', 'Y', NULL, 2);
        """)
        rows = self.results()
        self.assertEqual([r['CWID'] for r in rows], ['TEST-1'])
        self.assertEqual(rows[0]['Preferred Email'], 'a@example.invalid')
        self.assertEqual(rows[0]['Email Type'], 'UNIV')
        self.assertEqual(rows[0]['Preferred Phone'], '(720) 5550101 x123')
        self.assertEqual(rows[0]['Phone Type'], 'CELL')
        self.assertNotIn('Report Row Count', rows[0])

    def test_only_valid_preferred_contacts_and_incomplete_students_excluded(self):
        self.db.executescript("""
            INSERT INTO general.goremal VALUES
                (2, 'UNIV', 'inactive@example.invalid', 'I', 'Y', '2099-01-01'),
                (2, 'UNIV', 'unpreferred@example.invalid', 'A', 'N', '2099-01-01'),
                (2, 'UNIV', '   ', 'A', 'Y', '2099-01-01'),
                (2, 'PERS', ' personal@example.invalid ', 'A', 'Y', NULL),
                (3, 'UNIV', 'unpreferred@example.invalid', 'A', 'N', NULL);
            INSERT INTO saturn.sprtele VALUES
                (2, 'HOME', NULL, '5550100', NULL, 'Y', NULL, 1),
                (2, 'CELL', '303', '5550101', NULL, 'Y', ' i ', 99),
                (2, 'CELL', '303', '5550102', NULL, 'N', 'A', 100),
                (2, 'CELL', '303', '  ', NULL, 'Y', 'A', 101),
                (3, 'CELL', '303', '5550103', NULL, 'N', 'A', 1);
        """)
        rows = self.results()
        self.assertEqual([r['CWID'] for r in rows], ['TEST-2'])
        self.assertEqual(rows[0]['Preferred Email'], 'personal@example.invalid')
        self.assertEqual(rows[0]['Email Type'], 'PERS')
        self.assertEqual(rows[0]['Preferred Phone'], '5550100')

    def test_empty_student_population(self):
        self.db.execute('DELETE FROM saturn.sgbstdn')
        self.assertEqual(self.results(), [])

    def add_complete_contacts(self):
        self.db.executescript("""
            INSERT INTO general.goremal VALUES
                (2, 'PERS', 'personal@example.invalid', 'A', 'Y', NULL);
            INSERT INTO saturn.sprtele VALUES
                (2, 'CELL', NULL, '5550100', NULL, 'Y', NULL, 1);
        """)

    def test_account_recency_boundaries_and_missing_dates(self):
        self.add_complete_contacts()
        self.db.execute('DELETE FROM taismgr.tbbacct WHERE tbbacct_pidm = 2')
        self.assertEqual(self.results(), [])
        for activity, qualifies in (
            (None, False),
            ('2091-09-30 23:59:59', False),
            ('2091-10-01', True),
            ('2095-10-01', True),  # Four-year-old account is inside the new window.
            ('2099-10-16 23:59:59', True),
            ('2099-10-17', False),
        ):
            with self.subTest(activity=activity):
                self.db.execute('DELETE FROM taismgr.tbbacct WHERE tbbacct_pidm = 2')
                self.db.execute('INSERT INTO taismgr.tbbacct VALUES (2, ?)', (activity,))
                self.assertEqual([r['CWID'] for r in self.results()],
                                 ['TEST-2'] if qualifies else [])

    def test_account_history_does_not_duplicate_or_override_recent_account(self):
        self.add_complete_contacts()
        self.db.executescript("""
            INSERT INTO taismgr.tbbacct VALUES
                (2, '2000-01-01'), (2, NULL), (2, '2099-10-01'),
                (2, '2100-01-01');
        """)
        self.assertEqual([r['CWID'] for r in self.results()], ['TEST-2'])
        # A recent email does not make an old account qualify.
        self.db.execute("UPDATE general.goremal SET goremal_activity_date = '2099-10-16'")
        self.db.execute("UPDATE taismgr.tbbacct SET tbbacct_activity_date = '2000-01-01'")
        self.assertEqual(self.results(), [])

    def test_each_missing_or_blank_contact_field_excludes_student(self):
        self.add_complete_contacts()
        fields = (
            ('general.goremal', 'goremal_email_address', 'personal@example.invalid'),
            ('general.goremal', 'goremal_emal_code', 'PERS'),
            ('saturn.sprtele', 'sprtele_phone_number', '5550100'),
            ('saturn.sprtele', 'sprtele_tele_code', 'CELL'),
        )
        for table, column, original in fields:
            for missing in (None, '', '   '):
                with self.subTest(column=column, missing=missing):
                    self.db.execute(f'UPDATE {table} SET {column} = ?', (missing,))
                    self.assertEqual(self.results(), [])
                    self.db.execute(f'UPDATE {table} SET {column} = ?', (original,))
        self.assertEqual([r['CWID'] for r in self.results()], ['TEST-2'])

    def test_prod_export_uses_same_sql_without_row_count_column(self):
        self.add_complete_contacts()
        profile = InsightsDepartmentProfile(
            InsightsSettings('PROD', 'https://prod.example.edu', 7),
            'https://experience.example.edu/prod',
        )
        client = MagicMock()
        client.__enter__.return_value = client
        client.run_sql_file.return_value = pd.DataFrame(self.results())
        self.assertIsNone(self.query.result_count_column)
        with tempfile.TemporaryDirectory() as directory, patch(
            'app.gui.services.insights.load_department_profiles',
            return_value={'PROD': profile},
        ), patch(
            'app.gui.services.insights.build_authenticated_client',
            return_value=(client, 'cached session'),
        ) as build:
            output = Path(directory) / 'contacts.xlsx'
            result = run_insights_connection(WorkflowContext(
                'insights_query_export',
                {'action': 'query_export', 'query_id': 'contact_lookup',
                 'output_path': str(output)},
                WorkflowMode.PRODUCTION,
            ))
            self.assertTrue(result.success, result.message)
            exported = pd.read_excel(output)
            self.assertEqual(exported['CWID'].tolist(), ['TEST-2'])
            self.assertEqual(list(exported.columns), [
                'CWID', 'First Name', 'Last Name', 'Preferred Email',
                'Email Type', 'Preferred Phone', 'Phone Type',
            ])
            self.assertEqual(build.call_args.args[0].environment, 'PROD')
        client.run_sql_file.assert_called_once_with(self.query.sql_path)
        client.run_sql.assert_not_called()


if __name__ == '__main__':
    unittest.main()
