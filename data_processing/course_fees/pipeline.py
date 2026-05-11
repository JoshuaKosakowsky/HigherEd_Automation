from pathlib import Path

from data_processing.course_fees.clean import (
    clean_banner_course_fee_listing,
    clean_course_specific_fees,
)
from data_processing.course_fees.config import build_course_fee_config
from data_processing.course_fees.export import (
    export_course_fees_workbook,
    write_course_fee_debug_outputs,
)
from data_processing.course_fees.input import (
    read_banner_course_fee_listing,
    read_course_specific_fees,
)
from data_processing.course_fees.matching import build_matched_course_fees
from data_processing.course_fees.removal import build_fees_to_remove
from data_processing.course_fees.transform import (
    add_expected_fee_fields,
    finalize_course_fee_output,
)
from data_processing.shared.dates import compute_future_term_code, stamp_yyyymmdd


def run_course_fees_pipeline(
    *,
    banner_cfl_file: Path,
    csf_file: Path,
    output_dir: Path,
    third_party_dir: Path | None = None,
    write_debug_outputs: bool = False,
) -> Path:
    term_code = compute_future_term_code()
    run_stamp = stamp_yyyymmdd()

    config = build_course_fee_config(
        term_code=term_code,
        output_dir=output_dir,
        third_party_dir=third_party_dir,
        write_debug_outputs=write_debug_outputs,
    )

    banner_raw_df = read_banner_course_fee_listing(banner_cfl_file)
    csf_raw_df = read_course_specific_fees(csf_file)

    banner_clean_df = clean_banner_course_fee_listing(
        banner_raw_df,
        config=config,
    )

    csf_clean_df = clean_course_specific_fees(
        csf_raw_df,
        config=config,
    )

    csf_ready_df = add_expected_fee_fields(
        csf_clean_df,
        config=config,
    )

    matched_df = build_matched_course_fees(
        banner_clean_df,
        csf_ready_df,
        config=config,
    )

    final_df = finalize_course_fee_output(
        matched_df,
        config=config,
    )

    fees_to_remove_df = build_fees_to_remove(
        banner_clean_df,
        csf_ready_df,
    )

    if write_debug_outputs:
        write_course_fee_debug_outputs(
            cfl_df=banner_clean_df,
            csf_df=csf_ready_df,
            config=config,
            run_stamp=run_stamp,
        )

    output_file = export_course_fees_workbook(
        course_fees_df=final_df,
        fees_to_remove_df=fees_to_remove_df,
        config=config,
        run_stamp=run_stamp,
    )

    print(f"Completed Course Fees workbook: {output_file}")

    return output_file