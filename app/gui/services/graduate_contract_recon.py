"""Manual staff inputs and admin-only PROD extraction for 1305 reconciliation."""

from __future__ import annotations

from pathlib import Path
from zipfile import BadZipFile

from openpyxl.utils.exceptions import InvalidFileException

from app.gui import APP_VERSION
from app.gui.models import WorkflowContext, WorkflowMode, WorkflowResult
from app.gui.services.access import get_current_login, load_access_configuration
from data_processing.graduate_contract_recon.export import export_reconciliation, validate_output
from data_processing.graduate_contract_recon.reconciliation import reconcile
from data_processing.graduate_contract_recon.sources import SourceData, banner_from_frame, read_source, uploaded_scope
from data_processing.graduate_contract_recon.worktags import prepare_worktags
from shared.cancellation import CancellationToken, WorkflowCancelled
from shared.insights.banner_activity import BannerActivityParameters, extract_banner_activity
from shared.insights.config import load_department_profiles
from shared.insights.query_catalog import get_query
from shared.insights.session_auth import build_authenticated_client
from shared.mines_paths import get_shared_gui_access_path


def _upload_paths(selection: str | Path | tuple[Path, ...] | list[Path] | None) -> tuple[Path, ...]:
    if isinstance(selection, (str, Path)):
        selection = (selection,) if selection else ()
    paths = tuple(Path(path) for path in selection or ())
    if len({path.resolve() for path in paths}) != len(paths):
        raise ValueError("The upload list contains a duplicate file path.")
    return paths


def _read_uploads(
    paths: tuple[Path, ...], source: str, cancellation: CancellationToken | None,
) -> tuple[SourceData, ...]:
    uploads = []
    for path in paths:
        if cancellation:
            cancellation.check()
        try:
            uploads.append(read_source(path, source))
        except (ValueError, OSError, BadZipFile, InvalidFileException) as error:
            raise ValueError(f"Could not read {source} export {path.name}: {error}") from error
    return tuple(uploads)


def run_graduate_contract_recon(context: WorkflowContext) -> WorkflowResult:
    source = context.parameters.get("banner_source")
    if source not in {"manual", "sql"}:
        raise ValueError("Choose an Insights Report option.")
    parameters = BannerActivityParameters.from_inputs(
        context.parameters.get("start_date"), context.parameters.get("end_date"),
        context.parameters.get("detail_codes"),
    ) if source == "sql" else None
    workday_paths = _upload_paths(context.parameters.get("workday_file"))
    if not workday_paths:
        raise ValueError("Upload at least one Trial Balance (1305) transaction-detail export.")
    worktag_paths = _upload_paths(context.parameters.get("worktag_file"))
    output = Path(context.parameters["output_file"])
    banner_path = Path(context.parameters["banner_file"]) if source == "manual" else None
    inputs = workday_paths + worktag_paths
    validate_output(output, inputs + ((banner_path,) if banner_path else ()))
    if context.cancellation:
        context.cancellation.check()
    if source == "sql":
        policy = load_access_configuration(get_shared_gui_access_path())
        if not policy.is_administrator(get_current_login()):
            raise ValueError("Only an administrator can extract 1305 Banner data from PROD Insights.")
        if context.mode != WorkflowMode.PRODUCTION:
            raise ValueError("1305 Banner SQL extraction requires PROD Insights.")
    elif context.mode is not None:
        raise ValueError("File upload reconciliation does not use TEST or PROD.")
    context.progress.report("Reading Trial Balance (1305) exports")
    workday = _read_uploads(workday_paths, "Workday", context.cancellation)
    worktags = None
    if worktag_paths:
        context.progress.report("Reading Find Journal Lines worktag exports")
        worktags = prepare_worktags(*_read_uploads(worktag_paths, "Worktags", context.cancellation))
    if context.cancellation:
        context.cancellation.check()
    if source == "manual":
        context.progress.report("Reading Banner Activity by Date & Detail Code download")
        banner = read_source(banner_path, "Banner")
        parameters = uploaded_scope(workday, banner)
    else:
        context.progress.report("Connecting to PROD Insights — complete browser sign-in if prompted")
        # Preserve the established auth boundary: exception chains can include
        # credential-bearing handoff URLs and must not reach the GUI logger.
        try:
            profile = load_department_profiles()[WorkflowMode.PRODUCTION.value]
            if profile is None:
                raise ValueError("PROD Insights is not configured.")
            client, _ = build_authenticated_client(profile.settings, browser="chrome",
                experience_url=profile.experience_url, use_saved_mines_login=True)
            with client:
                query = get_query("banner_activity")

                class CheckedExecutor:
                    def run_sql(self, sql):
                        if context.cancellation:
                            context.cancellation.check()
                        context.progress.report("Extracting and checking Banner activity")
                        frame = client.run_sql(sql)
                        if context.cancellation:
                            context.cancellation.check()
                        return frame

                frame = extract_banner_activity(CheckedExecutor(), parameters,
                    sql_template=query.sql_path.read_text(encoding="utf-8"))
            banner = banner_from_frame(frame)
        except WorkflowCancelled:
            raise
        except Exception:
            raise ValueError("Banner extraction failed. Check PROD access, selected inputs and API limits. No workbook was saved.") from None
    if context.cancellation:
        context.cancellation.check()
    context.progress.report("Matching feed documents, building student and combined activity views")
    review = reconcile(workday, banner, parameters)
    context.progress.report("Saving reconciliation workbook")
    export_reconciliation(review, output, app_version=APP_VERSION,
        banner_source="PROD Insights (API row-count checked)" if source == "sql" else "Uploaded Insights file (coverage unconfirmed)",
        cancellation=context.cancellation, worktags=worktags)
    return WorkflowResult(True,
        f"Created 1305 reconciliation: {len(review.documents):,} feed groups, {len(review.students):,} student groups, "
        f"{len(review.issues):,} source warnings. "
        + (f"{worktags.warning_count:,} worktag rows need review. " if worktags else "")
        + "Review document differences, period totals and Workday selection statuses before completing the reconciliation.", output)
