"""Upload-based W&F review, with administrator-only complete PROD extracts."""
from __future__ import annotations

from pathlib import Path

from app.gui import APP_VERSION
from app.gui.models import WorkflowContext, WorkflowMode, WorkflowResult
from app.gui.services.access import get_current_login, load_access_configuration
from data_processing.shared.workbook_output import validate_output
from data_processing.wf_mines_balance_recon.workbook import create_review_workbook, read_insights_file
from data_processing.wf_mines_balance_recon.source_workbooks import SOURCE_SUFFIXES
from data_processing.wf_mines_balance_recon.reconciliation import load_submission_percentage
from shared.cancellation import WorkflowCancelled
from shared.insights.auth import InsightsAuthenticationError
from shared.insights.browser_auth import InsightsBrowserAuthenticationError
from shared.insights.client import InsightsAPIError
from shared.insights.config import InsightsConfigurationError, load_department_profiles
from shared.insights.query_catalog import get_query
from shared.insights.report_results import InsightsReportResultError, checked_report_result
from shared.insights.session_auth import InsightsSessionError, build_authenticated_client
from shared.insights.session_cache import InsightsCredentialError
from shared.mines_paths import get_shared_gui_access_path


def _safe_extraction_failure(error: Exception, stage: str) -> str:
    """Only static categories, local report titles and aggregate counts escape."""
    detail = 'Unexpected application error; technical details withheld.'
    if isinstance(error, InsightsReportResultError):
        if error.reason == 'incomplete':
            detail = f'Incomplete result: received {error.received_rows:,} of {error.expected_rows:,} rows.'
        elif error.reason == 'missing_count':
            detail = 'The result is missing the Report Row Count completeness column.'
        else:
            detail = 'The result contains invalid or inconsistent completeness counts.'
    elif isinstance(error, InsightsAPIError):
        status = error.status_code
        if isinstance(status, int) and not isinstance(status, bool) and 100 <= status <= 599:
            detail = {
                401: 'HTTP 401: session expired or unauthenticated. Use Connections to sign in again.',
                403: 'HTTP 403: permission to run the report was refused.',
                429: 'HTTP 429: Insights request limit reached. Retry later.',
            }.get(status, f'Insights API rejected the request (HTTP {status}).')
        else:
            detail = {
                'timeout': 'The Insights request timed out.',
                'connection': 'The Insights API could not be reached.',
                'query_failed': 'The server did not complete the SQL query. Run this report in the Insights editor to inspect its database error.',
                'invalid_response': 'The Insights API returned an unreadable response.',
                'source_changed': 'Source counts changed during extraction. Retry when the source data is stable.',
                'key_group_cap': 'One transaction group still exceeds the API limit. Use the full Insights export.',
            }.get(error.code, 'The Insights API request failed; server details withheld.')
    elif isinstance(error, (InsightsAuthenticationError, InsightsBrowserAuthenticationError,
                            InsightsSessionError, InsightsCredentialError)):
        detail = 'Sign-in or session validation failed. Use Connections to sign in again.'
    elif isinstance(error, InsightsConfigurationError):
        detail = 'PROD Insights configuration is missing or invalid.'
    elif isinstance(error, FileNotFoundError):
        detail = 'A required local SQL file is unavailable. Update this application installation.'
    return (f'Insights extraction failed during {stage}. {detail} '
            'You can upload the complete combined Insights export instead. No workbook was saved.')


def run_wf_mines_balance_recon(context: WorkflowContext) -> WorkflowResult:
    percentage = load_submission_percentage()
    source = context.parameters.get('banner_source')
    if source not in {'manual', 'sql'}:
        raise ValueError('Choose the Insights data source.')
    if context.cancellation:
        context.cancellation.check()
    if source == 'sql':
        policy = load_access_configuration(get_shared_gui_access_path())
        if not policy.is_administrator(get_current_login()):
            raise ValueError('Only an administrator can query W&F source reports from PROD Insights.')
        if context.mode != WorkflowMode.PRODUCTION:
            raise ValueError('Direct W&F source extraction requires PROD Insights.')
    elif context.mode is not None:
        raise ValueError('File upload review does not use TEST or PROD.')
    selected = context.parameters.get('wf_files')
    if not isinstance(selected, (tuple, list)) or not selected:
        raise ValueError('Upload at least one Williams and Fudge workbook.')
    files = tuple(Path(path) for path in selected)
    if len({path.resolve() for path in files}) != len(files):
        raise ValueError('The W&F upload list contains a duplicate file path.')
    if any(not path.is_file() or path.suffix.lower() not in SOURCE_SUFFIXES for path in files):
        raise ValueError('W&F uploads must be existing CSV, XLS, XLSX, or XLSM files.')
    manual_paths = tuple(Path(context.parameters[key]) for key in ('banner_file',)) if source == 'manual' else ()
    if any(not path.is_file() for path in manual_paths):
        raise ValueError('Upload the combined Insights report before running.')
    output = Path(context.parameters['output_file'])
    validate_output(output, (*files, *manual_paths))
    if source == 'manual':
        context.progress.report('Reading the combined Insights upload')
        students = read_insights_file(manual_paths[0], 'students')
    else:
        context.progress.report('Connecting to PROD Insights — complete sign-in if prompted')
        stage = 'loading the PROD configuration'
        try:
            profile = load_department_profiles()[WorkflowMode.PRODUCTION.value]
            if profile is None:
                raise InsightsConfigurationError('PROD Insights is not configured.')
            stage = 'sign-in/session validation'
            client, _ = build_authenticated_client(
                profile.settings, browser='chrome', experience_url=profile.experience_url,
                use_saved_mines_login=True,
            )
            with client:
                query = get_query('collections_tracking')
                stage = f'querying {query.title}'
                context.progress.report(f'Extracting and checking {query.title}')
                if context.cancellation:
                    context.cancellation.check()
                frame = client.run_sql_file(query.sql_path)
                if context.cancellation:
                    context.cancellation.check()
                stage = f'checking completeness of {query.title}'
                students = checked_report_result(frame, query.result_count_column)
                stage = 'closing the Insights session'
        except WorkflowCancelled:
            raise
        except Exception as error:
            # Auth exceptions can carry credential-bearing URLs; keep this boundary.
            raise ValueError(_safe_extraction_failure(error, stage)) from None
    if context.cancellation:
        context.cancellation.check()
    context.progress.report('Comparing Banner and W&F accounts and saving reconciliation')
    count = create_review_workbook(
        students, files, output,
        app_version=APP_VERSION, cancellation=context.cancellation,
        submission_percentage=percentage,
    )
    return WorkflowResult(
        True, f'Created reconciliation: {len(students):,} Banner accounts, '
        f'{len(files):,} W&F files / {count:,} source worksheets. '
        'Review Reconciliation for account differences and returned status.',
        output,
    )
