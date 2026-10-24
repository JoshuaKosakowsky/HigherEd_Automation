"""Read original reports and collect source snapshots without matching accounts."""
from __future__ import annotations

import csv
import re
from copy import copy
from datetime import date, datetime
from pathlib import Path

import pandas as pd
from openpyxl import Workbook, load_workbook

from data_processing.shared.workbook_output import save_new_workbook, validate_output
from data_processing.shared.xlsx_output_format import (
    apply_default_font, format_table_columns, style_header_row,
)
from shared.cancellation import CancellationToken
from shared.insights.report_results import checked_report_result, prepare_excel_dates


HOLD_HEADERS = (
    'CWID', 'First Name', 'Last Name', 'Current Account Balance',
    'Latest Feed Date', 'Hold Code', 'From Date', 'To Date',
)
ACTIVITY_HEADERS = (
    "'ID'", "'Name'", "'Detail Code'", "'Description'", "'Amount'", "'Balance'",
    "'Term'", "'Aid Year'", "'Feed Document'", "'Feed Date'",
    'detail_code_description', 'Transaction User',
)
REPORT_HEADERS = {'holds': HOLD_HEADERS, 'activity': ACTIVITY_HEADERS}


def _header_key(value: object) -> str:
    return str(value or '').strip().strip("'\"").strip().casefold()


def prepare_report(frame: pd.DataFrame, report: str) -> pd.DataFrame:
    """Validate source identity without filtering or reclassifying source rows."""
    headers = [_header_key(value) for value in frame.columns]
    required = {_header_key(value) for value in REPORT_HEADERS[report]}
    if not required.issubset(headers) or len(headers) != len(set(headers)):
        raise ValueError(f'The {report} report is missing required headers or has duplicate headers.')
    if 'Report Row Count' in frame.columns:
        frame = checked_report_result(frame, 'Report Row Count')
    return prepare_excel_dates(frame)


def read_insights_file(path: Path, report: str) -> pd.DataFrame:
    """Locate exactly one source table, allowing the usual report title rows."""
    required = {_header_key(value) for value in REPORT_HEADERS[report]}
    candidates = []

    def inspect(rows) -> None:
        iterator = iter(rows)
        for number, row in enumerate(iterator, 1):
            if number > 30:
                break
            if not required.issubset({_header_key(value) for value in row}):
                continue
            headers = [str(value) if value is not None else '' for value in row]
            records = []
            for values in iterator:
                if not any(value is not None and value != '' for value in values):
                    continue
                if len(values) > len(headers):
                    raise ValueError(f'The {report} source has rows wider than its headers.')
                records.append([*values, *([None] * (len(headers) - len(values)))])
            candidates.append(prepare_report(pd.DataFrame(records, columns=headers), report))
            break

    if path.suffix.lower() == '.csv':
        with path.open(encoding='utf-8-sig', newline='') as source:
            inspect(csv.reader(source))
    elif path.suffix.lower() in {'.xlsx', '.xlsm'}:
        book = load_workbook(path, read_only=True, data_only=False, keep_links=False)
        try:
            for sheet in book:
                sheet.reset_dimensions()
                def rows():
                    for row in sheet:
                        if any(cell.data_type == 'f' for cell in row):
                            raise ValueError('Upload original Insights values, not a workbook with formulas.')
                        yield [cell.value for cell in row]
                inspect(rows())
        finally:
            book.close()
    else:
        raise ValueError('Insights uploads must be XLSX, XLSM, or CSV files.')
    if len(candidates) != 1:
        raise ValueError(f'Upload exactly one matching {report} source table; found {len(candidates)}.')
    return candidates[0]


def _sheet_name(name: str, used: set[str]) -> str:
    base = re.sub(r'[\\/*?:\[\]\x00-\x1f]', '_', name).strip().strip("'") or 'WF Source'
    candidate = base[:31]
    index = 2
    while candidate.casefold() in used:
        suffix = f'_{index}'
        candidate = base[:31 - len(suffix)] + suffix
        index += 1
    used.add(candidate.casefold())
    return candidate


def _write_frame(book: Workbook, name: str, frame: pd.DataFrame, cancellation) -> None:
    if len(frame) + 1 > 1_048_576 or len(frame.columns) > 16_384:
        raise ValueError('A source exceeds Excel worksheet limits. No workbook was saved.')
    sheet = book.create_sheet(name)
    sheet.append(list(frame.columns))
    for number, values in enumerate(frame.itertuples(index=False, name=None), 2):
        if cancellation and number % 500 == 0:
            cancellation.check()
        sheet.append([None if pd.isna(value) else value for value in values])
    for row in sheet:
        for cell in row:
            if isinstance(cell.value, str):
                cell.data_type = 's'
            elif isinstance(cell.value, datetime):
                cell.number_format = 'yyyy-mm-dd hh:mm:ss'
            elif isinstance(cell.value, date):
                cell.number_format = 'yyyy-mm-dd'
    apply_default_font(sheet)
    style_header_row(sheet)
    format_table_columns(sheet, headers=list(frame.columns), currency_headers={
        'Current Account Balance', "'Amount'", "'Balance'",
    })
    for column in sheet.iter_cols(min_row=2):
        if any(isinstance(cell.value, datetime) for cell in column):
            dimension = sheet.column_dimensions[column[0].column_letter]
            dimension.width = max(dimension.width, 24)
    sheet.freeze_panes = 'A2'
    sheet.auto_filter.ref = sheet.dimensions


def create_review_workbook(
    holds: pd.DataFrame, activity: pd.DataFrame, wf_files: tuple[Path, ...], output: Path,
    *, source_labels: tuple[str, str], app_version: str,
    cancellation: CancellationToken | None = None,
) -> int:
    """Create two Insights tabs, every agency worksheet and a source index.

    Agency cells are value snapshots with cell formatting and layout retained.
    Cached formula values prevent broken cross-workbook references; missing
    caches fail explicitly rather than silently turning financial data blank.
    """
    validate_output(output, wf_files)
    book = Workbook()
    book.remove(book.active)
    manifest = []
    used = {'active co holds', 'banner detail codes', 'sources'}
    agency_sheets = 0
    try:
        for name, frame, report, source in (
            ('Active CO Holds', holds, 'holds', source_labels[0]),
            ('Banner Detail Codes', activity, 'activity', source_labels[1]),
        ):
            frame = prepare_report(frame, report)
            _write_frame(book, name, frame, cancellation)
            manifest.append([name, 'Insights', source, 'Report table', len(frame) + 1])
        for path in wf_files:
            if cancellation:
                cancellation.check()
            source = load_workbook(path, data_only=False, keep_links=False)
            cached = None
            try:
                for original in source:
                    name = _sheet_name(f'WF {path.stem} - {original.title}', used)
                    sheet = book.create_sheet(name)
                    if original.max_row > 1_048_576 or original.max_column > 16_384:
                        raise ValueError('A W&F worksheet exceeds Excel limits.')
                    for row in original:
                        if cancellation and row[0].row % 500 == 0:
                            cancellation.check()
                        for cell in row:
                            if cell.value is None and not cell.has_style:
                                continue
                            value = cell.value
                            if cell.data_type == 'f':
                                if cached is None:
                                    cached = load_workbook(path, data_only=True, keep_links=False)
                                value = cached[original.title][cell.coordinate].value
                                if value is None:
                                    raise ValueError(
                                        f'{path.name} / {original.title} has a formula without a saved value. '
                                        'Recalculate and save it in Excel, or upload a values-only copy.'
                                    )
                            target = sheet.cell(cell.row, cell.column, value)
                            if isinstance(value, str):
                                target.data_type = 's'
                            if cell.has_style:
                                target.font, target.fill = copy(cell.font), copy(cell.fill)
                                target.border, target.alignment = copy(cell.border), copy(cell.alignment)
                                target.protection = copy(cell.protection)
                            target.number_format = cell.number_format
                    for key, dimension in original.column_dimensions.items():
                        sheet.column_dimensions[key] = copy(dimension)
                        sheet.column_dimensions[key].parent = sheet
                    for key, dimension in original.row_dimensions.items():
                        sheet.row_dimensions[key] = copy(dimension)
                        sheet.row_dimensions[key].parent = sheet
                    for merged in original.merged_cells.ranges:
                        sheet.merge_cells(str(merged))
                    sheet.freeze_panes = original.freeze_panes
                    sheet.auto_filter.ref = original.auto_filter.ref
                    manifest.append([name, 'Williams and Fudge', path.name, original.title, original.max_row])
                    agency_sheets += 1
            finally:
                source.close()
                if cached is not None:
                    cached.close()
        index = pd.DataFrame(manifest, columns=[
            'Output Tab', 'Source', 'File / Query', 'Original Worksheet', 'Rows Including Headers',
        ])
        _write_frame(book, 'Sources', index, cancellation)
        book.properties.title = 'W&F - Mines Balance Recon: source review'
        book.properties.description = f'App {app_version}. Source snapshots only; no matching or recon conclusions.'
        save_new_workbook(book, output, cancellation=cancellation)
        return agency_sheets
    finally:
        book.close()
