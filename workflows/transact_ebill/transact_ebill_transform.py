#!/usr/bin/env python3
"""Convert a Banner TSRS schedule/bill .lis file to Transact eBill XML.

This is a Python replacement for Transact_eBill_File_Transformation.pl.  It
keeps the XML field names and parsing behavior used by that script, while
avoiding per-line terminal output and repeated construction of a large regular
expression.
"""

from __future__ import annotations

import argparse
import re
import shutil
import sys
import time
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Iterable, TextIO


DATE_LINE_RE = re.compile(r"^\s*(\d{2}/\d{2}/\d{4})\s+")
STUDENT_RE = re.compile(r"^\s*(.+?)\s+Student ID:\s*(\d+)\s*$")
DUE_DATE_RE = re.compile(r"\bDATE DUE:\s*(\d{2}-\w{3}-\d{4})\b")
TERM_RE = re.compile(r"\bTerm:\s*(\d+)\s*$")
COURSE_RE = re.compile(
    r"^\s*(\S+)\s+(\d+)\s+(\S+)\s+(\S{3,4})\s+(\S+)\s+(.+)\s+(\d+\.\d+)"
)
COURSE_PREFIX_RE = re.compile(r"^\s*\S+\s+\d+\s+")
FINAL_TRANSACTION_AMOUNT_RE = re.compile(r"(-?\d+\.\d{2})$")
DELIMITER_RE = re.compile(r"={75}")
SEMESTER_RE = re.compile(r"\b(Spring|Summer|Fall) (\d{4})")
TOTAL_CHARGE_RE = re.compile(r"Total Current Term Charges:\s*(\d+\.\d+)")
TOTAL_CREDIT_RE = re.compile(r"Total Current Term Credits:\s*(\d+\.\d+)")
COURSE_CREDITS_RE = re.compile(r"Course Credits:\s*(\d+\.\d+)")
PREVIOUS_BALANCE_RE = re.compile(r"Previous/Other Term Balance:\s*([-\d.]+)")
AMOUNT_DUE_RE = re.compile(r"AMOUNT DUE:\s*(\d+\.\d+)")
SKIP_TRANSACTION_RE = re.compile(
    r"Course Credits:|Current Term Balance:|Future Balance:|Version:"
)


@dataclass(slots=True)
class Course:
    prt: str
    crn: str
    subj: str
    crse: str
    sec: str
    title: str
    creds: str


@dataclass(slots=True)
class Transaction:
    description: str
    amount: str
    is_credit: bool = False


@dataclass(slots=True)
class Billing:
    invoice_date: str = ""
    student_id: str = ""
    semester: str = ""
    address1: str = ""
    address2: str = ""
    address3: str = ""
    total_charge: str = ""
    amount_due: str = ""
    term: str = ""
    student_name: str = ""
    total_credit: str = ""
    course_credits: str = ""
    previous_balance: str = ""
    due_date: str = ""
    message: str = ""
    courses: list[Course] = field(default_factory=list)
    transactions: list[Transaction] = field(default_factory=list)

    @property
    def has_detail(self) -> bool:
        return bool(self.courses or self.transactions)


def xml_escape(value: str | None) -> str:
    """Escape text using the same five replacements as the Perl script."""
    if value is None:
        return ""
    return (
        value.replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
        .replace("'", "&apos;")
    )


def find_credit_descriptions(lines: Iterable[str]) -> list[str]:
    """Return unique descriptions found in right-side credit columns."""
    descriptions: list[str] = []
    seen: set[str] = set()
    in_credits = False
    final_amount_re = re.compile(r"(-?\d+\.\d{2})$")
    column_gap_re = re.compile(r"\s{2,}")

    for raw_line in lines:
        line = raw_line.rstrip("\r\n")
        if "CREDITS/ANTICIPATED CREDITS" in line:
            in_credits = True
            continue
        if in_credits and re.match(r"^={10,}", line):
            in_credits = False
            continue
        if not in_credits:
            continue

        amount_match = final_amount_re.search(line)
        if not amount_match:
            continue
        # The report separates its charge and credit columns with at least two
        # spaces.  Splitting at that boundary avoids the original regex's
        # expensive backtracking on padded charge-only rows.
        before_amount = line[: amount_match.start()]
        gap_match = column_gap_re.search(before_amount)
        if not gap_match:
            continue
        description = before_amount[gap_match.end() :].strip()
        description = re.sub(r"^\s*-?\d*\.\d+\s*", "", description)
        if description.strip() and description not in seen:
            seen.add(description)
            descriptions.append(description)

    return descriptions


def _embedded_credit_pattern(descriptions: list[str]) -> re.Pattern[str] | None:
    if not descriptions:
        return None
    alternatives = "|".join(re.escape(item) for item in descriptions)
    return re.compile(rf"(\*?.*?)(-?\d+\.\d{{2}})\s*({alternatives})")


def parse_billings(lines: list[str], credit_descriptions: list[str]) -> list[Billing]:
    """Parse all billing records from the report lines."""
    billings: list[Billing] = []
    invoice_date = ""
    header_read = False
    in_charges = False
    in_message = False
    continued = False
    current = Billing()
    embedded_credit_re = _embedded_credit_pattern(credit_descriptions)

    def finish_current() -> None:
        nonlocal current
        if current.has_detail:
            current.invoice_date = invoice_date
            billings.append(current)
        current = Billing()

    for raw_line in lines:
        line = raw_line.rstrip("\r\n")

        if "CHARGES" in line:
            in_charges = True
        if "Student ID" in line:
            in_charges = False

        stripped_line = line.lstrip()
        date_match = (
            DATE_LINE_RE.match(line)
            if stripped_line[:1].isdigit()
            else None
        )
        if not header_read and date_match:
            invoice_date = date_match.group(1)
            header_read = True
            continue

        if in_message:
            if DELIMITER_RE.search(line):
                in_message = False
                current.message = current.message.rstrip()
            else:
                current.message += line + " "
            continue

        if "* * * CONTINUED ON NEXT PAGE * * *" in line:
            continued = True

        if date_match:
            if current.has_detail and not continued:
                finish_current()
            if continued:
                continued = False

        match = STUDENT_RE.match(line) if "Student ID:" in line else None
        if match:
            current.student_name = match.group(1)
            current.student_id = match.group(2)
            continue

        match = DUE_DATE_RE.search(line) if "DATE DUE:" in line else None
        if match:
            current.due_date = match.group(1)
            prefix = line.split("DATE DUE:", 1)[0]
            if "---NO ADDRESS--" not in line:
                current.address2 = prefix
            continue

        match = TERM_RE.search(line) if "Term:" in line else None
        if match:
            current.term = match.group(1)
            prefix = line.split("Term:", 1)[0]
            if "*** WARNING ***" not in line:
                current.address1 = prefix
            continue

        semester_match = SEMESTER_RE.search(line)
        if semester_match:
            current.semester = f"{semester_match.group(1)} {semester_match.group(2)}"
            continue

        value_patterns = (
            (TOTAL_CHARGE_RE, "total_charge"),
            (TOTAL_CREDIT_RE, "total_credit"),
            (COURSE_CREDITS_RE, "course_credits"),
            (PREVIOUS_BALANCE_RE, "previous_balance"),
        )
        value_found = False
        for pattern, attribute in value_patterns:
            value_match = pattern.search(line)
            if value_match:
                setattr(current, attribute, value_match.group(1))
                value_found = True
                break
        if value_found:
            continue

        amount_due_match = AMOUNT_DUE_RE.search(line)
        if amount_due_match:
            current.amount_due = amount_due_match.group(1)
            current.address3 = line.split("AMOUNT DUE:", 1)[0]
            continue

        if not in_charges and COURSE_PREFIX_RE.match(line):
            course_match = COURSE_RE.match(line)
            if course_match:
                current.courses.append(
                    Course(*(part.strip() for part in course_match.groups()))
                )
                continue

        transaction_text = line.rstrip()
        transaction_match = FINAL_TRANSACTION_AMOUNT_RE.search(transaction_text)
        if transaction_match and not SKIP_TRANSACTION_RE.search(line):
            amount = transaction_match.group(1)
            description = transaction_text[: transaction_match.start()].strip()
            if not description:
                continue
            if ":" in description:
                continue

            split_match = embedded_credit_re.search(description) if embedded_credit_re else None
            if split_match:
                charge_description, charge_amount, credit_description = split_match.groups()
                current.transactions.append(
                    Transaction(charge_description.strip(), charge_amount)
                )
                current.transactions.append(
                    Transaction(credit_description.strip(), amount, is_credit=True)
                )
            else:
                current.transactions.append(Transaction(description.strip(), amount))
            continue

        if DELIMITER_RE.search(line):
            in_message = True
            current.message = ""

    finish_current()
    return billings


def _tag(output: TextIO, name: str, value: str | None) -> None:
    output.write(f"<{name}>{xml_escape(value.strip() if value else '')}</{name}>\n")


def write_xml(billings: Iterable[Billing], output: TextIO) -> int:
    """Write the Transact XML and return the number of Billing records."""
    count = 0
    output.write("<Billings>\n")
    for billing in billings:
        count += 1
        output.write("<Billing>\n")
        _tag(output, "INVOICEDATE", billing.invoice_date)
        _tag(output, "STUDENTID", billing.student_id)
        for course in billing.courses:
            output.write("<SCHEDULE>\n")
            _tag(output, "PRT", course.prt)
            _tag(output, "CRN", course.crn)
            _tag(output, "SUBJ", course.subj)
            _tag(output, "CRSE", course.crse)
            _tag(output, "SEC", course.sec)
            _tag(output, "TITLE", course.title)
            _tag(output, "CREDS", course.creds)
            output.write("</SCHEDULE>\n")
        _tag(output, "TCREDITS", billing.course_credits)
        _tag(output, "PREVBAL", billing.previous_balance)
        for transaction in billing.transactions:
            output.write("<DETAIL>\n")
            output.write("<GROUP>BILLED BALANCE</GROUP>\n")
            output.write("<SECTIONID>CURRENT CHARGES</SECTIONID>\n")
            _tag(output, "TERMCODE", billing.term)
            _tag(output, "DESC", transaction.description)
            _tag(output, "CREDITS" if transaction.is_credit else "CHARGES", transaction.amount)
            output.write("</DETAIL>\n")
        _tag(output, "MESSAGE", billing.message)
        due_date = datetime.strptime(billing.due_date.strip(), "%d-%b-%Y").strftime("%m/%d/%Y")
        _tag(output, "DUEDATE", due_date)
        _tag(output, "TOTALDUE", billing.amount_due)
        _tag(output, "TOTALCHARGE", billing.total_charge)
        _tag(output, "TOTALCREDIT", billing.total_credit)
        _tag(output, "CURRBAL", billing.total_charge)
        _tag(output, "STUDENTNAME", billing.student_name)
        _tag(output, "SEMESTER", billing.semester)
        _tag(output, "BILLTERM", billing.term)
        output.write("<EMAIL/>\n")
        _tag(output, "ADDRESS1", billing.address1)
        _tag(output, "ADDRESS2", billing.address2)
        _tag(output, "ADDRESS3", billing.address3)
        output.write("</Billing>\n")
    output.write("</Billings>\n")
    return count


def transform(input_path: Path, output_path: Path, *, backup: bool = True) -> tuple[int, float]:
    started = time.perf_counter()
    lines = input_path.read_text(encoding="utf-8").splitlines(keepends=True)
    credit_descriptions = find_credit_descriptions(lines)
    billings = parse_billings(lines, credit_descriptions)

    if output_path.exists() and backup:
        timestamp = datetime.now().strftime("%Y%m%d%H%M%S")
        backup_path = output_path.with_name(f"{output_path.stem}_{timestamp}{output_path.suffix}")
        shutil.copy2(output_path, backup_path)

    # Transact's existing Perl process emits Windows CRLF line endings.  Write
    # the Python output the same way so the generated XML is byte-for-byte
    # compatible, not merely equivalent after XML parsing.
    with output_path.open("w", encoding="utf-8", newline="\r\n") as output:
        record_count = write_xml(billings, output)
    return record_count, time.perf_counter() - started


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Convert a Banner TSRS .lis schedule/bill report to Transact eBill XML."
    )
    parser.add_argument("input_file", type=Path, help="source .lis file")
    parser.add_argument(
        "-o", "--output", type=Path, default=Path("schedule_invoice.xml"),
        help="output XML path (default: schedule_invoice.xml)",
    )
    parser.add_argument(
        "--no-backup", action="store_true",
        help="replace an existing output without creating a timestamped backup",
    )
    return parser


def main() -> int:
    args = build_parser().parse_args()
    try:
        records, elapsed = transform(args.input_file, args.output, backup=not args.no_backup)
    except (OSError, UnicodeError, ValueError) as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1
    print(f"Output file generated: {args.output}")
    print(f"Records: {records}")
    print(f"Duration: {elapsed:.3f} seconds")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
