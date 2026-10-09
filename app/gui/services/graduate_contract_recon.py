"""Manual staff inputs and admin-only PROD extraction for 1305 reconciliation."""

from __future__ import annotations

from pathlib import Path

from app.gui import APP_VERSION
from app.gui.models import WorkflowContext, WorkflowMode, WorkflowResult
from app.gui.services.access import get_current_login, load_access_configuration
from data_processing.graduate_contract_recon.export import export_reconciliation, validate_output
from data_processing.graduate_contract_recon.reconciliation import reconcile
from data_processing.graduate_contract_recon.sources import banner_from_frame, read_source
from shared.cancellation import WorkflowCancelled
from shared.insights.banner_activity import BannerActivityParameters, extract_banner_activity
from shared.insights.config import load_department_profiles
from shared.insights.query_catalog import get_query
from shared.insights.session_auth import build_authenticated_client
from shared.mines_paths import get_shared_gui_access_path


def run_graduate_contract_recon(context: WorkflowContext) -> WorkflowResult:
    source = context.parameters.get("banner_source")
    if source not in {"manual", "sql"}:
        raise ValueError("Choose the Banner data source.")
    parameters = BannerActivityParameters.from_inputs(
        context.parameters.get("start_date"), context.parameters.get("end_date"),
        context.parameters.get("detail_codes"),
    )
    workday_path = Path(context.parameters["workday_file"])
    output = Path(context.parameters["output_file"])
    banner_path = Path(context.parameters["banner_file"]) if source == "manual" else None
    validate_output(output, (workday_path,) + ((banner_path,) if banner_path else ()))
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
    context.progress.report("Reading Workday source export")
    workday = read_source(workday_path, "Workday")
    if source == "manual":
        context.progress.report("Reading Banner Insights download")
        banner = read_source(banner_path, "Banner")
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
        cancellation=context.cancellation)
    return WorkflowResult(True,
        f"Created 1305 reconciliation: {len(review.documents):,} feed groups, {len(review.students):,} student groups, "
        f"{len(review.issues):,} source warnings. Review Verification and Exceptions before completing the reconciliation.", output)
