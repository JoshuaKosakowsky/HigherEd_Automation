"""CSMF-specific project selection and source-value activity (no netting)."""

from __future__ import annotations

import re
from csv import Error as CsvError
from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from pathlib import Path
from zipfile import BadZipFile

from openpyxl.utils.exceptions import InvalidFileException

from data_processing.shared.source_exports import (
    ZERO, SourceData, fiscal_scope, money, parse_date, read_source_table, text,
)


LOANS = {
    "694511": "Parsons", "694512": "Combined", "694513": "CSM Board",
    "694514": "Welch", "694516": "Bruce", "694518": "Lewis", "694521": "Pearson",
}
SECTIONS = {
    "payment": "Payment", "loan_activity": "Loan Activity",
    "1621": "1621 — Unclassified", "payables": "Payables (2100/2402)",
    "2881": "Payables (2881)", "1382": "AR",
    "5909R": "Interest on loans", "8309R": "Late fees on loans",
}
IGNORED_ACCOUNTS = frozenset({"1021", "1036"})
JOURNAL_ALIASES = {
    "project": ("Project",), "ledger": ("Ledger Account",), "journal": ("Journal Number",),
    "date": ("Accounting Date",), "source": ("Source", "Journal Source"),
    "memo": ("Line Memo",), "debit": ("Ledger Debit Amount",), "credit": ("Ledger Credit Amount",),
}
BALANCE_ALIASES = {
    "worktags": ("Worktags",), "debit": ("Debit Amount",), "date": ("Accounting Date",),
}


def validate_fiscal_year(value: object) -> int:
    if isinstance(value, bool) or not re.fullmatch(r"[0-9]{4}", str(value)):
        raise ValueError("Choose a four-digit fiscal ending year.")
    year = int(value)
    if not 1900 <= year <= 9998:
        raise ValueError("Fiscal ending year must be between 1900 and 9998.")
    return year


def project_number(value: object, *, worktags: bool = False) -> str:
    """Match a Project token, never an unrelated Fund/Grant tag or name number."""
    value = text(value)
    matches = re.findall(r"(?<![\w])Project\s*:\s*(\d{6})(?!\d)", value, flags=re.I)
    if len(matches) > 1:
        raise ValueError("More than one Project tag is present.")
    if matches:
        return matches[0]
    if not worktags:
        match = re.match(r"^(\d{6})(?=\s|:|$)", value)
        if match:
            return match[1]
    return ""


def read_journal(path: Path) -> SourceData:
    return read_source_table(path, "Find Journal Lines - GA",
                             JOURNAL_ALIASES | {"status": ("Status",)}, tuple(JOURNAL_ALIASES))


def read_trial_balance(path: Path) -> SourceData:
    try:
        return read_source_table(path, "Trial Balance", BALANCE_ALIASES, ("worktags", "debit"))
    except (BadZipFile, InvalidFileException, KeyError, SyntaxError, CsvError):
        # Trial Balance is read before execution to show the values. Report a
        # damaged export in that form instead of losing the review to a Qt error.
        raise ValueError("Trial Balance could not be read. Upload an intact XLSX, XLSM, or CSV export.") from None


def opening_values(source: SourceData) -> tuple[tuple[str, Decimal | None], ...]:
    """Return only uploaded projects; a blank amount is distinct from omission."""
    values: dict[str, Decimal | None] = {}
    for number, row in source.rows:
        try:
            project = project_number(source.value(row, "worktags"), worktags=True)
        except ValueError as error:
            raise ValueError(f"Trial Balance row {number}: {error}") from None
        if project not in LOANS:
            source.dispositions[number] = "Not a configured loan project"
            continue
        if project in values:
            raise ValueError(f"Trial Balance has duplicate rows for Project {project}; balances were not saved.")
        try:
            amount = source.value(row, "debit")
            values[project] = None if text(amount).casefold() in {"", "null"} else money(amount)
        except ValueError:
            raise ValueError(f"Trial Balance row {number}: invalid Debit Amount for Project {project}.") from None
        source.dispositions[number] = "Opening balance" if values[project] is not None else "Blank opening balance"
    if not values:
        raise ValueError("Trial Balance contains no configured loan projects. Include at least one loan row to update.")
    return tuple((project, values[project]) for project in LOANS if project in values)


@dataclass(frozen=True)
class Activity:
    project: str
    account: str
    section: str
    journal: str
    day: date
    source: str
    description: str
    amount: Decimal
    direction: str
    source_row: int
    prior_year_activity: bool = False
    status: str = ""

    @property
    def label(self) -> str:
        if self.section == "loan_activity":
            return "Loan Disbursement" if self.direction == "Debit" else "Loan Reversal"
        if self.section == "payables":
            return f"Payables — {self.account}"
        if self.section == "other":
            return f"Other — {self.account}"
        return SECTIONS[self.section]

    @property
    def adjusted_amount(self) -> Decimal:
        # The source column determines the sign, including unclassified and
        # footnoted activity. Keep the original amount intact for review.
        if self.direction == "Debit":
            return -self.amount
        return self.amount


@dataclass(frozen=True)
class LoanActivity:
    fiscal_year: int
    rows: tuple[Activity, ...]
    source: SourceData
    periods: tuple[str, ...]
    other_account_count: int


def prepare_activity(source: SourceData, fiscal_year: int) -> LoanActivity:
    """Use every uploaded period in this FY; never reconstruct from old output."""
    fiscal_year = validate_fiscal_year(fiscal_year)
    rows = []
    periods = set()
    other_count = 0
    for number, row in source.rows:
        if not any(text(value) for value in row):
            source.dispositions[number] = "Blank row"
            continue
        try:
            project = project_number(source.value(row, "project"))
        except ValueError as error:
            raise ValueError(f"Journal row {number}: {error}") from None
        if project not in LOANS:
            source.dispositions[number] = "Not a configured loan project"
            continue
        account = re.match(r"^(\d{4}R?)(?=\s|:|$)", text(source.value(row, "ledger")), re.I)
        if not account:
            raise ValueError(f"Journal row {number}: missing or invalid Ledger Account.")
        account = account[1].upper()
        if account in IGNORED_ACCOUNTS:
            source.dispositions[number] = "Excluded ledger account " + account
            continue
        try:
            day = parse_date(source.value(row, "date"))
        except (ValueError, TypeError, OverflowError):
            raise ValueError(f"Journal row {number}: invalid Accounting Date.") from None
        year, period, _ = fiscal_scope(day)
        if year != fiscal_year:
            raise ValueError(f"Journal row {number} belongs to FY{year}, not selected FY{fiscal_year}. Upload one FY at a time.")
        try:
            debit = money(source.value(row, "debit"), blank_zero=True)
            credit = money(source.value(row, "credit"), blank_zero=True)
        except ValueError:
            raise ValueError(f"Journal row {number}: invalid debit or credit amount.") from None
        # R1 has one output row per journal line and one source amount. Never
        # silently net a row whose origin cannot be represented in that layout.
        if debit != ZERO and credit != ZERO:
            raise ValueError(f"Journal row {number} has both a debit and a credit; one amount cannot represent this line.")
        if debit == ZERO and credit == ZERO:
            if bool(text(source.value(row, "debit"))) == bool(text(source.value(row, "credit"))):
                raise ValueError(f"Journal row {number}: a zero amount must identify one debit/credit source column.")
            direction = "Debit" if text(source.value(row, "debit")) else "Credit"
        else:
            direction = "Debit" if debit != ZERO else "Credit"
        amount = debit if direction == "Debit" else credit
        journal_source = text(source.value(row, "source"))
        section = "payables" if account in {"2100", "2402"} else account
        if account == "1621":
            if journal_source.casefold() == "sis":
                section = "loan_activity"
            elif "journal" in journal_source.casefold():
                section = "payment"
        if section not in SECTIONS:
            section = "other"
            other_count += 1
        # Dates already belong to the selected FY. July is its opening month,
        # so FY2027's inclusive cutoff is July 31, 2026, not July 31, 2027.
        prior_year_activity = (day <= date(fiscal_year - 1, 7, 31)
                               and (account == "1382" or (account == "2100"
                                    and journal_source.casefold() == "supplier invoice payment")))
        rows.append(Activity(project, account, section, text(source.value(row, "journal")), day,
                             journal_source, text(source.value(row, "memo")),
                             amount, direction, number, prior_year_activity=prior_year_activity,
                             status=text(source.value(row, "status"))))
        periods.add(period)
        if prior_year_activity:
            kind = "accounts receivable activity" if account == "1382" else "payment"
            source.dispositions[number] = f"Footnote; prior fiscal year {kind} excluded from activity totals"
        else:
            source.dispositions[number] = "Included; unmapped ledger account" if section == "other" else "Included"
    if not rows:
        raise ValueError("No loan activity was found for the configured projects and included accounts.")
    rows.sort(key=lambda row: (-row.day.toordinal(), row.journal, row.source_row))
    return LoanActivity(fiscal_year, tuple(rows), source, tuple(sorted(periods)), other_count)
