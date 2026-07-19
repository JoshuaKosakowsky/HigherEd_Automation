from __future__ import annotations

import re
from collections.abc import Iterator
from pathlib import Path
from xml.etree.ElementTree import iterparse
from zipfile import BadZipFile, ZipFile


XML_NAMESPACE = (
    "{http://schemas.openxmlformats.org/"
    "spreadsheetml/2006/main}"
)

CELL_REFERENCE = re.compile(r"([A-Z]+)")

FISCAL_YEAR_PATTERN = re.compile(
    r"(?:^|[_\- ])fy(?P<year>\d{2}|\d{4})(?:$|[_\-. ])",
    flags=re.IGNORECASE,
)


def clean_tgiaccd_header(value: object) -> str:
    """
    Remove the quote marks added to TGIACCD export headers.
    """
    return (
        str(value or "")
        .strip()
        .strip("'")
        .strip()
    )


def fiscal_year_from_filename(path: Path) -> int:
    """
    Extract a four-digit fiscal year from a TGIACCD filename.

    Examples:
        TGIACCD_fy26.xlsx -> 2026
        TGIACCD_fy2026.xlsx -> 2026
        TGIACCD_fy99.xlsx -> 1999
    """
    match = FISCAL_YEAR_PATTERN.search(
        path.name
    )

    if match is None:
        raise ValueError(
            "Could not determine the fiscal year from "
            f"the filename: {path.name}"
        )

    year_text = match.group("year")

    if len(year_text) == 4:
        return int(year_text)

    two_digit_year = int(year_text)

    if two_digit_year >= 80:
        return 1900 + two_digit_year

    return 2000 + two_digit_year


def _read_shared_strings(
    archive: ZipFile,
) -> list[str]:
    """
    Read the optional Excel shared-string table.
    """
    filename = "xl/sharedStrings.xml"

    if filename not in archive.namelist():
        return []

    strings: list[str] = []

    with archive.open(filename) as source:
        for _, element in iterparse(
            source,
            events=("end",),
        ):
            if element.tag != f"{XML_NAMESPACE}si":
                continue

            text_parts = [
                text_element.text or ""
                for text_element in element.iter(
                    f"{XML_NAMESPACE}t"
                )
            ]

            strings.append(
                "".join(text_parts)
            )

            element.clear()

    return strings


def _read_cell(
    cell,
    *,
    shared_strings: list[str],
) -> object:
    cell_type = cell.attrib.get("t")

    if cell_type == "inlineStr":
        text_parts = [
            text_element.text or ""
            for text_element in cell.iter(
                f"{XML_NAMESPACE}t"
            )
        ]
        return "".join(text_parts)

    value_element = cell.find(
        f"{XML_NAMESPACE}v"
    )

    if (
        value_element is None
        or value_element.text is None
    ):
        return None

    raw_value = value_element.text

    if cell_type == "s":
        return shared_strings[int(raw_value)]

    if cell_type in {"str", "e"}:
        return raw_value

    try:
        return float(raw_value)
    except ValueError:
        return raw_value


def _first_worksheet_name(
    archive: ZipFile,
) -> str:
    worksheets = sorted(
        name
        for name in archive.namelist()
        if (
            name.startswith("xl/worksheets/sheet")
            and name.endswith(".xml")
        )
    )

    if not worksheets:
        raise ValueError(
            "The workbook does not contain a worksheet."
        )

    return worksheets[0]


def iter_tgiaccd_rows(
    path: Path,
    *,
    required_columns: tuple[str, ...],
) -> Iterator[dict[str, object]]:
    """
    Stream selected columns from a TGIACCD workbook.

    The historical exports incorrectly declare their used range as
    A1. Reading the worksheet XML directly avoids that bad dimension
    and prevents the multi-hundred-megabyte sheets from being loaded
    into memory at once.
    """
    if not path.exists():
        raise FileNotFoundError(
            f"TGIACCD workbook not found: {path}"
        )

    try:
        archive = ZipFile(path)
    except BadZipFile as error:
        raise ValueError(
            f"Not a valid Excel workbook: {path}"
        ) from error

    with archive:
        shared_strings = _read_shared_strings(
            archive
        )
        worksheet_name = _first_worksheet_name(
            archive
        )
        header_by_column: dict[str, str] = {}
        required_column_letters: set[str] = set()

        with archive.open(worksheet_name) as source:
            for _, element in iterparse(
                source,
                events=("end",),
            ):
                if element.tag != f"{XML_NAMESPACE}row":
                    continue

                if not header_by_column:
                    for cell in element.findall(
                        f"{XML_NAMESPACE}c"
                    ):
                        match = CELL_REFERENCE.match(
                            cell.attrib["r"]
                        )
                        if match is None:
                            continue

                        column_letter = match.group(1)
                        header_by_column[column_letter] = (
                            clean_tgiaccd_header(
                                _read_cell(
                                    cell,
                                    shared_strings=shared_strings,
                                )
                            )
                        )

                    missing_columns = (
                        set(required_columns)
                        - set(header_by_column.values())
                    )

                    if missing_columns:
                        raise ValueError(
                            f"{path.name} is missing required "
                            f"columns: {sorted(missing_columns)}"
                        )

                    required_column_letters = {
                        column_letter
                        for column_letter, header
                        in header_by_column.items()
                        if header in required_columns
                    }

                    element.clear()
                    continue

                output = {
                    column: None
                    for column in required_columns
                }

                for cell in element.findall(
                    f"{XML_NAMESPACE}c"
                ):
                    match = CELL_REFERENCE.match(
                        cell.attrib["r"]
                    )
                    if match is None:
                        continue

                    column_letter = match.group(1)

                    if (
                        column_letter
                        not in required_column_letters
                    ):
                        continue

                    header = header_by_column[
                        column_letter
                    ]
                    output[header] = _read_cell(
                        cell,
                        shared_strings=shared_strings,
                    )

                element.clear()
                yield output