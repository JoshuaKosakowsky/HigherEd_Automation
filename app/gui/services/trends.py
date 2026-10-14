"""Admin-only trends review from annual uploads or checked PROD Insights SQL."""
from __future__ import annotations

from pathlib import Path

from app.gui.models import WorkflowContext, WorkflowMode, WorkflowResult
from app.gui.services.access import get_current_login, load_access_configuration
from data_processing.trends.config import TrendsConfig
from data_processing.trends.ingest import read_detail_codes, validate_annual_files
from data_processing.trends.pipeline import run_trends_review
from data_processing.trends.extract import TrendsExtractSettings, run_sql_trends_pipeline
from shared.cancellation import WorkflowCancelled
from shared.insights.detail_codes import refresh_detail_codes
from shared.insights.client import InsightsClient
from shared.insights.config import load_department_profiles
from shared.insights.session_auth import build_authenticated_client
from shared.mines_paths import get_shared_gui_access_path, get_shared_detail_codes_path


def run_trends(context: WorkflowContext) -> WorkflowResult:
    policy = load_access_configuration(get_shared_gui_access_path())
    if not policy.is_administrator(get_current_login()):
        raise ValueError("Only an administrator can run Historical Trends.")
    source = context.parameters.get("banner_source")
    if source not in {"manual", "sql"}:
        raise ValueError("Choose TGIACCD uploads or PROD Insights SQL for Historical Trends.")
    if source == "sql" and context.mode != WorkflowMode.PRODUCTION:
        raise ValueError("Historical Trends SQL requires PROD Insights.")
    if source == "manual" and context.mode is not None:
        raise ValueError("TGIACCD file uploads do not use TEST or PROD.")
    output = Path(context.parameters["output_file"])
    config = TrendsConfig(output_file=output, detail_codes_file=get_shared_detail_codes_path())
    if output.suffix.lower() != ".xlsx" or output.exists() or not output.parent.is_dir():
        raise ValueError("Choose an existing approved output folder and a new .xlsx filename.")
    if context.cancellation:
        context.cancellation.check()
    if source == "manual":
        try:
            read_detail_codes(config.detail_codes_file)
        except FileNotFoundError:
            raise ValueError(
                "The shared Banner detail-code reference is unavailable. An administrator "
                "must run Refresh Banner Detail Codes to create detail_codes.json beside gui_access.json in the shared "
                ".highered_automation folder. Confirm OneDrive has finished syncing."
            ) from None
        files = validate_annual_files([Path(path) for path in context.parameters["banner_file"]])
        context.progress.report("Reading annual TGIACCD uploads")
        created = run_trends_review(config, files=files,
            cancellation=context.cancellation, progress=context.progress)
        return WorkflowResult(True,
            f"Created Historical Trends from {len(files)} annual TGIACCD file(s). Source files were preserved.", created)
    try:
        first = int(context.parameters["first_fiscal_year"])
        last = int(context.parameters["last_fiscal_year"])
    except (TypeError, ValueError):
        raise ValueError("Enter four-digit fiscal years.") from None
    settings = TrendsExtractSettings(first, last, output.parent / f"{output.stem}_sources")
    if settings.extract_directory.exists():
        raise ValueError("Choose a new output filename with no matching source folder.")
    client = _connect_prod(context)
    with client:
        created = run_sql_trends_pipeline(client, settings, config,
            cancellation=context.cancellation, progress=context.progress)
    return WorkflowResult(True,
        f"Created Historical Trends for FY{first}–FY{last}. Checked annual source CSVs are saved in {settings.extract_directory}. "
        "Balances reflect current replicated balances, not historical year-end snapshots.", created)


def _connect_prod(context: WorkflowContext) -> InsightsClient:
    """Use the established browser auth boundary without logging handoff URLs."""
    context.progress.report("Connecting to PROD Insights — complete browser sign-in if prompted")
    # Authentication failures may contain credential-bearing handoff URLs.
    try:
        profile = load_department_profiles()[WorkflowMode.PRODUCTION.value]
        if profile is None:
            raise ValueError("PROD Insights is not configured.")
        client, _ = build_authenticated_client(profile.settings, browser="chrome",
            experience_url=profile.experience_url, use_saved_mines_login=True)
    except WorkflowCancelled:
        raise
    except Exception:
        raise ValueError("Could not connect to PROD Insights. Check configuration and browser sign-in.") from None
    return client


def run_refresh_detail_codes(context: WorkflowContext) -> WorkflowResult:
    """Admin action to initialize or update the shared classification reference."""
    policy = load_access_configuration(get_shared_gui_access_path())
    if not policy.is_administrator(get_current_login()):
        raise ValueError("Only an administrator can refresh Banner detail codes.")
    if context.mode != WorkflowMode.PRODUCTION:
        raise ValueError("Detail-code refresh requires PROD Insights.")
    output = get_shared_detail_codes_path()
    client = _connect_prod(context)
    with client:
        count = refresh_detail_codes(client, output, progress=context.progress)
    return WorkflowResult(True, f"Refreshed {count:,} Banner detail-code classifications for Historical Trends.", output)
