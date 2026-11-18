"""Read source exports without modifying them or assuming fixed column positions."""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from pathlib import Path

import pandas as pd

from data_processing.shared.source_exports import (
    CENT, ZERO, SourceData, fiscal_scope, header_key, match_columns, money,
    parse_date, read_source_table, text,
)
from shared.insights.banner_activity import BannerActivityParameters


STUDENT_PATTERN = re.compile(r"(?<!\d)10\d{6}(?!\d)")
ALIASES = {
    "date": ("Accounting Date",), "kind": ("Journal Source", "Source"),
    "debit": ("Debit Amount", "Workday Debit Amount", "Ledger Debit Amount", "Workday Debit"),
    "credit": ("Credit Amount", "Workday Credit Amount", "Ledger Credit Amount", "Workday Credit"),
    "memo": ("Memo", "Line Memo", "Journal Line Memo"), "ledger": ("Ledger Account",),
    "reference": ("External Reference", "External Reference ID"),
    "journal": ("Journal Entry", "Journal Number"), "line": ("Journal Line ID",),
    "cwid": ("CWID", "Student ID"),
    "id": ("ID",), "description": ("Description",), "code": ("Detail Code",),
    "amount": ("Amount",), "feed": ("Feed Document",), "feed_date": ("Feed Date",),
    "transaction": ("Transaction Number",), "term": ("Term",),
    "user": ("Transaction User", "Cashier User ID"),
    "worktag_memo": ("Line Memo",), "worktags": ("Worktags",),
}
REQUIRED = {
    "Workday": ("date", "kind", "debit", "credit", "memo", "ledger"),
    "Banner": ("id", "description", "code", "amount", "feed", "feed_date"),
    "Worktags": ("worktag_memo", "worktags"),
}


def reference(value: object) -> str:
    value = text(value)
    # Numeric export cells and text such as 12345.0 represent the same document.
    if re.fullmatch(r"[0-9]+\.0+", value):
        value = value.split(".")[0]
    return " ".join(value.split()).upper()


def student_id(value: object) -> str:
    value = text(value)
    return value if re.fullmatch(r"10[0-9]{6}", value) else ""


def leading_student(value: object) -> str:
    match = re.match(r"^(10[0-9]{6})(?=\s|$)", text(value))
    return match[1] if match else ""


def _columns(headers: list[object], source: str) -> dict[str, int] | None:
    return match_columns(headers, source, ALIASES, REQUIRED[source])


def read_source(path: Path, source: str) -> SourceData:
    if source not in REQUIRED:
        raise ValueError("Unknown reconciliation source.")
    return read_source_table(path, source, ALIASES, REQUIRED[source])


def banner_from_frame(frame: pd.DataFrame) -> SourceData:
    columns = _columns(list(frame.columns), "Banner")
    if columns is None:
        raise ValueError("Insights Banner extract is missing required columns.")
    rows = [[None if pd.isna(value) else value for value in row]
            for row in frame.itertuples(index=False, name=None)]
    return SourceData("Banner", "PROD Insights / Banner Activity by Date & Detail Code",
                      list(frame.columns), list(enumerate(rows, 2)), columns)


@dataclass(frozen=True)
class Transaction:
    source: str
    row: int
    day: date
    kind: str
    memo: str
    feed: str
    cwid: str
    account: str
    code: str
    debit: Decimal
    credit: Decimal
    journal: str = ""
    term: str = ""
    user: str = ""
    concerns: tuple[str, ...] = ()

    @property
    def group_key(self) -> tuple[int, str, str]:
        year, period, _ = fiscal_scope(self.day)
        return year, period, self.feed


@dataclass(frozen=True)
class Issue:
    source: str
    row: int
    issue: str


def uploaded_scope(workday: SourceData, banner: SourceData) -> BannerActivityParameters:
    """Use the files' dates and codes instead of hidden extraction defaults."""
    dates = []
    codes = set()
    for source in (workday, banner):
        for _, values in source.rows:
            if source.source == "Workday":
                if not re.match(r"^1305(?:\s|:|$)", text(source.value(values, "ledger"))):
                    continue
                date_field = "date"
            else:
                code = text(source.value(values, "code")).upper()
                if re.fullmatch(r"[A-Z0-9]{4}", code) is None:
                    continue
                codes.add(code)
                date_field = "feed_date"
            try:
                dates.append(parse_date(source.value(values, date_field)))
            except (ValueError, TypeError, OverflowError):
                # Invalid rows still receive the normal source review flags.
                continue
    if not codes:
        raise ValueError("Banner upload contains no valid detail codes. Upload a populated Banner activity export.")
    if not dates:
        raise ValueError("Uploads contain no valid accounting/feed dates. Check the source exports.")
    return BannerActivityParameters(min(dates), max(dates), tuple(sorted(codes)))


def prepare_source(
    source: SourceData, parameters: BannerActivityParameters,
) -> tuple[list[Transaction], list[Issue]]:
    transactions, issues = [], []
    identities = set()
    for number, values in source.rows:
        get = lambda name: source.value(values, name)
        if not any(text(value) for value in values):
            source.dispositions[number] = "Blank row"
            continue
        if any(text(value).casefold() in {"grand total", "report total", "subtotal"} for value in values[:5]):
            source.dispositions[number] = "Excluded report total"
            continue
        if source.source == "Workday":
            if not text(get("ledger")):
                source.dispositions[number] = "Excluded missing ledger account"
                issues.append(Issue(source.source, number, "Invalid ledger account; source coverage requires review"))
                continue
            if not re.match(r"^1305(?:\s|:|$)", text(get("ledger"))):
                source.dispositions[number] = "Excluded ledger account"
                continue
        else:
            code = text(get("code")).upper()
            if re.fullmatch(r"[A-Z0-9]{4}", code) is None:
                source.dispositions[number] = "Excluded invalid detail code"
                issues.append(Issue(source.source, number, "Invalid detail code; source coverage requires review"))
                continue
            if code not in parameters.detail_codes:
                source.dispositions[number] = "Excluded detail code"
                continue
        try:
            day = parse_date(get("date" if source.source == "Workday" else "feed_date"))
        except (ValueError, TypeError, OverflowError):
            source.dispositions[number] = "Excluded invalid date"
            issues.append(Issue(source.source, number, "Invalid source date; selection and amount coverage require review"))
            continue
        if not parameters.start_date <= day <= parameters.end_date:
            source.dispositions[number] = "Excluded date range"
            continue
        try:
            if source.source == "Workday":
                debit = money(get("debit"), blank_zero=True)
                credit = money(get("credit"), blank_zero=True)
            else:
                amount = money(get("amount"))
                # Issue #17: this sponsor's Banner sign is opposite Workday's.
                # Normalize before matching/aggregation; keep the source row intact.
                if "TPS00080" in text(get("id")).upper():
                    amount = -amount
                debit, credit = max(amount, ZERO), max(-amount, ZERO)
        except ValueError:
            source.dispositions[number] = "Excluded invalid amount"
            issues.append(Issue(source.source, number, "Invalid amount; selected totals are incomplete"))
            continue
        concerns = []
        kind = text(get("kind")) if source.source == "Workday" else "Banner"
        memo = text(get("memo" if source.source == "Workday" else "description"))
        feed = reference(get("feed")) if source.source == "Banner" else (
            reference(get("reference")) or reference(get("memo")) if kind.upper() == "SIS" else ""
        )
        if source.source == "Workday":
            if not kind:
                concerns.append("Missing journal source; activity classification requires review")
            if debit < 0 or credit < 0 or (debit and credit):
                concerns.append("Unusual debit/credit signs or both populated")
            cwid = student_id(get("cwid")) or leading_student(memo)
            account = ""
            identity = (text(get("journal")), text(get("line"))) if text(get("line")) else None
        else:
            account = text(get("id"))
            cwid = student_id(account) or leading_student(memo)
            if student_id(account) and leading_student(memo) and student_id(account) != leading_student(memo):
                concerns.append("Conflicting account ID and description student ID")
                cwid = ""
            identity = (account, text(get("transaction"))) if text(get("transaction")) else None
        if identity is not None:
            if identity in identities:
                concerns.append("Duplicate source transaction identity; rows retained")
            identities.add(identity)
        if not feed and (source.source == "Banner" or kind.upper() == "SIS"):
            concerns.append("Missing feed document; cannot match this row")
        if not cwid and (source.source == "Banner" or kind.upper() != "SIS"):
            concerns.append("Missing valid CWID; student attribution incomplete")
        issues.extend(Issue(source.source, number, concern) for concern in concerns)
        source.dispositions[number] = "Selected"
        transactions.append(Transaction(source.source, number, day, kind, memo, feed, cwid, account,
            text(get("code")).upper() if source.source == "Banner" else "", debit, credit,
            text(get("journal")), text(get("term")), text(get("user")), tuple(concerns)))
    return transactions, issues
