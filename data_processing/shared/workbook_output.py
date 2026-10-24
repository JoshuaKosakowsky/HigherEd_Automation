"""Publish a completed workbook without replacing sources or existing output."""
from __future__ import annotations

import shutil
import tempfile
from pathlib import Path

from openpyxl import Workbook

from shared.cancellation import CancellationToken


def validate_output(path: Path, inputs: tuple[Path, ...] = ()) -> None:
    if path.suffix.lower() != ".xlsx" or not path.is_absolute():
        raise ValueError("Choose an absolute .xlsx output path.")
    if not path.parent.is_dir():
        raise ValueError("The output folder does not exist.")
    if path.exists() or path.resolve() in {source.resolve() for source in inputs}:
        raise ValueError("Output already exists or is a source file. Choose a new filename.")


def save_new_workbook(
    book: Workbook, output: Path, *, cancellation: CancellationToken | None = None,
) -> None:
    validate_output(output)
    with tempfile.TemporaryDirectory(prefix=".review-workbook-", dir=output.parent) as directory:
        staging = Path(directory) / "review.xlsx"
        # Close the OS handle even if the Excel writer fails mid-save on Windows.
        with staging.open('wb') as handle:
            book.save(handle)

        def publish() -> None:
            created = False
            try:
                with output.open("xb") as destination:
                    created = True
                    with staging.open("rb") as source:
                        shutil.copyfileobj(source, destination)
            except Exception:
                # This boundary removes only the incomplete file we created.
                if created:
                    output.unlink(missing_ok=True)
                raise

        if cancellation:
            cancellation.publish(publish)
        else:
            publish()
