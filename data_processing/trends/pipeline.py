from pathlib import Path

from .analysis import (
    analyze_all_files,
    build_reporting_group_totals,
)
from .config import TrendsConfig
from .export import export_trends_workbook
from .ingest import (
    discover_tgiaccd_files,
    read_detail_codes,
)


def run_trends_pipeline(
    config: TrendsConfig,
) -> Path:
    """
    Run the complete fiscal-year TGIACCD analysis.
    """
    files = discover_tgiaccd_files(
        config.input_dir,
        file_pattern=config.file_pattern,
    )

    detail_codes = read_detail_codes(
        config.detail_codes_file
    )

    (
        fiscal_year_results,
        detail_code_results,
        group_average_results,
        category_average_results,
        term_group_total_results,
        term_collection_total_results,
    ) = analyze_all_files(
        files,
        detail_codes=detail_codes,
        config=config,
    )

    reporting_group_total_results = (
        build_reporting_group_totals(
            fiscal_year_results=(
                fiscal_year_results
            ),
            detail_code_results=(
                detail_code_results
            ),
            group_average_results=(
                group_average_results
            ),
        )
    )

    return export_trends_workbook(
        fiscal_year_results=(
            fiscal_year_results
        ),
        detail_code_results=(
            detail_code_results
        ),
        group_average_results=(
            group_average_results
        ),
        reporting_group_total_results=(
            reporting_group_total_results
        ),
        category_average_results=(
            category_average_results
        ),
        term_group_total_results=(
            term_group_total_results
        ),
        term_collection_total_results=(
            term_collection_total_results
        ),
        output_file=config.output_file,
    )