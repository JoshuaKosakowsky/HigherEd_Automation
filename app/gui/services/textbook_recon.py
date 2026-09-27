"""GUI adapters for manual and Insights-backed textbook reconciliation."""

from __future__ import annotations

import tempfile
from datetime import date
from pathlib import Path

import pandas as pd

from app.gui.models import WorkflowContext, WorkflowMode, WorkflowResult
from app.gui.services.access import get_current_login, load_access_configuration
from data_processing.textbook_brokers.recon import BANNER_HEADERS, MONTH_PATTERN, build_recon
from shared.insights.config import load_department_profiles
from shared.insights.session_auth import build_authenticated_client
from shared.mines_paths import get_shared_gui_access_path


PROJECT_ROOT = Path(__file__).resolve().parents[3]
SQL_PATH = PROJECT_ROOT / "query/AR/textbook_brokers/recon_transactions.sql"
FIELD_NAMES = {
    "'Detail Code'": "tbraccd_detail_code",
    "'Description'": "tbbdetc_desc",
    "'Amount'": "tbraccd_amount",
    "'Balance'": "tbraccd_balance",
    "'Term'": "tbraccd_term_code",
    "'Aid Year'": "tbraccd_aidy_code",
    "'Period'": "tbraccd_period",
    "'Transaction Number'": "tbraccd_tran_number",
    "'Transaction Number Paid'": "tbraccd_tran_number_paid",
    "'Receipt'": "tbraccd_receipt_number",
    "'Source Code'": "tbraccd_srce_code",
    "'Cashier User ID'": "tbraccd_cashier_user_id",
    "'Cashier Session'": "tbraccd_cashier_session",
    "'Cashier End Date'": "tbraccd_cashier_end_date",
    "'Course Reference Number'": "tbraccd_crn",
    "'Cross Reference ID'": "tbraccd_xref_pidm",
    "'Cross Reference Source'": "tbraccd_xref_srce",
    "'Cross Reference Number'": "tbraccd_xref_num",
    "'Contract Payment'": "tbraccd_contract_pidm",
    "'Feed Indicator'": "tbraccd_feed_ind",
    "'Feed Document'": "tbraccd_feed_doc",
    "'Feed Date'": "tbraccd_feed_date",
    "'Invoice Number'": "tbraccd_invoice_num",
    "'Invoice Number Paid'": "tbraccd_invoice_paid",
    "'Invoice Statement Date'": "tbraccd_invoice_statement_date",
    "'Effective Date'": "tbraccd_effective_date",
    "'Bill Date'": "tbraccd_bill_date",
    "'Due Date'": "tbraccd_due_date",
    "'Activity Date'": "tbraccd_activity_date",
}
MANUAL_SOURCE = "manual"
SQL_SOURCE = "sql"


def _month_bounds(text: str) -> tuple[date, date]:
    if not MONTH_PATTERN.fullmatch(text):
        raise ValueError("Recon month must be YYYY-MM.")
    year, month = map(int, text.split("-"))
    start = date(year, month, 1)
    end = date(year + (month == 12), month % 12 + 1, 1)
    return start, end


def _render_sql(month: str, batch: int | None = None) -> str:
    start, end = _month_bounds(month)
    template = SQL_PATH.read_text(encoding="utf-8")
    if batch is not None and not 0 <= batch < 32:
        raise ValueError("Invalid Insights extraction batch.")
    batch_filter = "TRUE" if batch is None else f"MOD(t.tbraccd_pidm, 32) = {batch}"
    return (template.replace("__START_DATE__", start.isoformat())
            .replace("__END_DATE__", end.isoformat())
            .replace("__BATCH_FILTER__", batch_filter))


def _run_complete_query(client, month: str) -> pd.DataFrame:
    initial = client.run_sql(_render_sql(month))
    if initial.empty:
        return initial
    if "extract_row_count" not in initial:
        raise ValueError("Insights result lacks the row-count guard.")
    expected = int(initial["extract_row_count"].iloc[0])
    if len(initial) == expected:
        return initial
    batches = []
    for index in range(32):
        part = client.run_sql(_render_sql(month, index))
        if not part.empty:
            if "extract_row_count" not in part or len(part) != int(part["extract_row_count"].iloc[0]):
                raise ValueError(f"Insights truncated recon batch {index + 1}. The workbook was not created.")
        batches.append(part)
    combined = pd.concat(batches, ignore_index=True)
    if len(combined) != expected:
        raise ValueError("Insights batch totals differ from the complete query count. The workbook was not created.")
    return combined


def _normalized_banner(frame: pd.DataFrame, code: str) -> pd.DataFrame:
    if "tbraccd_detail_code" not in frame or "tbraccd_amount" not in frame:
        raise ValueError("Insights result lacks TBRACCD detail code or amount.")
    selected = frame.loc[frame["tbraccd_detail_code"] == code].copy()
    result = pd.DataFrame(index=selected.index)
    for header in BANNER_HEADERS:
        source = FIELD_NAMES.get(header, header)
        result[header] = selected[source] if source in selected else None
    # Preserve all underlying transaction columns, even if a local TGIACCD
    # display header has no exact equivalent in the Insights table.
    for column in selected:
        if column not in {"extract_row_count", "'ID'", "'Name'"}:
            result[column] = selected[column]
    return result


def _common(context: WorkflowContext) -> tuple[Path, Path]:
    brokers = Path(context.parameters["brokers_file"])
    output = Path(context.parameters["output_file"])
    if output.suffix.casefold() != ".xlsx":
        raise ValueError("Output must be an .xlsx workbook.")
    return brokers, output


def run_manual_recon(context: WorkflowContext) -> WorkflowResult:
    brokers, output = _common(context)
    month = str(context.parameters["recon_month"])
    frst = context.parameters.get("frst_file")
    book = context.parameters.get("book_file")
    counts = build_recon(
        brokers=brokers,
        frst=Path(frst) if frst else None,
        book=Path(book) if book else None, output=output, month=month,
    )
    return WorkflowResult(True, f"Created IA and FA recon tabs from manual extracts ({counts['IA']} IA and {counts['FA']} FA student IDs). Open in Excel to refresh the PivotTables.", output)


def run_sql_recon(context: WorkflowContext) -> WorkflowResult:
    policy = load_access_configuration(get_shared_gui_access_path())
    if not policy.is_administrator(get_current_login()):
        raise ValueError("Only an administrator can run the Insights recon query.")
    if context.mode != WorkflowMode.PRODUCTION:
        raise ValueError("Textbook Recon SQL requires the PROD Insights database.")
    brokers, output = _common(context)
    if output.exists():
        raise ValueError("Output already exists. Choose a new filename.")
    month = str(context.parameters["recon_month"])
    profile = load_department_profiles()[WorkflowMode.PRODUCTION.value]
    if profile is None:
        raise ValueError("Insights PROD is not configured.")
    client, _ = build_authenticated_client(profile.settings, browser="chrome")
    with client:
        frame = _run_complete_query(client, month)
    with tempfile.TemporaryDirectory(prefix="tbb-recon-") as directory:
        inputs = {}
        for code in ("FRST", "BOOK"):
            path = Path(directory) / f"{code}.xlsx"
            _normalized_banner(frame, code).to_excel(path, index=False)
            inputs[code] = path
        counts = build_recon(brokers=brokers, frst=inputs["FRST"], book=inputs["BOOK"], output=output, month=month)
    return WorkflowResult(True, f"Created {month} recon from Insights ({counts['IA']} IA and {counts['FA']} FA student IDs). Open in Excel to refresh the PivotTables.", output)


def run_recon(context: WorkflowContext) -> WorkflowResult:
    """Dispatch the single GUI workflow after validating its Banner source."""
    source = context.parameters.get("banner_source")
    if source == MANUAL_SOURCE:
        return run_manual_recon(context)
    if source == SQL_SOURCE:
        return run_sql_recon(context)
    raise ValueError("Choose how to get the Banner FRST and BOOK transactions.")
