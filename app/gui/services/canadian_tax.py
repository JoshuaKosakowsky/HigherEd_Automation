"""Administrator-only Insights adapter for the shared TL11A review pipeline."""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

from app.gui import APP_VERSION
from app.gui.models import WorkflowContext, WorkflowMode, WorkflowResult
from app.gui.services.access import get_current_login, load_access_configuration
from data_processing.canadian_tax.exchange_rates import fetch_annual_rate
from data_processing.canadian_tax.pipeline import extract_data, prepare_review, review_metadata, write_package
from data_processing.canadian_tax.preparation import QUERY_DIRECTORY, load_rules, validate_inputs
from shared.cancellation import WorkflowCancelled
from shared.insights.config import load_department_profiles
from shared.insights.session_auth import build_authenticated_client
from shared.mines_paths import get_shared_gui_access_path


def run_canadian_tax(context: WorkflowContext) -> WorkflowResult:
    policy = load_access_configuration(get_shared_gui_access_path())
    if not policy.is_administrator(get_current_login()):
        raise ValueError("Only an administrator can run the Canadian TL11A review.")
    if context.cancellation:
        context.cancellation.check()
    cwid = str(context.parameters["cwid"]).strip()
    year_text = str(context.parameters["tax_year"]).strip()
    if len(year_text) != 4 or not year_text.isascii() or not year_text.isdigit():
        raise ValueError("Tax year must be a four-digit year from 2000 through 2099.")
    tax_year = int(year_text)
    validate_inputs(cwid, tax_year)
    if context.mode not in (WorkflowMode.TEST, WorkflowMode.PRODUCTION):
        raise ValueError("Choose TEST or PROD Insights for the Canadian TL11A review.")
    output_text = str(context.parameters["output_directory"]).strip().strip('"')
    if not output_text:
        raise ValueError("Choose an output location for the review package.")
    output_root = Path(output_text).expanduser()
    if output_root.is_file():
        raise ValueError("Output location must be a directory, not a file.")
    output = output_root / f"tl11a_{tax_year}_{datetime.now(timezone.utc):%Y%m%d_%H%M%S_%f}"
    rules = load_rules()
    context.progress.report(f"Connecting to {context.mode.value} Insights — complete browser sign-in if prompted")
    # Authentication/query errors may contain SQL literals or sensitive responses.
    # Keep this adapter's operational exception boundary safe for GUI log files.
    try:
        profile = load_department_profiles()[context.mode.value]
        if profile is None:
            raise ValueError("Selected Insights environment is not configured.")
        client, _ = build_authenticated_client(profile.settings, browser="chrome", experience_url=profile.experience_url)
        with client:
            schema = client.run_sql_file(QUERY_DIRECTORY / "validate_canadian_tax_schema.sql")
            inventory = client.run_sql_file(QUERY_DIRECTORY / "payment_application_inventory.sql")
            if schema.empty or "validation_status" not in schema or schema.validation_status.ne("FOUND").any():
                raise ValueError("Required schema validation failed.")
            frames = {"schema": schema, "payment_application_columns": inventory}
            frames.update(extract_data(client, cwid, tax_year, cancellation=context.cancellation, progress=context.progress))
    except WorkflowCancelled:
        raise
    except Exception:
        raise RuntimeError("TL11A extraction failed. Check Insights access, required schema columns and extract completeness; no output was published.") from None
    if context.cancellation:
        context.cancellation.check()
    context.progress.report("Fetching published annual USD/CAD rate and reconciling payment allocations")
    rate, response = fetch_annual_rate(tax_year)
    manifest = review_metadata(cwid, tax_year, context.mode.value, APP_VERSION, rate, response)
    review = prepare_review(frames, manifest, rules)
    context.progress.report("Saving TL11A review workbook and audit package")
    if context.cancellation:
        context.cancellation.publish(lambda: write_package(output, frames, manifest, review))
    else:
        write_package(output, frames, manifest, review)
    return WorkflowResult(success=True, output_path=output / "tl11a_review.xlsx",
        message="Created TL11A review and source package. " + (
            "USD/CAD amounts reconciled; confirm attendance and degree before certifying."
            if review.paid_cad is not None else "Some amounts are withheld; see the Checks tab for required review."))
