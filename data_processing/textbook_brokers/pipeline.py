"""Reusable Textbook Brokers to Banner TSPLOAD transformation pipeline."""

from __future__ import annotations

import csv
import io
import re
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Iterable


TSPLOAD_HEADER = [
    "Student ID",
    "Detail Code",
    "Term Code",
    "Source Code",
    " Amount ",
    "Entry Date",
    "Effective Date",
    "User ID",
    "Transaction Date",
    "Description",
    "Pay Number",
    "Document Number",
]

SOURCE_COLUMN_COUNT = 6
TERM_CODE_PATTERN = re.compile(r"^\d{6}$")
SOURCE_FILE_PATTERN = re.compile(r"^(finaid|ia)_.+\.csv$", re.IGNORECASE)


class TransformationError(RuntimeError):
    """Raised when source data cannot be transformed safely."""


@dataclass(frozen=True)
class SourceSummary:
    """Processing result for one Finaid or IA source file."""

    source_type: str
    path: Path
    row_count: int


@dataclass(frozen=True)
class TransformationResult:
    """Summary of a completed TSPLOAD transformation."""

    output_path: Path
    source_summaries: tuple[SourceSummary, ...]
    total_rows: int


def _read_csv_rows(path: Path) -> list[list[str]]:
    if not path.is_file():
        raise TransformationError(f"File was not found: {path}")

    try:
        with path.open("r", encoding="utf-8-sig", newline="") as handle:
            return list(csv.reader(handle))
    except UnicodeDecodeError as exc:
        raise TransformationError(
            f"File is not valid UTF-8 text: {path}"
        ) from exc
    except csv.Error as exc:
        raise TransformationError(f"Invalid CSV file {path}: {exc}") from exc

def _validate_source_paths(source_paths: Iterable[Path]) -> list[Path]:
    unique_paths: list[Path] = []
    seen: set[Path] = set()

    for supplied_path in source_paths:
        source_path = Path(supplied_path)
        resolved_path = source_path.resolve()

        if resolved_path in seen:
            raise TransformationError(
                f"Source file was supplied more than once: {source_path}"
            )

        if not SOURCE_FILE_PATTERN.match(source_path.name):
            raise TransformationError(
                "Source filename must match finaid_*.csv or ia_*.csv: "
                f"{source_path.name}"
            )

        seen.add(resolved_path)
        unique_paths.append(source_path)

    if not unique_paths:
        raise TransformationError("No source files were supplied.")

    return unique_paths


def _get_source_type(source_path: Path) -> str:
    return "Finaid" if source_path.name.lower().startswith("finaid_") else "IA"


def _transform_source(
    source_path: Path,
    term_code: str,
) -> tuple[list[list[str]], SourceSummary]:
    source_rows = _read_csv_rows(source_path)

    if not source_rows:
        raise TransformationError(f"Source file is empty: {source_path}")

    output_rows: list[list[str]] = []

    # Textbook Brokers source files do not contain a header row.
    for row_number, source_row in enumerate(source_rows, start=1):
        if len(source_row) != SOURCE_COLUMN_COUNT:
            raise TransformationError(
                f"{source_path.name} row {row_number} has "
                f"{len(source_row)} columns; expected {SOURCE_COLUMN_COUNT}."
            )

        student_id = source_row[2].strip()
        detail_code = source_row[3].strip()
        amount = source_row[5].strip()

        if not student_id:
            raise TransformationError(
                f"{source_path.name} row {row_number} has a blank Student ID."
            )

        if not detail_code:
            raise TransformationError(
                f"{source_path.name} row {row_number} has a blank Detail Code."
            )

        if not amount:
            raise TransformationError(
                f"{source_path.name} row {row_number} has a blank Amount."
            )

        try:
            Decimal(amount)
        except InvalidOperation as exc:
            raise TransformationError(
                f"{source_path.name} row {row_number} has an invalid "
                f"Amount: {amount!r}."
            ) from exc

        output_rows.append(
            [
                student_id,
                detail_code,
                term_code,
                "T",
                amount,
                "",
                "",
                "",
                "",
                "",
                "",
                "",
            ]
        )

    summary = SourceSummary(
        source_type=_get_source_type(source_path),
        path=source_path,
        row_count=len(output_rows),
    )
    return output_rows, summary


def _serialize_output(header: list[str], rows: list[list[str]]) -> bytes:
    buffer = io.StringIO(newline="")
    writer = csv.writer(buffer, lineterminator="\r\n")
    writer.writerow(header)
    writer.writerows(rows)
    return buffer.getvalue().encode("utf-8")


def _write_new_output(output_path: Path, content: bytes) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_created = False

    try:
        with output_path.open("xb") as handle:
            output_created = True
            handle.write(content)
    except FileExistsError as exc:
        raise TransformationError(
            "Output file already exists and was not overwritten: "
            f"{output_path}"
        ) from exc
    except OSError as exc:
        if output_created and output_path.exists():
            output_path.unlink()
        raise TransformationError(
            f"Unable to write output file {output_path}: {exc}"
        ) from exc


def run_transformation(
    *,
    term_code: str,
    output_path: Path,
    source_paths: Iterable[Path],
) -> TransformationResult:
    """Validate and combine Finaid/IA sources into a new TSPLOAD CSV."""

    if not TERM_CODE_PATTERN.fullmatch(term_code):
        raise TransformationError(
            f"Banner term code must contain exactly six digits: {term_code!r}"
        )

    output_path = Path(output_path)
    validated_sources = _validate_source_paths(source_paths)

    combined_rows: list[list[str]] = []
    source_summaries: list[SourceSummary] = []

    for source_path in validated_sources:
        transformed_rows, summary = _transform_source(
            source_path,
            term_code,
        )

        combined_rows.extend(transformed_rows)
        source_summaries.append(summary)

    if not combined_rows:
        raise TransformationError(
            "No source rows were available for transformation."
        )

    output_content = _serialize_output(
        TSPLOAD_HEADER,
        combined_rows,
    )

    _write_new_output(
        output_path,
        output_content,
    )

    return TransformationResult(
        output_path=output_path,
        source_summaries=tuple(source_summaries),
        total_rows=len(combined_rows),
    )