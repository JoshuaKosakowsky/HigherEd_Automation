"""Exercise W&F extraction failures without exposing auth or source data."""
import tempfile
import traceback
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

import pandas as pd
import requests

from app.gui.models import WorkflowContext, WorkflowMode
from app.gui.services.wf_mines_balance_recon import run_wf_mines_balance_recon
from shared.insights.browser_auth import InsightsBrowserAuthenticationError
from shared.insights.client import InsightsAPIError, InsightsClient
from shared.insights.report_results import InsightsReportResultError, checked_report_result
from test_insights import StubSession, make_response
from test_wf_mines_balance_recon import holds_frame, activity_frame


class WFInsightsDiagnosticsTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.output = self.root / 'review.xlsx'
        path_patch = patch('app.gui.services.wf_mines_balance_recon.get_shared_gui_access_path', return_value=self.root / 'access.json')
        path_patch.start()
        self.addCleanup(path_patch.stop)
        wf = self.root / 'synthetic.xlsx'
        wf.touch()
        self.context = WorkflowContext('wf_mines_balance_recon', dict(
            banner_source='sql', detail_codes='WOFF, BDRC', wf_files=(wf,), output_file=self.output,
        ), WorkflowMode.PRODUCTION)
        self.client = MagicMock()
        self.client.__enter__.return_value = self.client
        self.holds, self.activity = holds_frame(), activity_frame()
        self.holds['Report Row Count'] = 1
        self.activity['Report Row Count'] = 1
        self.client.run_sql_file.return_value = self.holds
        self.client.run_sql.return_value = self.activity

    def failure(self, *, auth_error=None, missing_profile=False):
        with patch('app.gui.services.wf_mines_balance_recon.load_access_configuration') as policy, patch(
            'app.gui.services.wf_mines_balance_recon.load_department_profiles',
            return_value={'PROD': None if missing_profile else MagicMock()},
        ), patch('app.gui.services.wf_mines_balance_recon.build_authenticated_client',
                 return_value=(self.client, 'cached'), side_effect=auth_error), patch(
            'app.gui.services.wf_mines_balance_recon.create_review_workbook',
        ) as publish:
            policy.return_value.is_administrator.return_value = True
            with self.assertRaises(ValueError) as caught:
                run_wf_mines_balance_recon(self.context)
            publish.assert_not_called()
        self.assertFalse(self.output.exists())
        error = caught.exception
        self.assertTrue(error.__suppress_context__)
        self.assertNotIn('SECRET', str(error))
        self.assertNotIn('SECRET', ''.join(traceback.format_exception(error)))
        self.assertIn('No workbook was saved', str(error))
        return str(error)

    def test_missing_prod_configuration_is_identified_without_sign_in(self):
        result = self.failure(missing_profile=True)
        self.assertIn('loading the PROD configuration', result)
        self.assertIn('configuration is missing or invalid', result)

    def test_stage_and_safe_categories_distinguish_auth_first_and_second_reports(self):
        for stage, error, message in (
            ('auth', InsightsBrowserAuthenticationError('SECRET auth URL'), 'sign-in/session validation'),
            ('holds', InsightsAPIError('SECRET response', status_code=403), 'querying W&F - Banner Recon. HTTP 403'),
            ('holds', InsightsAPIError('SECRET response', status_code=401), 'session expired'),
            ('holds', InsightsAPIError('SECRET response', status_code=429), 'request limit reached'),
            ('activity', InsightsAPIError('SECRET URL', code='timeout'), 'querying W&F - Banner Recon. The Insights request timed out'),
            ('activity', InsightsAPIError('SECRET database error', code='query_failed'), 'server did not complete the SQL query'),
            ('holds', FileNotFoundError('SECRET local path'), 'required local SQL file'),
            ('holds', RuntimeError('SECRET unexpected error'), 'Unexpected application error'),
        ):
            with self.subTest(stage=stage, message=message):
                self.client.run_sql_file.side_effect = error if stage in {'holds', 'activity'} else None
                self.client.run_sql.side_effect = error if stage == 'activity' else None
                result = self.failure(auth_error=error if stage == 'auth' else None)
                self.assertIn(message, result)

    def test_missing_invalid_and_capped_counts_identify_the_report_and_safe_counts(self):
        cases = (
            ('holds', pd.DataFrame({'Name': ['SECRET source row']}), 'W&F - Banner Recon', 'missing the Report Row Count'),
            ('holds', pd.DataFrame({'Name': ['SECRET source row'], 'Report Row Count': [5]}),
             'W&F - Banner Recon', 'received 1 of 5 rows'),
            ('activity', pd.DataFrame({'Name': ['SECRET source row'], 'Report Row Count': [1.0]}),
             'W&F - Banner Recon', 'invalid or inconsistent'),
        )
        for report, frame, name, message in cases:
            with self.subTest(report=report, message=message):
                self.client.run_sql_file.return_value = frame
                self.client.run_sql.return_value = frame if report == 'activity' else self.activity
                result = self.failure()
                self.assertIn(f'checking completeness of {name}', result)
                self.assertIn(message, result)

    def test_report_validator_retains_strict_acceptance_and_exposes_only_aggregate_metadata(self):
        for frame, reason in (
            (pd.DataFrame({'Value': ['SECRET']}), 'missing_count'),
            (pd.DataFrame({'Report Row Count': [True]}), 'invalid_count'),
            (pd.DataFrame({'Report Row Count': [1.0]}), 'invalid_count'),
            (pd.DataFrame({'Report Row Count': [0]}), 'invalid_count'),
            (pd.DataFrame({'Report Row Count': [2, 3]}), 'invalid_count'),
            (pd.DataFrame([[1, 1]], columns=['Report Row Count', 'Report Row Count']), 'invalid_count'),
            (pd.DataFrame({'Report Row Count': [9]}), 'incomplete'),
        ):
            with self.subTest(reason=reason), self.assertRaises(InsightsReportResultError) as caught:
                checked_report_result(frame, 'Report Row Count')
            self.assertEqual(caught.exception.reason, reason)
            self.assertNotIn('SECRET', str(caught.exception))
        for value in (1, '1'):
            result = checked_report_result(pd.DataFrame({'Value': [10], 'Report Row Count': [value]}), 'Report Row Count')
            self.assertEqual(result.to_dict('list'), {'Value': [10]})
        result = checked_report_result(pd.DataFrame(columns=['Value', 'Report Row Count']), 'Report Row Count')
        self.assertEqual(list(result.columns), ['Value'])

    def test_client_failure_codes_do_not_include_raw_response_or_timeout_secrets(self):
        client = InsightsClient('https://example.invalid', 1, api_key='synthetic')
        self.addCleanup(client.close)
        with patch.object(client._http_session, 'request', side_effect=requests.exceptions.Timeout('SECRET URL')):
            with self.assertRaises(InsightsAPIError) as caught:
                client.run_sql('SELECT 1')
        self.assertEqual(caught.exception.code, 'timeout')
        self.assertNotIn('SECRET', str(caught.exception))
        session = StubSession(make_response(200, {'status': 'failed', 'error': 'SECRET database details'}))
        client = InsightsClient('https://example.invalid', 1, api_key='synthetic', http_session=session)
        with self.assertRaises(InsightsAPIError) as caught:
            client.run_sql('SELECT 1')
        self.assertEqual(caught.exception.code, 'query_failed')
        self.assertNotIn('SECRET', str(caught.exception))


if __name__ == '__main__':
    unittest.main()
