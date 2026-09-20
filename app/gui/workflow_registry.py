"""Staff-facing workflow metadata and runner registration."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

from data_processing.population_testing.config import (
    DEFAULT_INPUT_FILE,
    DEFAULT_OUTPUT_FILE,
    DEFAULT_SAMPLE_FRACTION,
    DEFAULT_STAFF_NAMES,
)

from app.gui.models import ParameterDefinition, ParameterKind, WorkflowDefinition
from app.gui.services.population_testing import run_population_testing
from app.gui.services.refunds import run_refund_review
from app.gui.services.report_watcher import run_setup_report_watcher
from app.gui.services.textbook_brokers import run_textbook_brokers
from shared.banner.term import get_banner_term


PROJECT_ROOT = Path(__file__).resolve().parents[2]
CURRENT_TERM = get_banner_term()


WORKFLOWS: tuple[WorkflowDefinition, ...] = (
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
            "Calculates a read-only refund review workbook from the transaction "
            "and account-context files downloaded from Insights. It does not "
            "approve or issue refunds."
        ),
        category="Accounts Receivable",
        runner=run_refund_review,
        parameters=(
            ParameterDefinition(
                key="target_term",
                label="Banner target term",
                kind=ParameterKind.TEXT,
                default=CURRENT_TERM.code,
                help_text=f"Current term: {CURRENT_TERM.name} ({CURRENT_TERM.code}).",
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
                default=(
                    PROJECT_ROOT
                    / "data"
                    / "refunds"
                    / (
                        f"refund_review_{CURRENT_TERM.code}_"
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
            "Combines selected Finaid and IA files into a new Banner-ready "
            "TSPLOAD.csv file. Source files are not moved or archived."
        ),
        category="Payments",
        runner=run_textbook_brokers,
        parameters=(
            ParameterDefinition(
                key="term_code",
                label="Banner term",
                kind=ParameterKind.TEXT,
                default=CURRENT_TERM.code,
                help_text=f"Current term: {CURRENT_TERM.name} ({CURRENT_TERM.code}).",
            ),
            ParameterDefinition(
                key="source_files",
                label="Finaid and IA source files",
                kind=ParameterKind.MULTI_INPUT_FILE,
                help_text=(
                    "Enter one path per line, browse for files, or drop one or "
                    "more finaid_*.csv / ia_*.csv files here."
                ),
                file_types=(
                    ("Textbook Brokers CSV files", "*.csv"),
                    ("All files", "*.*"),
                ),
            ),
            ParameterDefinition(
                key="output_file",
                label="Save result as",
                kind=ParameterKind.OUTPUT_FILE,
                default=(
                    PROJECT_ROOT
                    / "data"
                    / "textbook_brokers"
                    / "output"
                    / "TSPLOAD.csv"
                ),
                help_text=(
                    "For safety, an existing output file will not be overwritten."
                ),
                file_types=(("CSV file", "*.csv"),),
                default_extension=".csv",
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
)


def get_workflows() -> tuple[WorkflowDefinition, ...]:
    return WORKFLOWS


def get_workflow(workflow_id: str) -> WorkflowDefinition:
    for workflow in WORKFLOWS:
        if workflow.workflow_id == workflow_id:
            return workflow
    raise KeyError(f"Unknown workflow: {workflow_id}")
