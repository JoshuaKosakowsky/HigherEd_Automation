"""Validate TL11A extracts and classify charges without inventing tuition paid."""

from __future__ import annotations

import json
import re
from decimal import Decimal, InvalidOperation
from pathlib import Path

import pandas as pd


REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
QUERY_DIRECTORY = REPOSITORY_ROOT / "query/AR/canadian_tax"
DEFAULT_RULES = REPOSITORY_ROOT / "config/institutions/mines/tl11a_detail_codes.json"


def validate_inputs(cwid: str, tax_year: int) -> None:
    if not re.fullmatch(r"[A-Za-z0-9_-]{1,30}", cwid):
        raise ValueError("CWID must contain 1-30 letters, digits, underscores or hyphens.")
    if type(tax_year) is not int or not 2000 <= tax_year <= 2099:
        raise ValueError("Tax year must be a four-digit year from 2000 through 2099.")


def render_query(name: str, cwid: str, tax_year: int) -> str:
    validate_inputs(cwid, tax_year)
    if name not in {"identity", "transactions", "enrollment", "programs", "payment_applications"}:
        raise ValueError("Unknown TL11A extract.")
    scope = (QUERY_DIRECTORY / "tl11a_scope.sql").read_text(encoding="utf-8")
    scope = scope.replace("__CWID__", f"'{cwid}'").replace("__TAX_YEAR__", str(tax_year))
    return (QUERY_DIRECTORY / f"tl11a_{name}.sql").read_text(encoding="utf-8").replace(
        "__TL11A_SCOPE_SQL__", scope
    )


def validate_extract(frame: pd.DataFrame, tax_year: int) -> None:
    """COUNT OVER protects against the Insights result limit."""
    required = {"extract_row_count", "extract_tax_year", "pidm"}
    if not required.issubset(frame.columns):
        raise ValueError("Extract is missing completeness/scope columns.")
    if frame.empty:
        return
    if frame["extract_row_count"].isna().any() or not frame["extract_row_count"].eq(len(frame)).all():
        raise ValueError("Extract is incomplete or has inconsistent row counts.")
    if not frame["extract_tax_year"].eq(tax_year).all():
        raise ValueError("Extract belongs to another tax year.")
    if frame["pidm"].isna().any() or frame["pidm"].nunique() != 1:
        raise ValueError("Extract does not identify exactly one account.")


def load_rules(path: Path = DEFAULT_RULES) -> dict[str, dict[str, str]]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict) or payload.get("schemaVersion") != 1:
        raise ValueError("Unsupported TL11A detail-code rules.")
    rules = payload.get("rules")
    if not isinstance(rules, dict):
        raise ValueError("TL11A rules must be a detail-code mapping.")
    for code, rule in rules.items():
        if ((code != "*" and not re.fullmatch(r"[A-Z0-9]{1,4}", code))
                or not isinstance(rule, dict)
                or rule.get("status") not in {"eligible", "excluded", "review"}
                or not isinstance(rule.get("reason"), str) or not rule["reason"].strip()):
            raise ValueError("Each detail-code rule requires a valid status and reason.")
    return rules


def money(value: object) -> Decimal:
    try:
        amount = Decimal(str(value))
    except (InvalidOperation, ValueError):
        raise ValueError("Transaction amount is missing or invalid.") from None
    try:
        valid = amount.is_finite() and amount == amount.quantize(Decimal("0.01"))
    except InvalidOperation:
        valid = False
    if not valid:
        raise ValueError("Transaction amount must be finite USD with at most two decimals.")
    return amount


def prepare_transactions(
    frame: pd.DataFrame, rules: dict[str, dict[str, str]],
) -> pd.DataFrame:
    required = {"pidm", "tran_number", "term_code", "detail_code", "type_ind", "amount_usd"}
    if not required.issubset(frame.columns):
        raise ValueError("Transaction extract is missing required columns.")
    if frame[["pidm", "tran_number"]].isna().any().any() or frame.duplicated(["pidm", "tran_number"]).any():
        raise ValueError("Transaction identifiers are missing or duplicated; check source joins.")
    result = frame.copy()
    amounts, classifications, reasons = [], [], []
    for row in frame.to_dict("records"):
        amounts.append(money(row["amount_usd"]))
        kind = str(row["type_ind"]).strip().upper()
        code = str(row["detail_code"]).strip().upper()
        if kind == "P":
            status, reason = "payment", "Payment source; allocation to eligible tuition remains unverified. Scholarships are not automatically subtracted."
        elif kind == "C":
            rule = rules.get(code, rules.get("*", {"status": "review", "reason": "No approved eligibility rule for this charge code."}))
            status, reason = rule["status"], rule["reason"]
        else:
            status, reason = "review", "Missing or unknown Banner charge/payment indicator."
        classifications.append(status)
        reasons.append(reason)
    result["amount_usd"] = amounts
    result["eligibility_status"] = classifications
    result["eligibility_reason"] = reasons
    return result


def summarize_codes(frame: pd.DataFrame) -> pd.DataFrame:
    """Inventory signed source amounts; these are not eligible tuition paid."""
    columns = ["term_code", "detail_code", "type_ind", "eligibility_status", "eligibility_reason"]
    return frame.groupby(columns, dropna=False, sort=True).agg(
        transaction_count=("tran_number", "size"),
        net_source_amount_usd=("amount_usd", "sum"),
    ).reset_index()


def prepare_payment_applications(
    frame: pd.DataFrame, transactions: pd.DataFrame,
) -> pd.DataFrame:
    """Link raw applications without treating them as final paid tuition."""
    required = {"pidm", "application_id", "payment_tran_number", "charge_tran_number", "application_amount_usd"}
    if not required.issubset(frame.columns):
        raise ValueError("Payment application extract is missing required columns.")
    if frame[["pidm", "application_id"]].isna().any().any() or frame.duplicated(["pidm", "application_id"]).any():
        raise ValueError("Payment application identifiers are missing or duplicated.")
    columns = ["pidm", "tran_number", "term_code", "detail_code", "type_ind", "effective_date", "eligibility_status"]
    if not set(columns).issubset(transactions.columns):
        raise ValueError("Prepared transactions are missing application-link columns.")
    if transactions.duplicated(["pidm", "tran_number"]).any():
        raise ValueError("Transaction identifiers are duplicated; application links would multiply.")
    result = frame.copy()
    result["application_amount_usd"] = [money(value) for value in frame.application_amount_usd]
    for role in ("payment", "charge"):
        source = transactions[columns].rename(columns={
            column: f"{role}_{column}" for column in columns if column != "pidm"
        })
        result = result.merge(source, how="left", on=["pidm", f"{role}_tran_number"], validate="many_to_one", sort=False)
    result["application_review_status"] = [
        "missing_transaction" if pd.isna(pay) or pd.isna(charge)
        else "linked" if pay == "P" and charge == "C"
        else "review_transaction_types"
        for pay, charge in zip(result.payment_type_ind, result.charge_type_ind)
    ]
    return result


def prepare_enrollment(frame: pd.DataFrame) -> pd.DataFrame:
    """Check each course's scheduled duration; do not infer full-time status."""
    columns = ["section_start_date", "section_end_date", "part_of_term_start_date", "part_of_term_end_date"]
    if not set(columns + ["counts_in_enrollment"]).issubset(frame.columns):
        raise ValueError("Enrollment extract is missing duration-check columns.")
    result = frame.copy()
    days, statuses = [], []
    for row in frame.to_dict("records"):
        parsed = []
        invalid = False
        for column in columns:
            value = row[column]
            if pd.isna(value) or value == "":
                parsed.append(None)
                continue
            try:
                timestamp = pd.to_datetime(value, utc=True)
                if pd.isna(timestamp):
                    invalid = True
                    parsed.append(None)
                else:
                    parsed.append(timestamp.date())
            except (TypeError, ValueError, OverflowError):
                invalid = True
                parsed.append(None)
        start, end, part_start, part_end = parsed
        conflict = (start is not None and part_start is not None and start != part_start
                    or end is not None and part_end is not None and end != part_end)
        # Use a complete date pair; do not mix a section start with a part end.
        if start is None or end is None:
            start, end = part_start, part_end
        length = (end - start).days + 1 if start is not None and end is not None else None
        days.append(length)
        if invalid or conflict or length is None or length <= 0:
            status = "review_dates"
        elif str(row["counts_in_enrollment"]).strip().upper() == "N":
            status = "not_enrolled"
        elif str(row["counts_in_enrollment"]).strip().upper() != "Y":
            status = "review_enrollment_status"
        else:
            status = "meets_minimum" if length >= 21 else "below_minimum"
        statuses.append(status)
    result["scheduled_duration_days"] = pd.array(days, dtype="Int64")
    result["course_duration_status"] = statuses
    return result
