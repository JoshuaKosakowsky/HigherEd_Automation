"""Reconcile Banner application flows before proposing TL11A review amounts."""

from __future__ import annotations

from collections import Counter, defaultdict
from dataclasses import dataclass
from decimal import Decimal

import pandas as pd

from .exchange_rates import convert_usd_to_cad, parse_annual_rate, RATE_SERIES
from .preparation import money


ZERO = Decimal("0.00")


def _text(value: object) -> str:
    return "" if pd.isna(value) else str(value).strip()


def _key(value: object) -> str:
    # CSV readers may represent integral Banner identifiers as floats.
    text = _text(value)
    try:
        number = Decimal(text)
        if number.is_finite() and number == number.to_integral_value():
            return str(int(number))
    except ArithmeticError:
        pass
    raise ValueError("Banner transaction identifier is missing or invalid.")


@dataclass(frozen=True)
class TuitionReview:
    paid_usd: Decimal | None
    paid_cad: Decimal | None
    charges: pd.DataFrame
    applications: pd.DataFrame
    reconciliation: pd.DataFrame
    sessions: pd.DataFrame
    checks: pd.DataFrame


def calculate_review(
    transactions: pd.DataFrame, applications: pd.DataFrame,
    enrollment: pd.DataFrame, programs: pd.DataFrame, tax_year: int,
    rate: dict, rate_response: dict | None,
) -> TuitionReview:
    """Use positive payment allocations, not net charges or zero balances.

    Reapplication Y rows may be omitted only when equal reverse-direction
    pairs cancel. Negative charges settle charges as credits, not payments;
    payment reversals settle payments. Unsupported flows withhold the total.
    Whole-history balance reconciliation guards incomplete/sequential extracts.
    """
    checks: list[dict] = []

    def check(name: str, count: int, detail: str, blocks: str = "USD") -> None:
        checks.append(dict(check=name, issue_count=count, result="REVIEW" if count else "OK",
                           blocks_amount=blocks if count else "", detail=detail))

    tx = {_key(row["tran_number"]): row for row in transactions.to_dict("records")}
    if len(tx) != len(transactions):
        raise ValueError("Transaction identifiers are duplicated.")
    incoming, outgoing = defaultdict(lambda: ZERO), defaultdict(lambda: ZERO)
    mirrors: Counter = Counter()
    records = applications.to_dict("records")
    for row in records:
        if _text(row["reapplication_ind"]).upper() == "Y":
            mirrors[(_key(row["payment_tran_number"]), _key(row["charge_tran_number"]),
                     money(row["application_amount_usd"]))] += 1
    unmatched = sum(max(0, count - mirrors[(charge, pay, amount)])
                    for (pay, charge, amount), count in mirrors.items() if pay != charge)
    unmatched += sum(count for (pay, charge, _), count in mirrors.items() if pay == charge)
    check("Reapplication pairs", unmatched,
          "Every Y row must have an equal opposite-direction Y row; matched pairs contribute zero.")

    allocations, missing, unsupported = [], 0, 0
    for row in records:
        pay_key, charge_key = _key(row["payment_tran_number"]), _key(row["charge_tran_number"])
        pay, charge = tx.get(pay_key), tx.get(charge_key)
        amount = money(row["application_amount_usd"])
        outgoing[pay_key] += amount
        incoming[charge_key] += amount
        status, retained, payment_year = "review_flow", ZERO, None
        flags_ok = (_text(row["reapplication_ind"]).upper() in {"", "N", "Y"}
                    and _text(row["direct_payment_ind"]).upper() in {"", "N"}
                    and not _text(row["direct_payment_type"]))
        if pay is None or charge is None:
            status = "missing_transaction"
            missing += 1
        elif amount < 0 or pay_key == charge_key or not flags_ok:
            unsupported += 1
        elif _text(row["reapplication_ind"]).upper() == "Y":
            status = "cancelled_reapplication_pair" if mirrors[(charge_key, pay_key, amount)] == mirrors[(pay_key, charge_key, amount)] else "review_reapplication"
        elif pay["type_ind"] == "P" and charge["type_ind"] == "C" and pay["amount_usd"] > 0 and charge["amount_usd"] > 0:
            status = "payment_to_charge"
            if charge["year_term_candidate"] == "Y" and charge["eligibility_status"] == "eligible":
                retained = amount
                try:
                    date = pd.to_datetime(pay["effective_date"], utc=True)
                    payment_year = None if pd.isna(date) else date.year
                except (ValueError, TypeError, OverflowError):
                    payment_year = None
        elif pay["type_ind"] == charge["type_ind"] == "C" and pay["amount_usd"] < 0 < charge["amount_usd"]:
            status = "charge_credit"
        elif pay["type_ind"] == charge["type_ind"] == "P" and pay["amount_usd"] > 0 > charge["amount_usd"]:
            status = "payment_reversal"
        else:
            unsupported += 1
        allocations.append({**row, "calculation_treatment": status,
                            "retained_paid_usd": retained, "payment_year": payment_year})
    check("Application links", missing, "Every application must link to both source transactions.")
    check("Application flows and flags", unsupported,
          "Supported flows: positive payment to charge, negative charge credit, payment reversal, paired reapplications. Other signs/flags require review.")
    application_report = pd.DataFrame(allocations, columns=list(applications.columns) + [
        "calculation_treatment", "retained_paid_usd", "payment_year"])
    reconciliation = []
    for key, row in tx.items():
        balance = money(row["stored_balance_usd"])
        flow = incoming[key] - outgoing[key] if row["type_ind"] == "C" else outgoing[key] - incoming[key]
        difference = row["amount_usd"] - balance - flow
        reconciliation.append({"tran_number": row["tran_number"], "term_code": row["term_code"],
                               "detail_code": row["detail_code"], "type_ind": row["type_ind"],
                               "amount_usd": row["amount_usd"], "stored_balance_usd": balance,
                               "net_application_usd": flow, "difference_usd": difference})
    reconciliation_report = pd.DataFrame(reconciliation, columns=["tran_number", "term_code", "detail_code",
        "type_ind", "amount_usd", "stored_balance_usd", "net_application_usd", "difference_usd"])
    check("Transaction balances", sum(row["difference_usd"] != 0 for row in reconciliation),
          "Source amount minus stored balance must equal net application flow on every account transaction.")
    check("Transaction types", sum(row["type_ind"] not in {"C", "P"} for row in tx.values()),
          "Unknown charge/payment types cannot be reconciled automatically.")
    check("Application records", int(applications.empty and not transactions.empty),
          "An empty application extract does not prove tuition was paid.")

    charges = []
    for key, row in tx.items():
        if row["type_ind"] != "C" or row["year_term_candidate"] != "Y":
            continue
        paid = sum((a["retained_paid_usd"] for a in allocations if _key(a["charge_tran_number"]) == key), ZERO)
        charges.append({**row, "retained_paid_usd": paid})
    charge_report = pd.DataFrame(charges, columns=list(transactions.columns) + ["retained_paid_usd"])
    check("Charge eligibility rules", sum(row["eligibility_status"] == "review" for row in charges),
          "Requested-year charges must have an approved fee rule.")
    check("Paid charge limits", sum(row["retained_paid_usd"] < 0 or row["retained_paid_usd"] > max(ZERO, row["amount_usd"]) for row in charges),
          "Retained paid allocations must be nonnegative and cannot exceed the positive source charge.")

    sessions = []
    active = enrollment[enrollment.counts_in_enrollment.map(_text).str.upper().ne("N")]
    term_codes = sorted({_text(row["term_code"]) for row in charges} | set(active.term_code.map(_text)))
    for term in term_codes:
        courses = active[active.term_code.map(_text).eq(term)]
        program = programs[programs.term_code.map(_text).eq(term)]
        term_charges = [row for row in charges if _text(row["term_code"]) == term]
        valid = not courses.empty and courses.course_duration_status.eq("meets_minimum").all()
        dates = []
        for course in courses.to_dict("records"):
            start, end = course["section_start_date"], course["section_end_date"]
            if not _text(start) or not _text(end):
                start, end = course["part_of_term_start_date"], course["part_of_term_end_date"]
            for value in (start, end):
                try:
                    date = pd.to_datetime(value, utc=True)
                    if pd.isna(date):
                        valid = False
                    else:
                        dates.append(date.date())
                        valid = valid and date.year == tax_year
                except (ValueError, TypeError, OverflowError):
                    valid = False
        program_valid = len(program) == 1 and all(_text(program.iloc[0][col]) for col in ("program_code", "degree_code", "level_code"))
        sessions.append(dict(term_code=term,
            term_description=_text(courses.iloc[0]["term_description"]) if not courses.empty else _text(term_charges[0]["term_description"]),
            session_start=min(dates) if dates else None, session_end=max(dates) if dates else None,
            course_count=len(courses), credit_hours=pd.to_numeric(courses.credit_hours, errors="coerce").sum(min_count=1),
            duration_review="OK" if valid else "Review dates/course eligibility; no automatic proration",
            program_code=_text(program.iloc[0]["program_code"]) if program_valid else "REVIEW",
            degree_code=_text(program.iloc[0]["degree_code"]) if program_valid else "REVIEW",
            program_review="OK" if program_valid else "Review missing/tied program",
            retained_paid_usd=sum((row["retained_paid_usd"] for row in term_charges), ZERO),
            full_time_attendance_confirmation="", qualifying_degree_confirmation=""))
    session_report = pd.DataFrame(sessions, columns=["term_code", "term_description", "session_start", "session_end",
        "course_count", "credit_hours", "duration_review", "program_code", "degree_code", "program_review",
        "retained_paid_usd", "full_time_attendance_confirmation", "qualifying_degree_confirmation"])
    check("Session duration and year", sum(row["duration_review"] != "OK" for row in sessions) + int(not sessions),
          "All enrolled courses must pass 21 inclusive scheduled days in this calendar year. Missing/mixed/overlapping years require review, not estimated tuition proration.")
    check("Term-effective programs", sum(row["program_review"] != "OK" for row in sessions),
          "One complete latest-effective program is required for each reported term; degree qualification still requires confirmation.")

    financial_blocks = any(row["issue_count"] and row["blocks_amount"] == "USD" for row in checks)
    paid_usd = None if financial_blocks else sum((row["retained_paid_usd"] for row in charges), ZERO)
    cross_year = sum(a["retained_paid_usd"] != 0 and a["payment_year"] != tax_year for a in allocations)
    check("Payment year for CAD", cross_year,
          "Advance/late payments remain in USD. Missing/cross-year effective dates withhold CAD pending appropriate payment-year rate review.", "CAD")
    verified_rate = parse_annual_rate(rate_response, tax_year) if rate_response is not None else None
    rate_ok = (verified_rate is not None and rate.get("status") == "published"
               and rate.get("series") == RATE_SERIES and rate.get("rate_year") == tax_year
               and rate.get("direction") == "CAD per 1 USD" and str(verified_rate) == rate.get("cad_per_usd"))
    check("Published annual USD/CAD rate", int(not rate_ok),
          "Use the matching published Bank of Canada FXAUSDCAD annual observation; no fallback rate.", "CAD")
    paid_cad = convert_usd_to_cad(paid_usd, verified_rate) if paid_usd is not None and rate_ok and not cross_year else None
    checks.append(dict(check="Certificate review", issue_count=None, result="PENDING",
                       blocks_amount="Certificate", detail="Confirm full-time attendance, qualifying degree/courses and owner fee policy before certifying. Scheduled duration alone does not establish attendance."))
    return TuitionReview(paid_usd, paid_cad, charge_report, application_report,
                         reconciliation_report, session_report, pd.DataFrame(checks))
