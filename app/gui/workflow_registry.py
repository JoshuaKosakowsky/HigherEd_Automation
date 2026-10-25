"""Staff-facing workflow metadata and runner registration."""

from __future__ import annotations

from datetime import datetime, date, timedelta
from pathlib import Path

from data_processing.population_testing.config import (
    DEFAULT_INPUT_FILE,
    DEFAULT_OUTPUT_FILE,
    DEFAULT_SAMPLE_FRACTION,
    DEFAULT_STAFF_NAMES,
)

from app.gui.models import ParameterDefinition, ParameterKind, WorkflowDefinition, WorkflowMode
from app.gui.services.canadian_tax import run_canadian_tax
from app.gui.services.graduate_contract_recon import run_graduate_contract_recon
from app.gui.services.wf_mines_balance_recon import run_wf_mines_balance_recon
from app.gui.services.population_testing import run_population_testing
from app.gui.services.refunds import run_refund_review
from app.gui.services.trends import run_trends, run_refresh_detail_codes
from app.gui.services.report_watcher import run_setup_report_watcher
from app.gui.services.textbook_brokers import run_textbook_brokers
from app.gui.services.textbook_recon import run_recon
from shared.banner.term import get_banner_term


PROJECT_ROOT = Path(__file__).resolve().parents[2]


def _current_term_code() -> str:
    return get_banner_term(date.today()).code


def _previous_month_end() -> date:
    return date.today().replace(day=1) - timedelta(days=1)


def _last_completed_fiscal_year() -> str:
    today = date.today()
    return str(today.year - (today.month < 7))


WORKFLOWS: tuple[WorkflowDefinition, ...] = (
    WorkflowDefinition(
        workflow_id="refresh_detail_codes", name="Refresh Banner Detail Codes",
        description="Refresh the shared charge/payment classifications and categories used by Historical Trends directly from Banner. Validates the complete result before replacing the shared reference.",
        category="Accounts Receivable", runner=run_refresh_detail_codes,
        administrator_only=True,
        supported_modes=(WorkflowMode.PRODUCTION,),
        production_warning="Reads Banner detail-code metadata from PROD Insights and updates detail_codes.json beside the shared GUI permissions file. No Banner records are changed. A failed refresh preserves the saved reference.",
    ),
    WorkflowDefinition(
        workflow_id="trends", name="Historical Trends",
        description="Analyze annual TGIACCD uploads or extract Banner activity by fiscal year (July–June Feed Dates) from PROD Insights in checked pages. Creates the existing analysis workbook; SQL runs also keep annual source CSVs. SQL balances are current replicated balances.",
        category="Accounts Receivable", runner=run_trends,
        administrator_only=True, cancellable=True,
        production_warning="Reads all account transactions for the selected fiscal years from PROD Insights and saves annual source files and an analysis workbook. No Banner records are changed. Balances are current, not historical year-end snapshots.",
        parameters=(
            ParameterDefinition(key="banner_file", label="Annual TGIACCD files", kind=ParameterKind.MULTI_INPUT_FILE,
                file_types=(("Annual Excel or CSV files", "*.xlsx *.csv"),),
                help_text="Drop, browse, or paste one file path per line. Use one file per fiscal year named TGIACCD_fy2026.xlsx (or .csv). Uploaded years come from filenames; no hidden SQL year filters apply."),
            ParameterDefinition(key="first_fiscal_year", label="First fiscal year (ending year)", kind=ParameterKind.INTEGER,
                minimum=1900, maximum=9998,
                default_factory=_last_completed_fiscal_year,
                help_text="FY2026 means July 1, 2025 through June 30, 2026. All detail codes and terms in that Feed Date range are included."),
            ParameterDefinition(key="last_fiscal_year", label="Last fiscal year (ending year)", kind=ParameterKind.INTEGER,
                minimum=1900, maximum=9998,
                default_factory=_last_completed_fiscal_year,
                help_text="Defaults to the most recently completed fiscal year. A current or future year can be incomplete."),
            ParameterDefinition(key="output_file", label="Save trends analysis as", kind=ParameterKind.OUTPUT_FILE,
                default_factory=lambda: PROJECT_ROOT / "data" / "statistics" / f"TGIACCD_Fiscal_Year_Analysis_{datetime.now():%Y%m%d_%H%M%S}.xlsx",
                file_types=(("Excel workbook", "*.xlsx"),), default_extension=".xlsx",
                help_text="Choose an existing approved output folder and a new filename. SQL runs also create a matching _sources folder with one checked CSV per fiscal year. Source files and existing results are never overwritten."),
        ),
    ),
    WorkflowDefinition(
        workflow_id="canadian_tax", name="Canadian TL11A Review",
        description="Reconciles tuition paid from Insights, includes scholarships, checks course dates and converts USD to CAD using the published annual rate. Saves a review workbook and audit data.",
        category="Accounts Receivable", runner=run_canadian_tax,
        administrator_only=True, cancellable=True,
        supported_modes=(WorkflowMode.TEST, WorkflowMode.PRODUCTION),
        production_warning="This reads one student's account and enrollment from PROD Insights and saves a review. No Banner records are changed and no certificate is issued.",
        parameters=(
            ParameterDefinition(key="cwid", label="Student CWID", kind=ParameterKind.TEXT,
                                help_text="Enter the student's CWID. It is not included in progress messages."),
            ParameterDefinition(key="tax_year", label="Tax year", kind=ParameterKind.TEXT,
                                default_factory=lambda: str(date.today().year - 1), help_text="Calendar year of the courses, for example 2025."),
            ParameterDefinition(key="output_directory", label="Output location", kind=ParameterKind.TEXT,
                                default=PROJECT_ROOT / "data" / "canadian_tax",
                                help_text="Creates a new timestamped subfolder on each run with tl11a_review.xlsx, source CSVs and manifest.json."),
        ),
    ),
    WorkflowDefinition(
        workflow_id="population_testing",
        name="Student Testing Population",
        description=(
            "Creates testing samples, staff assignments, and TEST/PROD "
            "assignments from the student population workbook."
        ),
        category="Testing",
        runner=run_population_testing,
        parameters=(
            ParameterDefinition(
                key="input_file",
                label="Source workbook",
                kind=ParameterKind.INPUT_FILE,
                default=PROJECT_ROOT / DEFAULT_INPUT_FILE,
                help_text=(
                    "Enter a path, browse, or drop the population workbook here."
                ),
                file_types=(
                    ("Excel workbooks", "*.xlsx *.xlsm"),
                    ("All files", "*.*"),
                ),
                default_extension=".xlsx",
            ),
            ParameterDefinition(
                key="output_file",
                label="Save result as",
                kind=ParameterKind.OUTPUT_FILE,
                default=PROJECT_ROOT / DEFAULT_OUTPUT_FILE,
                help_text="A new formatted workbook will be written here.",
                file_types=(("Excel workbook", "*.xlsx"),),
                default_extension=".xlsx",
            ),
            ParameterDefinition(
                key="sample_percent",
                label="Sample from each standard group (%)",
                kind=ParameterKind.PERCENT,
                default=DEFAULT_SAMPLE_FRACTION * 100,
                help_text="Graduate Online students are always included.",
                minimum=0.01,
                maximum=100,
            ),
            ParameterDefinition(
                key="staff_names",
                label="Staff receiving assignments",
                kind=ParameterKind.NAME_LIST,
                default=DEFAULT_STAFF_NAMES,
                help_text="Enter one unique name per line.",
            ),
        ),
    ),
    WorkflowDefinition(
        workflow_id="refund_review",
        name="Refund Review",
        description=(
            "Calculates a read-only refund review workbook from uploaded Insights "
            "files or direct Insights SQL extraction. It does not "
            "approve or issue refunds."
        ),
        category="Accounts Receivable",
        runner=run_refund_review,
        cancellable=True,
        administrator_only=True,
        production_warning=(
            "Run SQL reads production student account data from PROD Insights "
            "and creates a review workbook. It does not approve or issue refunds."
        ),
        parameters=(
            ParameterDefinition(
                key="target_term",
                label="Banner target term",
                kind=ParameterKind.TEXT,
                default_factory=_current_term_code,
                help_text="Defaults to the current Banner term using the configured term dates.",
            ),
            ParameterDefinition(
                key="transaction_file",
                label="Refund transaction download",
                kind=ParameterKind.INPUT_FILE,
                default=(
                    PROJECT_ROOT
                    / "data"
                    / "refunds"
                    / "input"
                    / "refund_transactions.xlsx"
                ),
                help_text=(
                    "Select the complete XLSX or CSV result downloaded from "
                    "refund_transactions_manual.sql."
                ),
                file_types=(
                    ("Excel and CSV files", "*.xlsx *.csv"),
                    ("All files", "*.*"),
                ),
            ),
            ParameterDefinition(
                key="context_file",
                label="Refund account-context download",
                kind=ParameterKind.INPUT_FILE,
                default=(
                    PROJECT_ROOT
                    / "data"
                    / "refunds"
                    / "input"
                    / "refund_context.xlsx"
                ),
                help_text=(
                    "Select the matching complete XLSX or CSV result downloaded "
                    "from refund_context_manual.sql."
                ),
                file_types=(
                    ("Excel and CSV files", "*.xlsx *.csv"),
                    ("All files", "*.*"),
                ),
            ),
            ParameterDefinition(
                key="output_file",
                label="Save refund review as",
                kind=ParameterKind.OUTPUT_FILE,
                default_factory=lambda: (
                    PROJECT_ROOT
                    / "data"
                    / "refunds"
                    / (
                        f"refund_review_{_current_term_code()}_"
                        f"{datetime.now():%Y%m%d_%H%M%S}.xlsx"
                    )
                ),
                help_text=(
                    "For safety, an existing review workbook will not be overwritten."
                ),
                file_types=(("Excel workbook", "*.xlsx"),),
                default_extension=".xlsx",
            ),
        ),
    ),
    WorkflowDefinition(
        workflow_id="textbook_brokers",
        name="Textbook Brokers",
        description=(
            "Downloads pending Finaid and IA files from the Textbook Brokers SFTP "
            "server and creates a Banner-ready TSPLOAD.csv file in step 1. "
            "After completing TSPLOAD in Banner, use step 2 to confirm successful "
            "transaction loading and archive the pending local and remote files."
        ),
        category="Payments",
        runner=run_textbook_brokers,
        parameters=(
            ParameterDefinition(
                key="term_code",
                label="Banner term",
                kind=ParameterKind.TEXT,
                default_factory=_current_term_code,
                help_text="Defaults to the current Banner term using the configured term dates.",
            ),
        ),
    ),
    WorkflowDefinition(
        workflow_id="setup_report_watcher",
        name="Set Up Report Watcher",
        description=(
            "Windows only. Installs or updates the report filing watcher for your "
            "signed-in Windows account, starts it now, and enables it at sign-in. "
            "Run setup.ps1 first to save your name and initials. Matching Downloads "
            "reports ask for confirmation before filing. Run this on the cashier's "
            "own computer and login, not an administrator's account."
        ),
        category="Cashier Tools",
        runner=run_setup_report_watcher,
    ),
    WorkflowDefinition(
        workflow_id="textbook_recon_manual", name="Textbook Recon",
        description="Match the monthly Brokers workbook to Banner FRST and BOOK charges.",
        category="Accounts Receivable", runner=run_recon,
        production_warning="Run SQL reads production student account transactions from Insights and saves a recon workbook.",
        parameters=(
            ParameterDefinition(
                key="brokers_file", label="Textbook Brokers workbook", kind=ParameterKind.INPUT_FILE,
                file_types=(("Excel workbook", "*.xlsx"),),
                help_text="Select the monthly workbook containing IA Charge Report and FA Charge Report.",
            ),
            ParameterDefinition(
                key="recon_month", label="Feed month (YYYY-MM)", kind=ParameterKind.TEXT,
                default_factory=lambda: _previous_month_end().strftime("%Y-%m"),
                help_text="Reconcile transactions with Feed Dates in this month.",
            ),
            ParameterDefinition(
                key="frst_file", label="FRST extract", kind=ParameterKind.INPUT_FILE,
                required=False, file_types=(("Excel or CSV", "*.xlsx *.csv"),),
                help_text="Leave blank if the month has no FRST transactions.",
            ),
            ParameterDefinition(
                key="book_file", label="BOOK extract", kind=ParameterKind.INPUT_FILE,
                required=False, file_types=(("Excel or CSV", "*.xlsx *.csv"),),
                help_text="Leave blank if the month has no BOOK transactions.",
            ),
            ParameterDefinition(
                key="output_file", label="Save recon as", kind=ParameterKind.OUTPUT_FILE,
                default_factory=lambda: PROJECT_ROOT / "data" / "textbook_brokers" / f"{_previous_month_end():%Y-%m} TBB Recon.xlsx",
                file_types=(("Excel workbook", "*.xlsx"),), default_extension=".xlsx",
                help_text="A new workbook is created. Existing files are never overwritten.",
            ),
        ),
    ),
    WorkflowDefinition(
        workflow_id="wf_mines_balance_recon", name="W&F - Mines Balance Recon",
        description="Collect active CO holds, all-date Banner activity and W&F files. Account Status and Returned Accounts reports are combined on their own tabs; other worksheets stay separate. Matching rules will follow.",
        category="Accounts Receivable", runner=run_wf_mines_balance_recon,
        cancellable=True,
        production_warning="Reads both source reports from PROD Insights. W&F files must still be uploaded. Saves a source review workbook without changing either system.",
        parameters=(
            ParameterDefinition(key="holds_file", label="Active CO holds report", kind=ParameterKind.INPUT_FILE,
                file_types=(("Insights export", "*.csv *.xls *.xlsx *.xlsm"),),
                help_text="Upload the complete Collections tracking report from Insights."),
            ParameterDefinition(key="activity_file", label="WOFF / BDRC transaction report", kind=ParameterKind.INPUT_FILE,
                file_types=(("Insights export", "*.csv *.xls *.xlsx *.xlsm"),),
                help_text="Upload the complete all-date W&F transaction extract. Uploads retain all supplied rows."),
            ParameterDefinition(key="detail_codes", label="Banner detail codes (comma-separated)", kind=ParameterKind.TEXT,
                default="WOFF, BDRC", help_text="Direct query defaults. Editable; all dates, including blank feed dates."),
            ParameterDefinition(key="wf_files", label="Williams and Fudge files", kind=ParameterKind.MULTI_INPUT_FILE,
                file_types=(("CSV or Excel files", "*.csv *.xls *.xlsx *.xlsm"),),
                help_text="Drop CSV, XLS, XLSX or XLSM files together; no manual conversion needed. Names route recognized reports to Collections or Returned tabs; other files stay separate."),
            ParameterDefinition(key="output_file", label="Save source review as", kind=ParameterKind.OUTPUT_FILE,
                default_factory=lambda: PROJECT_ROOT / "data" / f"WF_Mines_Balance_Recon_{datetime.now():%Y%m%d_%H%M%S}.xlsx",
                file_types=(("Excel workbook", "*.xlsx"),), default_extension=".xlsx",
                help_text="Choose a new filename in an approved folder. Source files and existing results are never overwritten."),
        ),
    ),
    WorkflowDefinition(
        workflow_id="graduate_contract_recon", name="1305 Graduate Contract Recon",
        description="Reconcile Workday 1305 activity to Banner feed documents and student detail. Creates a combined activity view and keeps both source exports.",
        category="Accounts Receivable", runner=run_graduate_contract_recon,
        cancellable=True,
        production_warning="Reads Banner activity from PROD Insights. Workday must still be uploaded. Saves a review workbook without changing either system.",
        parameters=(
            ParameterDefinition(key="workday_file", label="Workday 1305 export", kind=ParameterKind.INPUT_FILE,
                file_types=(("Excel or CSV", "*.xlsx *.xlsm *.csv"),),
                help_text="Upload the original Workday report with Accounting Date, Ledger Account, Journal Source, Debit/Credit Amounts and Memo."),
            ParameterDefinition(key="worktag_file", label="Grad Contract Worktag", kind=ParameterKind.INPUT_FILE,
                required=False, file_types=(("Excel or CSV", "*.xlsx *.xlsm *.csv"),),
                help_text="Optional Find Journal Lines export from Workday. Uses Line Memo and Worktags to match student funding worktags by CWID."),
            ParameterDefinition(key="banner_file", label="Banner Insights download", kind=ParameterKind.INPUT_FILE,
                file_types=(("Excel or CSV", "*.xlsx *.xlsm *.csv"),),
                help_text="Upload the complete Banner Activity by Date & Detail Code result for the same scope as Workday. Uploaded data is not narrowed by hidden date or code filters."),
            ParameterDefinition(key="start_date", label="Start date (inclusive)", kind=ParameterKind.DATE,
                default_factory=lambda: _previous_month_end().replace(day=1).isoformat(),
                help_text="Workday Accounting Date and Banner Feed Date are filtered independently to this range."),
            ParameterDefinition(key="end_date", label="End date (inclusive)", kind=ParameterKind.DATE,
                default_factory=lambda: _previous_month_end().isoformat(),
                help_text="Use actual boundaries for a period, quarter, fiscal year, or multiple years."),
            ParameterDefinition(key="detail_codes", label="1305 Banner detail codes (comma-separated)", kind=ParameterKind.TEXT,
                default="TPDT, TPLE, Z0LE",
                help_text="Defaults to TPDT, TPLE and Z0LE for this reconciliation. Add, change or remove codes as needed; at least one code is required."),
            ParameterDefinition(key="output_file", label="Save reconciliation as", kind=ParameterKind.OUTPUT_FILE,
                default_factory=lambda: PROJECT_ROOT / "data" / f"1305_recon_{datetime.now():%Y%m%d_%H%M%S}.xlsx",
                file_types=(("Excel workbook", "*.xlsx"),), default_extension=".xlsx",
                help_text="Choose an existing approved output folder and a new filename. Source files and existing results are never overwritten."),
        ),
    ),
)


def get_workflows() -> tuple[WorkflowDefinition, ...]:
    return WORKFLOWS


def get_workflow(workflow_id: str) -> WorkflowDefinition:
    for workflow in WORKFLOWS:
        if workflow.workflow_id == workflow_id:
            return workflow
    raise KeyError(f"Unknown workflow: {workflow_id}")
