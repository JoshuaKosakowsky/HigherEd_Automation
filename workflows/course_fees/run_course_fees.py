from __future__ import annotations

import argparse
from pathlib import Path

from data_processing.course_fees.pipeline import run_course_fees_pipeline
from data_processing.shared.dates import compute_future_term_code, stamp_yyyymmdd


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Run Course Fees transformation from raw Banner CFL and Course Specific Fees files."
    )

    parser.add_argument(
        "--banner-cfl-file",
        required=False,
        type=Path,
        help="Raw Banner gokoutp CSV file.",
    )

    parser.add_argument(
        "--csf-file",
        required=False,
        type=Path,
        help="Course Specific Fees Excel file.",
    )

    parser.add_argument(
        "--output-dir",
        required=False,
        type=Path,
        help="Output folder for the final Course Fees workbook.",
    )

    parser.add_argument(
        "--write-debug-outputs",
        action="store_true",
        help="Write cleaned intermediate files.",
    )

    return parser.parse_args()


def main() -> int:
    args = parse_args()

    term_code = compute_future_term_code()
    fiscal_year = term_code[2:4]
    run_stamp = stamp_yyyymmdd()

    onedrive_root = Path.home() / "OneDrive - Colorado Community College System"

    course_fees_root = (
        onedrive_root
        / "Accounts Receivable-Bursar - Documents"
        / "Rate Table"
    )

    output_dir = args.output_dir or (course_fees_root / term_code / run_stamp)

    banner_cfl_file = args.banner_cfl_file or (output_dir / f"gokoutp_{run_stamp}.csv")

    csf_file = args.csf_file or (
        course_fees_root
        / "CSF_FY"
        / f"FY{fiscal_year} Course Specific Fees.xlsx"
    )

    third_party_dir = (
        onedrive_root
        / "FRCC Fiscal - 3rd Party"
    )

    output_file = run_course_fees_pipeline(
        banner_cfl_file=banner_cfl_file,
        csf_file=csf_file,
        output_dir=output_dir,
        third_party_dir=third_party_dir,
        write_debug_outputs=args.write_debug_outputs,
    )

    print(f"Course Fees output created: {output_file}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())