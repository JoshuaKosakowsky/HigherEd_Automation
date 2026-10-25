"""Upload-based W&F review, with administrator-only complete PROD extracts."""
from __future__ import annotations

from pathlib import Path

from app.gui import APP_VERSION
from app.gui.models import WorkflowContext, WorkflowMode, WorkflowResult
from app.gui.services.access import get_current_login, load_access_configuration
from data_processing.shared.workbook_output import validate_output
from data_processing.wf_mines_balance_recon.workbook import create_review_workbook, read_insights_file
from shared.cancellation import WorkflowCancelled
from shared.insights.banner_activity import BannerDetailCodeParameters
from shared.insights.config import load_department_profiles
from shared.insights.query_catalog import get_query
from shared.insights.report_results import checked_report_result
from shared.insights.session_auth import build_authenticated_client
from shared.mines_paths import get_shared_gui_access_path


def run_wf_mines_balance_recon(context: WorkflowContext) -> WorkflowResult:
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
    codes = BannerDetailCodeParameters.from_inputs(
        context.parameters.get('detail_codes', 'WOFF, BDRC'),
    ) if source == 'sql' else None
    selected = context.parameters.get('wf_files')
    if not isinstance(selected, (tuple, list)) or not selected:
        raise ValueError('Upload at least one Williams and Fudge workbook.')
    files = tuple(Path(path) for path in selected)
    if len({path.resolve() for path in files}) != len(files):
        raise ValueError('The W&F upload list contains a duplicate file path.')
    if any(not path.is_file() or path.suffix.lower() not in {'.xlsx', '.xlsm'} for path in files):
        raise ValueError('W&F uploads must be existing XLSX or XLSM workbooks. Convert older XLS files in Excel first.')
    manual_paths = tuple(Path(context.parameters[key]) for key in ('holds_file', 'activity_file')) if source == 'manual' else ()
    if any(not path.is_file() for path in manual_paths):
        raise ValueError('Upload both original Insights reports before running.')
    output = Path(context.parameters['output_file'])
    validate_output(output, (*files, *manual_paths))
    if source == 'manual':
        context.progress.report('Reading the two Insights uploads')
        holds = read_insights_file(manual_paths[0], 'holds')
        activity = read_insights_file(manual_paths[1], 'activity')
        labels = tuple(path.name + ' (uploaded; coverage unconfirmed)' for path in manual_paths)
    else:
        context.progress.report('Connecting to PROD Insights — complete sign-in if prompted')
        try:
            profile = load_department_profiles()[WorkflowMode.PRODUCTION.value]
            if profile is None:
                raise ValueError('PROD Insights is not configured.')
            client, _ = build_authenticated_client(
                profile.settings, browser='chrome', experience_url=profile.experience_url,
                use_saved_mines_login=True,
            )
            with client:
                frames = []
                for query_id in ('collections_tracking', 'wf_mines_balance_transactions'):
                    if context.cancellation:
                        context.cancellation.check()
                    query = get_query(query_id)
                    context.progress.report(f'Extracting and checking {query.title}')
                    frame = (client.run_sql(query.render_sql(detail_codes=codes))
                             if query.default_detail_codes else client.run_sql_file(query.sql_path))
                    frames.append(checked_report_result(frame, query.result_count_column))
                holds, activity = frames
            labels = ('PROD Insights / Collections tracking (count checked)',
                      'PROD Insights / W&F transactions (count checked)')
        except WorkflowCancelled:
            raise
        except Exception:
            # Auth exceptions can carry credential-bearing URLs; keep this boundary.
            raise ValueError(
                'Insights extraction failed or returned incomplete results. Check PROD access and API limits. '
                'You can upload both complete Insights exports instead. No workbook was saved.'
            ) from None
    if context.cancellation:
        context.cancellation.check()
    context.progress.report('Collecting W&F worksheets and saving the source review workbook')
    count = create_review_workbook(
        holds, activity, files, output, source_labels=labels,
        app_version=APP_VERSION, cancellation=context.cancellation,
    )
    return WorkflowResult(
        True, f'Created source review: {len(holds):,} hold rows, {len(activity):,} detail-code rows, '
        f'{len(files):,} W&F files / {count:,} source worksheets. '
        'Review Sources for footer checks and unclassified files. No matching or reconciliation conclusions yet.',
        output,
    )
