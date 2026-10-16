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
        return [dict(row) for row in self.db.execute(self.query.render_sql())]

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
        self.assertEqual([r['CWID'] for r in rows], ['TEST-1', 'TEST-2', 'TEST-3'])
        self.assertEqual(rows[0]['Preferred Email'], 'a@example.invalid')
        self.assertEqual(rows[0]['Email Type'], 'UNIV')
        self.assertEqual(rows[0]['Preferred Phone'], '(720) 5550101 x123')
        self.assertEqual(rows[0]['Phone Type'], 'CELL')
        self.assertTrue(all(r['Report Row Count'] == 3 for r in rows))

    def test_only_valid_preferred_contacts_and_missing_contacts_retained(self):
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
        self.assertEqual(rows[1]['Preferred Email'], 'personal@example.invalid')
        self.assertEqual(rows[1]['Email Type'], 'PERS')
        self.assertEqual(rows[1]['Preferred Phone'], '5550100')
        self.assertIsNone(rows[2]['Preferred Email'])
        self.assertIsNone(rows[2]['Preferred Phone'])

    def test_empty_student_population(self):
        self.db.execute('DELETE FROM saturn.sgbstdn')
        self.assertEqual(self.results(), [])

    def test_prod_export_uses_same_sql_and_rejects_incomplete_results(self):
        profile = InsightsDepartmentProfile(
            InsightsSettings('PROD', 'https://prod.example.edu', 7),
            'https://experience.example.edu/prod',
        )
        client = MagicMock()
        client.__enter__.return_value = client
        complete = pd.DataFrame(self.results())
        with tempfile.TemporaryDirectory() as directory, patch(
            'app.gui.services.insights.load_department_profiles',
            return_value={'PROD': profile},
        ), patch(
            'app.gui.services.insights.build_authenticated_client',
            return_value=(client, 'cached session'),
        ) as build:
            for incomplete in (False, True):
                with self.subTest(incomplete=incomplete):
                    client.run_sql_file.return_value = (
                        complete.iloc[:1].copy() if incomplete else complete
                    )
                    output = Path(directory) / f'contacts-{incomplete}.xlsx'
                    result = run_insights_connection(WorkflowContext(
                        'insights_query_export',
                        {'action': 'query_export', 'query_id': 'contact_lookup',
                         'output_path': str(output)},
                        WorkflowMode.PRODUCTION,
                    ))
                    self.assertEqual(result.success, not incomplete, result.message)
                    self.assertEqual(output.exists(), not incomplete)
                    if not incomplete:
                        exported = pd.read_excel(output)
                        self.assertEqual(exported['CWID'].tolist(),
                                         ['TEST-1', 'TEST-2', 'TEST-3'])
                        self.assertEqual(list(exported.columns), list(complete.columns[:-1]))
                    else:
                        self.assertIn('incomplete', result.message)
            self.assertEqual(build.call_args.args[0].environment, 'PROD')
        client.run_sql_file.assert_called_with(self.query.sql_path)
        client.run_sql.assert_not_called()


if __name__ == '__main__':
    unittest.main()
