"""R1 upload orchestration; source systems are never changed."""

from __future__ import annotations

from pathlib import Path

from app.gui import APP_VERSION
from app.gui.models import WorkflowContext, WorkflowResult
from data_processing.csmf_loans.balances import (
    BalanceSelection, BalanceStore, file_digest, prepare_opening_balances,
)
from data_processing.csmf_loans.export import build_workbook
from data_processing.csmf_loans.sources import prepare_activity, read_journal, validate_fiscal_year
from data_processing.shared.workbook_output import save_new_workbook, validate_output


def run_csmf_loans(context: WorkflowContext) -> WorkflowResult:
    if context.mode is not None:
        raise ValueError("CSMF uploads do not use TEST or PROD.")
    year = validate_fiscal_year(context.parameters["fiscal_year"])
    journal_path = Path(context.parameters["journal_file"])
    trial_path = Path(context.parameters["trial_balance_file"]) if context.parameters.get("trial_balance_file") else None
    output = Path(context.parameters["output_file"])
    validate_output(output, (journal_path, *((trial_path,) if trial_path else ())))
    if context.cancellation:
        context.cancellation.check()
    selection = context.parameters.get("_opening_balances")
    if selection is None:
        selection = prepare_opening_balances(year, trial_path)
    if not isinstance(selection, BalanceSelection) or selection.balances.fiscal_year != year:
        raise ValueError("Review opening balances for the selected fiscal year before running.")
    if selection.trial_path != (trial_path.resolve() if trial_path else None):
        raise ValueError("Trial Balance selection changed after preview. Review the balances again.")
    if trial_path and file_digest(trial_path) != selection.balances.source_digest:
        raise ValueError("Trial Balance changed after preview. Review the new balances before running.")
    context.progress.report("Reading and grouping CSMF journal activity")
    journal = read_journal(journal_path)
    activity = prepare_activity(journal, year)
    context.progress.report("Building loan worksheets")
    book = build_workbook(activity, selection.balances, app_version=APP_VERSION,
                          trial_source=selection.trial_source, cancellation=context.cancellation)
    store = BalanceStore(year)

    def publish() -> None:
        with store.locked(selection.expected_digest):
            if trial_path and file_digest(trial_path) != selection.balances.source_digest:
                raise ValueError("Trial Balance changed after preview. Review the balances again.")
            save_new_workbook(book, output)
            try:
                if trial_path:
                    store.save_locked(selection.balances)
            except Exception:
                # Only this run's newly published file is removed. An unsuccessful
                # cache replacement must not leave a workbook claiming it succeeded.
                output.unlink(missing_ok=True)
                raise

    context.progress.report("Saving workbook and FY opening balances")
    try:
        if context.cancellation:
            context.cancellation.publish(publish)
        else:
            publish()
    finally:
        book.close()
    unclassified_count = sum(row.section == "1621" for row in activity.rows)
    return WorkflowResult(True,
        f"Created CSMF R1 workbook with {len(activity.rows):,} activity rows. "
        + (f"{activity.other_account_count:,} rows use unmapped ledger accounts; review Other ledger activity. "
           if activity.other_account_count else "")
        + (f"{unclassified_count:,} 1621 rows have unclassified sources; review 1621 — Unclassified. "
           if unclassified_count else "")
        + "Current FY Recon summarizes all uploaded FY activity; Current Month Recon shows the latest uploaded month. "
        + "AP and AR carry forward within the FY. AP clearing and variance remain pending.", output)
