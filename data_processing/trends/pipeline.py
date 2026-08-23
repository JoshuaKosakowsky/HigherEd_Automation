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

    analysis_result = analyze_all_files(
        files,
        detail_codes=detail_codes,
        config=config,
    )

    reporting_group_total_results = (
        build_reporting_group_totals(
            fiscal_year_results=(
                analysis_result.fiscal_years
            ),
            detail_code_results=(
                analysis_result.detail_codes
            ),
            group_average_results=(
                analysis_result.group_averages
            ),
        )
    )

    return export_trends_workbook(
        fiscal_year_results=(
            analysis_result.fiscal_years
        ),
        detail_code_results=(
            analysis_result.detail_codes
        ),
        group_average_results=(
            analysis_result.group_averages
        ),
        reporting_group_total_results=(
            reporting_group_total_results
        ),
        category_average_results=(
            analysis_result.category_averages
        ),
        term_group_total_results=(
            analysis_result.term_groups
        ),
        term_collection_total_results=(
            analysis_result.term_collections
        ),
        output_file=config.output_file,
    )
