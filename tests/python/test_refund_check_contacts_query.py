"""Execute the shared staff/app SQL using synthetic data, without live access."""
import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

import pandas as pd

from app.gui.models import WorkflowContext, WorkflowMode
from app.gui.services.insights import run_insights_connection
from shared.insights.query_catalog import get_query


class RefundCheckContactsTests(unittest.TestCase):
    def setUp(self):
        self.db = sqlite3.connect(":memory:")
        self.addCleanup(self.db.close)
        self.db.row_factory = sqlite3.Row
        self.db.executescript("""
            ATTACH DATABASE ':memory:' AS taismgr;
            ATTACH DATABASE ':memory:' AS saturn;
            ATTACH DATABASE ':memory:' AS general;
            ATTACH DATABASE ':memory:' AS faismgr;
            CREATE TABLE taismgr.tbraccd (
                tbraccd_pidm INTEGER, tbraccd_detail_code TEXT, tbraccd_feed_date TEXT);
            CREATE TABLE saturn.spriden (
                spriden_pidm INTEGER, spriden_id TEXT, spriden_first_name TEXT,
                spriden_last_name TEXT, spriden_change_ind TEXT);
            CREATE TABLE general.goremal (
                goremal_pidm INTEGER, goremal_emal_code TEXT,
                goremal_email_address TEXT, goremal_status_ind TEXT,
                goremal_activity_date TEXT);
            CREATE TABLE saturn.sprtele (
                sprtele_pidm INTEGER, sprtele_tele_code TEXT,
                sprtele_phone_area TEXT, sprtele_phone_number TEXT,
                sprtele_phone_ext TEXT, sprtele_status_ind TEXT, sprtele_seqno INTEGER);
            CREATE TABLE faismgr.rlrpapp (
                rlrpapp_pidm INTEGER, rlrpapp_borrower_id_no TEXT,
                rlrpapp_borr_first_name TEXT, rlrpapp_borr_last_name TEXT,
                rlrpapp_borr_phone_no TEXT, rlrpapp_borr_email TEXT,
                rlrpapp_activity_date TEXT, rlrpapp_aidy_code TEXT);
            INSERT INTO saturn.spriden VALUES (1, 'TEST-A', 'Synthetic', 'Student', NULL);
        """)
        # Only date arithmetic changes; ranking, joins and flags execute unchanged.
        self.sql = get_query('refund_check_contacts').render_sql().replace(
            "CURRENT_DATE - INTERVAL '200 days'", "'2099-01-01'",
        ).replace("CURRENT_DATE + INTERVAL '1 day'", "'2099-07-21'")

    def refund(self, code='RFND', date='2099-07-20', pidm=1):
        self.db.execute('INSERT INTO taismgr.tbraccd VALUES (?, ?, ?)', (pidm, code, date))

    def borrower(self, suffix='01', email='parent@example.invalid', date='2099-01-01',
                 aid_year='9899', phone='5550100'):
        self.db.execute('INSERT INTO faismgr.rlrpapp VALUES (1, ?, ?, ?, ?, ?, ?, ?)',
                        (suffix, 'Synthetic', 'Parent', phone, email, date, aid_year))

    def rows(self):
        return [dict(row) for row in self.db.execute(self.sql)]

    def test_inclusive_dates_other_codes_and_null_future_dates(self):
        self.refund(date='2099-01-01')
        self.refund(date='2099-07-20 23:59:59')
        for date in ('2098-12-31 23:59:59', '2099-07-21', None):
            self.refund('RFDP', date)
        self.refund('RFDD')
        row, = self.rows()
        self.assertEqual(row['Detail Code'], 'RFND')
        self.assertEqual(row['First Feed Date'], '2099-01-01')
        self.assertEqual(row['Latest Feed Date'], '2099-07-20 23:59:59')

    def test_multiple_borrowers_both_codes_leading_zeros_and_duplicates(self):
        self.refund()
        self.refund('RFDP')
        self.refund('RFDP')
        for suffix in ('01', '02', '35', '01'):
            self.borrower(suffix)
        self.db.execute("INSERT INTO saturn.spriden VALUES (1, 'OLD', 'Old', 'Name', 'I')")
        self.db.execute("INSERT INTO saturn.spriden VALUES (1, 'TEST-A', 'Synthetic', 'Student', NULL)")
        rows = self.rows()
        parents = [r for r in rows if r['Recipient Type'] == 'Parent']
        self.assertEqual([r['Borrower CWID'] for r in parents],
                         ['TEST-A01', 'TEST-A02', 'TEST-A35'])
        self.assertTrue(all(r['Contact Review'] == 'Contacts available' for r in parents))
        self.assertEqual(len(rows), 4)
        self.assertTrue(all(r['Report Row Count'] == 4 for r in rows))
        self.assertNotIn('Transaction Number', rows[0])

    def test_student_ranking_and_missing_contacts_remain(self):
        self.refund()
        self.db.executescript("""
            INSERT INTO general.goremal VALUES
                (1, 'UNIV', 'old@example.invalid', 'A', '2098-01-01'),
                (1, 'UNIV', 'new@example.invalid', 'A', '2099-01-01'),
                (1, 'UNIV', 'inactive@example.invalid', 'I', '2099-02-01'),
                (1, 'PERS', 'personal@example.invalid', 'A', '2099-02-01');
            INSERT INTO saturn.sprtele VALUES
                (1, 'PR', '303', '5550100', '42', NULL, 1),
                (1, 'CELL', '720', '5550101', NULL, 'A', 99);
        """)
        row, = self.rows()
        self.assertEqual(row['Email'], 'new@example.invalid')
        self.assertEqual(row['Phone Number'], '(303) 5550100 x42')
        self.assertEqual(row['Contact Review'], 'Contacts available')
        self.db.execute("UPDATE saturn.sprtele SET sprtele_status_ind = 'I' WHERE sprtele_tele_code = 'PR'")
        self.db.execute('DELETE FROM general.goremal')
        row, = self.rows()
        self.assertEqual(row['Phone Source'], 'CELL')
        self.assertIn('Missing email', row['Contact Review'])
        self.db.execute('DELETE FROM saturn.sprtele')
        self.assertIn('Missing phone', self.rows()[0]['Contact Review'])

    def test_latest_whole_borrower_record_across_years_and_conflict_flag(self):
        self.refund('RFDP')
        self.borrower(email='old@example.invalid')
        self.borrower(email='latest@example.invalid', date='2099-02-01', aid_year='0001', phone=None)
        self.borrower(email='null-date@example.invalid', date=None, aid_year='9999')
        row, = self.rows()
        self.assertEqual(row['Email'], 'latest@example.invalid')
        self.assertIsNone(row['Phone Number'])  # Never backfill from another application.
        self.assertIn('Missing phone', row['Contact Review'])
        self.assertIn('Borrower contact records differ', row['Contact Review'])

    def test_missing_borrower_suffix_and_identity_are_retained(self):
        self.refund('RFDP')
        row, = self.rows()
        self.assertIsNone(row['Borrower CWID'])
        self.assertIn('Missing borrower suffix', row['Contact Review'])
        self.borrower(suffix='  ')
        row, = self.rows()
        self.assertIsNone(row['Borrower CWID'])
        self.assertEqual(row['Email Source'], 'RLRPAPP')
        self.db.execute('DELETE FROM saturn.spriden')
        row, = self.rows()
        self.assertIn('Missing student CWID', row['Contact Review'])
        self.assertEqual(row['Email'], 'parent@example.invalid')

    def test_equal_timestamp_ties_are_deterministic(self):
        self.refund('RFDP')
        self.borrower(email='z@example.invalid')
        self.borrower(email='a@example.invalid')
        row, = self.rows()
        self.assertEqual(row['Email'], 'a@example.invalid')
        self.assertIn('Borrower contact records differ', row['Contact Review'])

    def test_empty_result_preserves_columns(self):
        cursor = self.db.execute(self.sql)
        self.assertEqual(cursor.fetchall(), [])
        self.assertIn('Borrower CWID', [c[0] for c in cursor.description])

    def test_app_export_access_completeness_and_borrower_text(self):
        self.refund('RFDP')
        self.borrower()
        frame = pd.DataFrame(self.rows())
        query = get_query('refund_check_contacts')
        self.assertTrue(query.administrator_only)
        for administrator, count, success in ((False, 1, False), (True, 2, False), (True, 1, True)):
            with self.subTest(administrator=administrator, count=count):
                client = MagicMock()
                client.__enter__.return_value = client
                client.run_sql_file.return_value = frame.assign(**{'Report Row Count': count})
                policy = MagicMock()
                policy.is_administrator.return_value = administrator
                with tempfile.TemporaryDirectory() as directory, patch(
                    'app.gui.services.insights.load_department_profiles', return_value={'TEST': MagicMock()},
                ), patch(
                    'app.gui.services.insights.load_access_configuration', return_value=policy,
                ), patch(
                    'app.gui.services.insights.get_shared_gui_access_path', return_value=Path(directory) / 'access.json',
                ), patch(
                    'app.gui.services.insights.build_authenticated_client', return_value=(client, 'cached'),
                ) as build:
                    output = Path(directory) / 'contacts.xlsx'
                    result = run_insights_connection(WorkflowContext(
                        'insights_query_export', {'action': 'query_export', 'query_id': query.query_id,
                                                 'output_path': str(output)}, WorkflowMode.TEST,
                    ))
                    self.assertEqual(result.success, success, result.message)
                    self.assertEqual(output.exists(), success)
                    if not administrator:
                        build.assert_not_called()
                    if success:
                        client.run_sql_file.assert_called_once_with(query.sql_path)
                        exported = pd.read_excel(output, dtype=str)
                        self.assertEqual(exported.loc[0, 'Borrower Suffix'], '01')
                        self.assertEqual(exported.loc[0, 'Borrower CWID'], 'TEST-A01')
                        self.assertNotIn('Report Row Count', exported.columns)


if __name__ == '__main__':
    unittest.main()
