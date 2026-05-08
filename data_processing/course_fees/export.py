from pathlib import Path

import pandas as pd

from data_processing.course_fees.config import CourseFeeRunConfig
from data_processing.shared.files import ensure_dir


def write_course_fee_debug_outputs(
    *,
    cfl_df: pd.DataFrame,
    csf_df: pd.DataFrame,
    config: CourseFeeRunConfig,
    run_stamp: str,
) -> None:
    ensure_dir(config.output_dir)

    cfl_file = config.output_dir / f"Cleaned_CFL_{run_stamp}.xlsx"
    csf_file = config.output_dir / f"FY{config.fiscal_year} Cleaned Course Specific Fees_{run_stamp}.xlsx"

    cfl_df.to_excel(cfl_file, index=False)
    csf_df.to_excel(csf_file, index=False)


def export_course_fees_workbook(
    *,
    course_fees_df: pd.DataFrame,
    fees_to_remove_df: pd.DataFrame,
    config: CourseFeeRunConfig,
    run_stamp: str,
) -> Path:
    ensure_dir(config.output_dir)

    output_file = config.output_dir / f"{config.term_code} Course Fees_{run_stamp}.xlsx"

    with pd.ExcelWriter(output_file, engine="openpyxl") as writer:
        course_fees_df.to_excel(writer, sheet_name="Course Fees", index=False)
        fees_to_remove_df.to_excel(writer, sheet_name="Fee Removal", index=False)

    return output_file