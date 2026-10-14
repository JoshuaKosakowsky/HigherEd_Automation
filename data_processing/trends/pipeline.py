from dataclasses import replace
from pathlib import Path
import shutil
from tempfile import TemporaryDirectory
from shared.cancellation import CancellationToken
from shared.progress import ProgressReporter

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
    *,
    files: list[Path] | None = None,
    cancellation: CancellationToken | None = None,
    progress: ProgressReporter | None = None,
) -> Path:
    """
    Run the complete fiscal-year TGIACCD analysis.
    """
    files = files if files is not None else discover_tgiaccd_files(
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
        cancellation=cancellation,
        progress=progress,
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

    if cancellation:
        cancellation.check()
    if progress:
        progress.report("Saving fiscal-year analysis workbook")
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


def run_trends_review(
    config: TrendsConfig, *, files: list[Path],
    cancellation: CancellationToken | None = None,
    progress: ProgressReporter | None = None,
) -> Path:
    """Publish SQL or uploaded analysis with identical cancellation/overwrite guards."""
    output = config.output_file
    if output.suffix.lower() != ".xlsx" or output.exists():
        raise ValueError("Choose a new .xlsx output filename; existing results are never overwritten.")
    if not files:
        raise ValueError("Select at least one annual TGIACCD file.")
    with TemporaryDirectory(prefix="trends-report-", dir=output.parent) as staging:
        staged = Path(staging) / output.name
        run_trends_pipeline(replace(config, output_file=staged), files=files,
                            cancellation=cancellation, progress=progress)

        def publish() -> None:
            # Exclusive creation also protects against another run creating the
            # same destination while extraction is in progress.
            created = False
            try:
                with output.open("xb") as destination:
                    created = True
                    with staged.open("rb") as source:
                        shutil.copyfileobj(source, destination)
            except OSError:
                if created:
                    output.unlink(missing_ok=True)
                raise

        if cancellation:
            cancellation.publish(publish)
        else:
            publish()
    return output
