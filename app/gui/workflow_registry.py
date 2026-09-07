"""Staff-facing workflow metadata and runner registration."""

from __future__ import annotations

from pathlib import Path

from data_processing.population_testing.config import (
    DEFAULT_INPUT_FILE,
    DEFAULT_OUTPUT_FILE,
    DEFAULT_SAMPLE_FRACTION,
    DEFAULT_STAFF_NAMES,
)

from app.gui.models import ParameterDefinition, ParameterKind, WorkflowDefinition
from app.gui.services.population_testing import run_population_testing
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
)


def get_workflows() -> tuple[WorkflowDefinition, ...]:
    return WORKFLOWS


def get_workflow(workflow_id: str) -> WorkflowDefinition:
    for workflow in WORKFLOWS:
        if workflow.workflow_id == workflow_id:
            return workflow
    raise KeyError(f"Unknown workflow: {workflow_id}")
