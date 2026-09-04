from __future__ import annotations

from collections import defaultdict
from datetime import date, datetime, timedelta
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
import math
import re
from typing import Any, Iterable

import pandas as pd

from .terms import RefundParameters, fiscal_year_start


CENT = Decimal("0.01")
ZERO = Decimal("0.00")
PRIORITY_PATTERN = re.compile(r"^[0-9]{1,3}$")
ORIGINAL_PAYMENT_CODES = {"ACHK", "CRDS", "CRED", "CRVC", "CRAM", "CRMC"}
LAST_000_CODES = {"ACHK", "CRAM", "CRDS", "CRMC", "CRVC"}

TRANSACTION_COLUMNS = {
    "pidm",
    "term_code",
    "aidy_code",
    "tran_number",
    "detail_code",
    "amount",
    "stored_balance",
    "effective_date",
    "activity_date",
    "detail_desc",
    "type_ind",
    "priority",
    "category_code",
    "title_iv_ind",
}

CONTEXT_COLUMNS = {
    "pidm",
    "cwid",
    "last_name",
    "first_name",
    "deceased_ind",
    "deceased_date",
    "confidential_ind",
    "account_control_row_count",
    "refund_hold_count",
    "raw_delinquency_code",
    "raw_refund_account_ind",
    "account_control_activity_date",
    "active_ed_row_count",
    "ed_activity_date",
    "plus_auth_row_ind",
    "plus_auth_aidy_code",
    "plus_to_student",
    "plus_auth_activity_date",
}

REPORT_COLUMNS = [
    "cwid",
    "last_name",
    "first_name",
    "full_account_balance",
    "total_refund_amount",
    "proposed_student_delivery",
    "student_refund_amount",
    "proposed_parent_delivery",
    "parent_refund_amount",
    "balance_sources",
    "plus_to_student_status",
    "parent_plus_target_term",
    "refund_split_status",
    "third_party_review_required_ind",
    "third_party_match_source",
    "refund_hold_ind",
    "raw_delinquency_code",
    "active_ed_ind",
    "raw_refund_account_ind",
    "refund_account_selected_ind",
    "fdpl_row_count",
    "target_term_fdpl_amount",
    "fdpl_aidy_code",
    "fdpl_priority_tie_rule",
    "unused_fdpl_amount",
    "unused_non_fdpl_amount",
    "total_unused_payment_amount",
    "unpaid_charge_amount",
    "allocation_review_required_ind",
    "previous_term_balance_before_current_payments",
    "prior_terms_balance_before_current_payments",
    "title_iv_applied_to_older_fiscal_years",
    "unrestricted_applied_to_older_terms",
    "original_payment_row_count",
    "original_payment_total",
    "original_payment_detail",
    "deceased_ind",
    "deceased_date",
    "confidential_ind",
    "plus_auth_row_count",
    "plus_auth_raw_values",
    "negative_source_count",
    "ambiguous_source_pool_count",
    "review_status",
    "review_reasons",
    "last_ar_activity_date",
    "account_control_activity_date",
    "ed_activity_date",
    "plus_auth_activity_date",
]


def _is_missing(value: object) -> bool:
    if value is None or value is pd.NA or value is pd.NaT:
        return True
    if isinstance(value, float):
        return math.isnan(value)
    return False


def _text(value: object, *, upper: bool = False) -> str | None:
    if _is_missing(value):
        return None
    result = str(value).strip()
    if not result:
        return None
    return result.upper() if upper else result


def _integer(value: object, default: int = 0) -> int:
    if _is_missing(value):
        return default
    return int(value)


def _decimal(value: object, *, missing_as_zero: bool = True) -> Decimal | None:
    if _is_missing(value):
        return ZERO if missing_as_zero else None
    try:
        return Decimal(str(value))
    except (InvalidOperation, ValueError) as error:
        raise ValueError(f"Invalid financial amount: {value!r}") from error


def _money(value: Decimal | int | str) -> Decimal:
    return Decimal(value).quantize(CENT, rounding=ROUND_HALF_UP)


def _date(value: object) -> date | None:
    if _is_missing(value):
        return None
    if isinstance(value, pd.Timestamp):
        return value.date()
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    text = str(value).strip()
    if not text:
        return None
    try:
        return date.fromisoformat(text[:10])
    except ValueError:
        parsed = pd.to_datetime(text, errors="coerce")
        return None if pd.isna(parsed) else parsed.date()


def _datetime(value: object) -> datetime | None:
    if _is_missing(value):
        return None
    if isinstance(value, pd.Timestamp):
        value = value.to_pydatetime()
    if isinstance(value, datetime):
        return value.replace(tzinfo=None)
    if isinstance(value, date):
        return datetime.combine(value, datetime.min.time())
    text = str(value).strip()
    if not text:
        return None
    try:
        return datetime.fromisoformat(text[:19])
    except ValueError:
        parsed = pd.to_datetime(text, errors="coerce")
        if pd.isna(parsed):
            return None
        return parsed.to_pydatetime().replace(tzinfo=None)


def _max_datetime(values: Iterable[object]) -> datetime | None:
    timestamps = [
        parsed for value in values if (parsed := _datetime(value)) is not None
    ]
    return max(timestamps) if timestamps else None


def _priority(value: object) -> str | None:
    text = _text(value)
    if text is None or not PRIORITY_PATTERN.fullmatch(text):
        return None
    return text.zfill(3)


def _effective_priority(detail_code: str, priority: str | None) -> tuple[str | None, int | None]:
    if detail_code in {"TPDT", "TPPY"} and priority == "800":
        return "800A", 8002
    if priority == "800":
        return "800", 8001
    if detail_code == "COFP" and priority == "000":
        return "000A", 2
    if detail_code in LAST_000_CODES and priority == "000":
        return "000Z", 0
    if priority is None:
        return None, None
    return priority, int(priority) * 10 + 1


def _priority_matches(charge_priority: str | None, payment_priority: str | None) -> bool:
    if charge_priority is None or payment_priority is None:
        return False
    return all(payment == "0" or payment == charge for charge, payment in zip(charge_priority, payment_priority))


def _sort_number(value: object) -> int:
    return _integer(value, 2**63 - 1)


def _normalize_columns(frame: pd.DataFrame) -> pd.DataFrame:
    result = frame.copy()
    result.columns = [
        re.sub(r"[^a-z0-9]+", "_", str(column).strip().lower()).strip("_")
        for column in result.columns
    ]
    return result


def _validate_columns(frame: pd.DataFrame, required: set[str], label: str) -> None:
    missing = sorted(required - set(frame.columns))
    if missing:
        raise ValueError(f"{label} extract is missing columns: {', '.join(missing)}")


def _normalize_transaction(row: dict[str, Any], source_id: int) -> dict[str, Any]:
    term = _text(row["term_code"]) or ""
    raw_amount = _decimal(row["amount"]) or ZERO
    type_ind = _text(row["type_ind"], upper=True)
    accounting_amount = (
        -raw_amount if type_ind == "P" else raw_amount if type_ind == "C" else None
    )
    priority = _priority(row["priority"])
    return {
        "source_id": source_id,
        "pidm": _integer(row["pidm"]),
        "term_code": term,
        "term_sort": int(term) if fiscal_year_start(term) is not None else None,
        "fiscal_year_start": fiscal_year_start(term),
        "aidy_code": _text(row["aidy_code"]),
        "tran_number": _integer(row["tran_number"], 2**63 - 1),
        "detail_code": _text(row["detail_code"], upper=True) or "",
        "raw_amount": raw_amount,
        "amount_missing": _is_missing(row["amount"]),
        "stored_balance": _decimal(row["stored_balance"], missing_as_zero=False),
        "effective_date": _date(row["effective_date"]),
        "activity_date": _datetime(row["activity_date"]),
        "detail_desc": _text(row["detail_desc"]) or "[Description unavailable]",
        "type_ind": type_ind,
        "priority_code": priority,
        "category_code": _text(row["category_code"], upper=True) or "",
        "is_title_iv": _text(row["title_iv_ind"], upper=True) == "Y",
        "accounting_amount": accounting_amount,
    }


def _payment_sources(transactions: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], int]:
    rows = [row for row in transactions if row["type_ind"] == "P" and row["term_sort"] is not None]
    grouped: dict[tuple[object, ...], list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        grouped[(row["term_code"], row["aidy_code"], row["detail_code"])].append(row)

    sources: list[dict[str, Any]] = []
    negative_groups = 0
    for group in grouped.values():
        group_net = sum((row["raw_amount"] for row in group), ZERO)
        if group_net < 0:
            negative_groups += 1
        prior_positive = ZERO
        for row in sorted(group, key=lambda item: item["tran_number"]):
            if row["raw_amount"] <= 0:
                continue
            amount = _money(min(row["raw_amount"], max(group_net - prior_positive, ZERO)))
            prior_positive += row["raw_amount"]
            if amount <= 0:
                continue
            effective, priority_sort = _effective_priority(row["detail_code"], row["priority_code"])
            if row["is_title_iv"]:
                fund_type = "TITLE_IV"
            elif row["category_code"].startswith("FA"):
                fund_type = "NON_TITLE_IV_FA"
            elif row["category_code"] == "CSH":
                fund_type = "CASH"
            else:
                fund_type = "OTHER_UNRESTRICTED"
            sources.append({
                **row,
                "source_amount": amount,
                "stored_unused_amount": _money(max(-(row["stored_balance"] or ZERO), ZERO)),
                "effective_priority_code": effective,
                "payment_priority_sort": priority_sort,
                "fund_type": fund_type,
            })
    return sources, negative_groups


def _charge_sources(
    transactions: list[dict[str, Any]],
    target_term_sort: int,
) -> tuple[list[dict[str, Any]], int]:
    """Build term-and-priority charge pools through the target term.

    Charge credits/reversals net only within their original term and priority.
    Keeping every term separate is required because cross-term payment rules are
    applied later, from the oldest outstanding term forward.
    """
    rows = [
        row for row in transactions
        if row["type_ind"] == "C"
        and row["term_sort"] is not None
        and row["term_sort"] <= target_term_sort
    ]
    grouped: dict[tuple[object, ...], list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        grouped[(row["term_code"], row["priority_code"])].append(row)

    charges: list[dict[str, Any]] = []
    negative_groups = 0
    for (term_code, priority), group in grouped.items():
        group_net = sum((row["raw_amount"] for row in group), ZERO)
        if group_net < 0:
            negative_groups += 1
        prior_positive = ZERO
        surviving: list[tuple[dict[str, Any], Decimal]] = []
        for row in sorted(group, key=lambda item: item["tran_number"]):
            if row["raw_amount"] <= 0:
                continue
            amount = _money(min(row["raw_amount"], max(group_net - prior_positive, ZERO)))
            prior_positive += row["raw_amount"]
            if amount > 0:
                surviving.append((row, amount))
        if not surviving:
            continue
        first = surviving[0][0]
        charges.append({
            "term_code": term_code,
            "term_sort": first["term_sort"],
            "fiscal_year_start": first["fiscal_year_start"],
            "tran_number": min(row["tran_number"] for row, _ in surviving),
            "detail_code": f"PRIORITY_{priority or 'INVALID'}",
            "detail_desc": "Aggregated charges at the same term and priority",
            "priority_code": priority,
            "charge_amount": _money(sum((amount for _, amount in surviving), ZERO)),
        })
    return charges, negative_groups


def _payment_sort_key(source: dict[str, Any]) -> tuple[object, ...]:
    priority = source["payment_priority_sort"]
    return (-(priority if priority is not None else -1), source["tran_number"], source["term_sort"], source["detail_code"])


def _charge_sort_key(charge: dict[str, Any]) -> tuple[object, ...]:
    return (charge["term_sort"], -(int(charge["priority_code"]) if charge["priority_code"] else -1), charge["tran_number"], charge["detail_code"])


def _open_allocation_window(
    transactions: list[dict[str, Any]],
    target_term_sort: int,
) -> tuple[list[dict[str, Any]], int | None]:
    """Exclude the most recent cumulatively settled historical prefix.

    A zero cumulative raw balance at a completed term boundary means every
    earlier charge and payment has already been resolved at the account level.
    Replaying that closed history under today's priorities can resurrect loans
    that were consumed or refunded years ago. Activity after the last zero
    boundary remains fully term-specific and is allocated oldest term first.
    """
    balances_by_term: dict[int, Decimal] = defaultdict(lambda: ZERO)
    for row in transactions:
        term_sort = row["term_sort"]
        if term_sort is not None and term_sort <= target_term_sort:
            balances_by_term[term_sort] += row["accounting_amount"] or ZERO

    cumulative = ZERO
    settled_through: int | None = None
    for term_sort in sorted(balances_by_term):
        cumulative = _money(cumulative + balances_by_term[term_sort])
        if term_sort < target_term_sort and cumulative == ZERO:
            settled_through = term_sort

    if settled_through is None:
        return transactions, None
    return (
        [row for row in transactions if row["term_sort"] > settled_through],
        settled_through,
    )


def _apply_pairs(
    charges: list[dict[str, Any]],
    sources: list[dict[str, Any]],
    *,
    title_iv_cap: Decimal | None = None,
) -> tuple[dict[int, Decimal], list[Decimal], list[dict[str, Any]]]:
    """Apply ordered payments to ordered term/priority charge pools."""
    payment_remaining = {source["source_id"]: source["allocation_amount"] for source in sources}
    charge_remaining = [charge["charge_amount"] for charge in charges]
    transfers: list[dict[str, Any]] = []
    given_by_fy: dict[int, Decimal] = defaultdict(lambda: ZERO)
    received_by_fy: dict[int, Decimal] = defaultdict(lambda: ZERO)

    for charge_index, charge in enumerate(charges):
        for source in sources:
            if charge_remaining[charge_index] <= 0:
                break
            if not _priority_matches(charge["priority_code"], source["priority_code"]):
                continue
            available_charge = charge_remaining[charge_index]
            available_payment = payment_remaining[source["source_id"]]
            if available_payment <= 0:
                continue
            cap_available = available_payment
            cross_fy_title_iv = (
                title_iv_cap is not None
                and source["is_title_iv"]
                and source["fiscal_year_start"] != charge["fiscal_year_start"]
            )
            if cross_fy_title_iv:
                cap_available = max(
                    min(
                        title_iv_cap - given_by_fy[source["fiscal_year_start"]],
                        title_iv_cap - received_by_fy[charge["fiscal_year_start"]],
                    ),
                    ZERO,
                )
            applied = _money(min(available_charge, available_payment, cap_available))
            if applied <= 0:
                continue
            charge_remaining[charge_index] -= applied
            payment_remaining[source["source_id"]] -= applied
            if cross_fy_title_iv:
                given_by_fy[source["fiscal_year_start"]] += applied
                received_by_fy[charge["fiscal_year_start"]] += applied
            transfers.append({"amount": applied, "charge": charge, "source": source})
    return payment_remaining, charge_remaining, transfers


def _context_for_account(context_rows: list[dict[str, Any]]) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    if context_rows:
        first = context_rows[0]
    else:
        first = {}
    account = {
        "cwid": _text(first.get("cwid")),
        "last_name": _text(first.get("last_name")),
        "first_name": _text(first.get("first_name")),
        "deceased_ind": _text(first.get("deceased_ind")),
        "deceased_date": _date(first.get("deceased_date")),
        "confidential_ind": _text(first.get("confidential_ind")),
        "account_control_row_count": _integer(first.get("account_control_row_count")),
        "refund_hold_count": _integer(first.get("refund_hold_count")),
        "raw_delinquency_code": _text(first.get("raw_delinquency_code")),
        "raw_refund_account_ind": _text(first.get("raw_refund_account_ind")),
        "account_control_activity_date": _datetime(first.get("account_control_activity_date")),
        "active_ed_row_count": _integer(first.get("active_ed_row_count")),
        "ed_activity_date": _datetime(first.get("ed_activity_date")),
    }
    authorization_rows = [
        row for row in context_rows
        if _integer(row.get("plus_auth_row_ind")) == 1
    ]
    return account, authorization_rows


def _format_money(value: Decimal) -> str:
    return f"{value:.2f}"


def _join_reasons(values: Iterable[str | None]) -> str | None:
    selected = [value for value in values if value]
    return "; ".join(selected) if selected else None


def _student_delivery(
    student_amount: Decimal | None,
    sources: list[dict[str, Any]],
    *,
    run_date: date,
    refund_hold: bool,
    third_party: bool,
    active_ed: bool,
) -> tuple[str, dict[str, Any]]:
    amounts = {
        "ach_eligible": ZERO,
        "ach_wait": ZERO,
        "ach_old": ZERO,
        "ach_date_review": ZERO,
        "crvc": ZERO,
    }
    next_eligible: list[date] = []
    for source in sources:
        amount = source["source_credit_amount"]
        if source["detail_code"] == "CRVC":
            amounts["crvc"] += amount
        if source["detail_code"] != "ACHK":
            continue
        effective = source["effective_date"]
        if effective is None or effective > run_date:
            amounts["ach_date_review"] += amount
        elif run_date < effective + timedelta(days=16):
            amounts["ach_wait"] += amount
            next_eligible.append(effective + timedelta(days=16))
        elif (run_date - effective).days <= 180:
            amounts["ach_eligible"] += amount
        else:
            amounts["ach_old"] += amount

    student = student_amount or ZERO
    special_total = sum(amounts.values(), ZERO)
    standard = _money(max(student - special_total, ZERO))
    components: list[tuple[str, Decimal]] = [
        ("AFRD (Transact)", amounts["ach_eligible"]),
        ("CRVC (Transact)", amounts["crvc"]),
        ("ACHK_WAIT", amounts["ach_wait"]),
        ("AFRD (Transact) - May Be Too Old", amounts["ach_old"]),
        ("ACHK Date Review", amounts["ach_date_review"]),
        ("ARFD (System)" if active_ed else "RFND (CHECK)", standard),
    ]
    active_components = [(label, _money(amount)) for label, amount in components if amount > 0]

    if student <= 0:
        delivery = "NONE"
    elif refund_hold:
        delivery = "Refund Hold - Student"
    elif third_party:
        delivery = "THIRD_PARTY_REVIEW"
    elif len(active_components) == 1:
        label, _ = active_components[0]
        if label == "ACHK_WAIT":
            delivery = f"ACHK Clearing Wait until {min(next_eligible):%m/%d/%Y}"
        else:
            delivery = label
    else:
        descriptions: list[str] = []
        for label, amount in active_components:
            if label == "ACHK_WAIT":
                descriptions.append(
                    f"ACHK Clearing Wait until {min(next_eligible):%m/%d/%Y} / {_format_money(amount)}"
                )
            else:
                descriptions.append(f"{label} {_format_money(amount)}")
        delivery = "; ".join(descriptions)

    return delivery, {
        **amounts,
        "next_eligible": min(next_eligible) if next_eligible else None,
        "standard": standard,
    }


def _allocate_account(
    transactions: list[dict[str, Any]],
    context_rows: list[dict[str, Any]],
    parameters: RefundParameters,
    legacy_third_party_cwids: set[str],
) -> dict[str, Any] | None:
    target_sort = int(parameters.target_term)
    previous_sort = int(parameters.previous_term)
    account, authorization_rows = _context_for_account(context_rows)

    if any(row["type_ind"] not in {"C", "P"} for row in transactions):
        return None

    full_balance = _money(sum((row["accounting_amount"] or ZERO for row in transactions), ZERO))
    target_rows = [row for row in transactions if row["term_code"] == parameters.target_term]
    fiscal_balances: dict[int, Decimal] = defaultdict(lambda: ZERO)
    for row in transactions:
        if row["term_sort"] is not None and row["term_sort"] <= target_sort:
            fiscal_balances[row["fiscal_year_start"]] += row["accounting_amount"] or ZERO
    negative_stored_target_payment = any(
        row["type_ind"] == "P"
        and row["stored_balance"] is not None
        and row["stored_balance"] < 0
        for row in target_rows
    )
    if not (
        full_balance < 0
        or negative_stored_target_payment
        or (target_rows and fiscal_balances and min(fiscal_balances.values()) < 0)
    ):
        return None

    invalid_priority_count = sum(row["raw_amount"] != 0 and row["priority_code"] is None for row in transactions)
    missing_amount_count = sum(row["amount_missing"] for row in transactions)
    negative_source_count = sum(row["raw_amount"] < 0 for row in transactions)
    invalid_term_count = sum(row["raw_amount"] != 0 and row["term_sort"] is None for row in transactions)
    future_term_count = sum(
        row["raw_amount"] != 0 and row["term_sort"] is not None and row["term_sort"] > target_sort
        for row in transactions
    )
    special_priority_mismatch_count = sum(
        row["raw_amount"] != 0 and (
            (row["detail_code"] in {"TPDT", "TPPY"} and row["priority_code"] != "800")
            or (row["detail_code"] == "COFP" and row["priority_code"] != "000")
            or (row["detail_code"] in LAST_000_CODES and row["priority_code"] != "000")
        )
        for row in transactions
    )
    missing_balance_count = sum(row["stored_balance"] is None for row in transactions)

    eligible_transactions = [
        row for row in transactions
        if row["term_sort"] is not None and row["term_sort"] <= target_sort
    ]
    allocation_transactions, _settled_through = _open_allocation_window(
        eligible_transactions,
        target_sort,
    )
    payment_sources, negative_payment_groups = _payment_sources(allocation_transactions)

    charges, negative_charge_groups = _charge_sources(
        allocation_transactions,
        target_sort,
    )

    # Preserve every payment source and every term/priority charge pool. Charges
    # are handled oldest-term first; payment eligibility and ordering are then
    # evaluated for the actual charge instead of against a synthetic FY balance.
    staged_sources: list[dict[str, Any]] = [
        {**source, "allocation_amount": _money(source["source_amount"])}
        for source in payment_sources
        if source["source_amount"] > 0
    ]
    staged_sources.sort(key=_payment_sort_key)
    staged_charges = sorted(charges, key=_charge_sort_key)

    cap = _money(parameters.title_iv_cross_fy_cap)
    payment_remaining, charge_remaining, transfers = _apply_pairs(
        staged_charges,
        staged_sources,
        title_iv_cap=cap,
    )

    selected_sources = []
    for sequence, source in enumerate(staged_sources, start=1):
        remaining = _money(payment_remaining[source["source_id"]])
        source["payment_sequence"] = sequence
        if remaining > 0:
            selected_sources.append({**source, "source_credit_amount": remaining})
    unpaid_charges = _money(sum(charge_remaining, ZERO))
    policy_unused_total = _money(sum((source["source_credit_amount"] for source in selected_sources), ZERO))
    unused_fdpl = _money(sum((source["source_credit_amount"] for source in selected_sources if source["detail_code"] == "FDPL"), ZERO))
    unused_non_fdpl = policy_unused_total - unused_fdpl
    account_credit = _money(max(-full_balance, ZERO))
    policy_credit_mismatch = policy_unused_total != account_credit

    eligible_balance = _money(sum((row["accounting_amount"] or ZERO for row in allocation_transactions), ZERO))
    reconstructed_balance = _money(unpaid_charges - policy_unused_total)
    ledger_residual = _money(eligible_balance - reconstructed_balance)

    selected_by_id = {source["source_id"]: source["source_credit_amount"] for source in selected_sources}
    stored_difference_count = sum(
        abs(selected_by_id.get(source["source_id"], ZERO) - source["stored_unused_amount"]) > Decimal("0.01")
        for source in staged_sources
    )
    negative_net_source_count = negative_payment_groups + negative_charge_groups

    title_iv_to_older = _money(sum((
        transfer["amount"] for transfer in transfers
        if transfer["source"]["is_title_iv"]
        and transfer["source"]["fiscal_year_start"] > transfer["charge"]["fiscal_year_start"]
    ), ZERO))
    unrestricted_to_older = _money(sum((
        transfer["amount"] for transfer in transfers
        if not transfer["source"]["is_title_iv"]
        and transfer["source"]["term_sort"] > transfer["charge"]["term_sort"]
    ), ZERO))

    previous_balance = _money(sum((
        row["accounting_amount"] or ZERO for row in eligible_transactions
        if row["term_code"] == parameters.previous_term
    ), ZERO))
    prior_balance = _money(sum((
        row["accounting_amount"] or ZERO for row in eligible_transactions
        if row["term_sort"] < previous_sort
    ), ZERO))

    current_fdpl = [
        source for source in payment_sources
        if source["term_code"] == parameters.target_term and source["detail_code"] == "FDPL"
    ]
    fdpl_amount = _money(sum((source["source_amount"] for source in current_fdpl), ZERO))
    fdpl_aid_years = sorted({source["aidy_code"] for source in current_fdpl if source["aidy_code"] is not None})

    auth_summaries: dict[str | None, dict[str, Any]] = {}
    parent_fdpl_amount = ZERO
    missing_auth_count = 0
    conflicting_auth_count = 0
    student_fdpl_count = 0
    parent_fdpl_count = 0
    for aid_year in sorted({source["aidy_code"] for source in selected_sources if source["detail_code"] == "FDPL"}, key=lambda item: item or ""):
        matches = [row for row in authorization_rows if _text(row.get("plus_auth_aidy_code")) == aid_year]
        values = [_text(row.get("plus_to_student"), upper=True) for row in matches]
        y_count = sum(value == "Y" for value in values)
        n_count = sum(value == "N" for value in values)
        invalid_count = sum(value not in {"Y", "N"} for value in values)
        if not matches:
            status = "MISSING"
            missing_auth_count += 1
        elif invalid_count or (y_count and n_count) or not (y_count or n_count):
            status = "CONFLICT"
            conflicting_auth_count += 1
        elif y_count:
            status = "Y"
            student_fdpl_count += 1
        else:
            status = "N"
            parent_fdpl_count += 1
        raw_values = sorted({value if value is not None else "[blank]" for value in values})
        auth_summaries[aid_year] = {
            "status": status,
            "row_count": len(matches),
            "raw": ", ".join(raw_values) if raw_values else "[missing]",
            "activity": _max_datetime(row.get("plus_auth_activity_date") for row in matches),
        }
        if status == "N":
            parent_fdpl_amount += sum((
                source["source_credit_amount"] for source in selected_sources
                if source["detail_code"] == "FDPL" and source["aidy_code"] == aid_year
            ), ZERO)

    if not auth_summaries:
        plus_status = "NOT_APPLICABLE"
    elif missing_auth_count:
        plus_status = "MISSING"
    elif conflicting_auth_count:
        plus_status = "CONFLICT"
    elif student_fdpl_count and parent_fdpl_count:
        plus_status = "MIXED"
    elif student_fdpl_count:
        plus_status = "Y"
    else:
        plus_status = "N"

    plus_auth_count = sum(summary["row_count"] for summary in auth_summaries.values())
    plus_auth_raw = " | ".join(
        f"{aid_year or '[no aid year]'}: {summary['raw']}"
        for aid_year, summary in auth_summaries.items()
    ) or None
    plus_auth_activity = _max_datetime(summary["activity"] for summary in auth_summaries.values())

    split_blocked = any((
        invalid_priority_count,
        missing_amount_count,
        invalid_term_count,
        future_term_count,
        special_priority_mismatch_count,
        negative_net_source_count,
        missing_auth_count,
        conflicting_auth_count,
        policy_credit_mismatch,
        ledger_residual != ZERO,
    ))
    if split_blocked:
        parent_amount = None
        student_amount = None
    else:
        parent_amount = _money(min(account_credit, parent_fdpl_amount))
        student_amount = _money(account_credit - parent_amount)

    cwid_upper = (account["cwid"] or "").upper()
    third_party = cwid_upper.startswith("TPS") or cwid_upper in legacy_third_party_cwids
    refund_hold = account["refund_hold_count"] > 0
    active_ed = account["active_ed_row_count"] > 0
    student_delivery, delivery_values = _student_delivery(
        student_amount,
        selected_sources,
        run_date=parameters.run_date,
        refund_hold=refund_hold,
        third_party=third_party,
        active_ed=active_ed,
    )
    if policy_credit_mismatch:
        known_student_policy_amount = _money(max(policy_unused_total - parent_fdpl_amount, ZERO))
        student_delivery = (
            "REAPPLICATION REQUIRED" if known_student_policy_amount > 0 else "NONE"
        )
        parent_delivery = (
            "REAPPLICATION REQUIRED" if parent_fdpl_amount > 0 else "NONE"
        )
    elif (parent_amount or ZERO) > 0 and plus_status in {"N", "MIXED"}:
        parent_delivery = "RFDP"
    elif (parent_amount or ZERO) > 0:
        parent_delivery = "PARENT_PLUS_AUTH_REVIEW"
    else:
        parent_delivery = "NONE"

    allocation_review = (
        split_blocked
        or missing_balance_count > 0
        or stored_difference_count > 0
        or unpaid_charges > 0
        or policy_credit_mismatch
        or ledger_residual != ZERO
    )
    raw_refund = (account["raw_refund_account_ind"] or "").upper()
    refund_selected = "Y" if raw_refund == "Y" else "N" if raw_refund in {"", "N"} else "UNKNOWN"

    original_sources = [source for source in selected_sources if source["detail_code"] in ORIGINAL_PAYMENT_CODES]
    original_total = _money(sum((source["source_credit_amount"] for source in original_sources), ZERO))
    original_detail = " | ".join(
        f"{source['term_code']} / {source['detail_code']} / priority {source['effective_priority_code']} / "
        f"tran {source['tran_number']} / {_format_money(source['source_credit_amount'])}"
        for source in sorted(original_sources, key=lambda item: (item["term_sort"], item["tran_number"]))
    ) or None
    balance_sources = " | ".join(
        f"{source['effective_priority_code']} / {source['term_code']} / tran {source['tran_number']} / "
        f"{source['detail_code']} ({source['detail_desc'].strip()}) / {source['fund_type']} / "
        f"remaining {_format_money(source['source_credit_amount'])}"
        for source in selected_sources
    ) or None

    reasons = _join_reasons([
        "MISSING_OR_INVALID_DETAIL_PRIORITY" if invalid_priority_count else None,
        "MISSING_TRANSACTION_AMOUNT" if missing_amount_count else None,
        "MISSING_TRANSACTION_BALANCE" if missing_balance_count else None,
        "STORED_BALANCE_DIFFERS_FROM_RECONSTRUCTED_ALLOCATION" if stored_difference_count else None,
        "UNRECOGNIZED_TERM_CODE" if invalid_term_count else None,
        "FUTURE_TERM_ACTIVITY_EXCLUDED_FROM_ALLOCATION" if future_term_count else None,
        "ARTIFICIAL_PRIORITY_DETAIL_CODE_HAS_UNEXPECTED_BASE_PRIORITY" if special_priority_mismatch_count else None,
        "NEGATIVE_NET_SOURCE_REQUIRES_REVIEW" if negative_net_source_count else None,
        "UNPAID_CHARGES_AFTER_POLICY_ALLOCATION" if unpaid_charges > 0 else None,
        "POLICY_REFUND_DIFFERS_FROM_FULL_ACCOUNT_CREDIT" if policy_credit_mismatch else None,
        "ALLOCATION_LEDGER_DOES_NOT_RECONCILE_TO_INCLUDED_TRANSACTIONS" if ledger_residual != ZERO else None,
        "REFUND_HOLD_RH" if refund_hold else None,
        "DECEASED_PERSON" if (account["deceased_ind"] or "").upper() == "Y" else None,
        "THIRD_PARTY_ACCOUNT_REVIEW_REQUIRED" if third_party else None,
        "CURRENT_SPRIDEN_MISSING" if account["cwid"] is None else None,
        f"TBBACCT_ROW_COUNT_{account['account_control_row_count']}" if account["account_control_row_count"] != 1 else None,
        f"MULTIPLE_ACTIVE_ED_ROWS_{account['active_ed_row_count']}" if account["active_ed_row_count"] > 1 else None,
        "PLUS_AUTH_RECORD_MISSING" if plus_status == "MISSING" else None,
        "PLUS_AUTH_VALUES_CONFLICT" if plus_status == "CONFLICT" else None,
        "REVIEW_ACH_CC_IN_TRANSACT" if original_sources else None,
        "ACHK_CLEARING_PERIOD_NOT_MET" if delivery_values["ach_wait"] > 0 else None,
        "ACHK_OVER_180_DAYS_MAY_BE_TOO_OLD_FOR_ORIGINAL_METHOD" if delivery_values["ach_old"] > 0 else None,
        "ACHK_EFFECTIVE_DATE_MISSING_OR_FUTURE" if delivery_values["ach_date_review"] > 0 else None,
    ])

    if policy_credit_mismatch:
        review_status = "REAPPLICATION_REQUIRED"
    elif refund_hold:
        review_status = "HOLD"
    elif allocation_review:
        review_status = "MANUAL_REVIEW"
    elif (account["deceased_ind"] or "").upper() == "Y" or third_party or account["cwid"] is None:
        review_status = "MANUAL_REVIEW"
    elif account["account_control_row_count"] != 1 or account["active_ed_row_count"] > 1:
        review_status = "MANUAL_REVIEW"
    elif plus_status in {"MISSING", "CONFLICT"} or delivery_values["ach_date_review"] > 0:
        review_status = "MANUAL_REVIEW"
    elif delivery_values["ach_wait"] > 0:
        review_status = "WAIT_ACH_CLEARING"
    elif original_sources:
        review_status = "TRANSACT_REVIEW"
    else:
        review_status = "READY_FOR_STAFF_REVIEW"

    result = {
        "cwid": account["cwid"],
        "last_name": account["last_name"],
        "first_name": account["first_name"],
        "full_account_balance": full_balance,
        "total_refund_amount": account_credit,
        "proposed_student_delivery": student_delivery,
        "student_refund_amount": student_amount,
        "proposed_parent_delivery": parent_delivery,
        "parent_refund_amount": parent_amount,
        "balance_sources": balance_sources,
        "plus_to_student_status": plus_status,
        "parent_plus_target_term": parameters.target_term,
        "refund_split_status": "REAPPLICATION_REQUIRED" if policy_credit_mismatch else "UNDETERMINED_SEE_REVIEW_REASONS" if student_amount is None else "CALCULATED_SUBJECT_TO_REVIEW",
        "third_party_review_required_ind": "Y" if third_party else "N",
        "third_party_match_source": "TPS_CWID_PREFIX" if cwid_upper.startswith("TPS") else "LEGACY_CWID_LIST" if third_party else None,
        "refund_hold_ind": "Y" if refund_hold else "N",
        "raw_delinquency_code": account["raw_delinquency_code"],
        "active_ed_ind": "Y" if active_ed else "N",
        "raw_refund_account_ind": account["raw_refund_account_ind"],
        "refund_account_selected_ind": refund_selected,
        "fdpl_row_count": len(current_fdpl),
        "target_term_fdpl_amount": fdpl_amount if current_fdpl else None,
        "fdpl_aidy_code": ", ".join(fdpl_aid_years) if fdpl_aid_years else None,
        "fdpl_priority_tie_rule": "EFFECTIVE_PRIORITY_THEN_EARLIEST_TRAN_NUMBER",
        "unused_fdpl_amount": unused_fdpl,
        "unused_non_fdpl_amount": unused_non_fdpl,
        "total_unused_payment_amount": policy_unused_total,
        "unpaid_charge_amount": unpaid_charges,
        "allocation_review_required_ind": "Y" if allocation_review else "N",
        "previous_term_balance_before_current_payments": previous_balance,
        "prior_terms_balance_before_current_payments": prior_balance,
        "title_iv_applied_to_older_fiscal_years": title_iv_to_older,
        "unrestricted_applied_to_older_terms": unrestricted_to_older,
        "original_payment_row_count": len(original_sources),
        "original_payment_total": original_total,
        "original_payment_detail": original_detail,
        "deceased_ind": account["deceased_ind"],
        "deceased_date": account["deceased_date"],
        "confidential_ind": account["confidential_ind"],
        "plus_auth_row_count": plus_auth_count,
        "plus_auth_raw_values": plus_auth_raw,
        "negative_source_count": negative_source_count,
        "ambiguous_source_pool_count": 0,
        "review_status": review_status,
        "review_reasons": reasons,
        "last_ar_activity_date": _max_datetime(row["activity_date"] for row in transactions),
        "account_control_activity_date": account["account_control_activity_date"],
        "ed_activity_date": account["ed_activity_date"],
        "plus_auth_activity_date": plus_auth_activity,
    }
    if policy_unused_total <= 0 and account_credit <= 0:
        return None
    return result


def allocate_refunds(
    transaction_frame: pd.DataFrame,
    context_frame: pd.DataFrame,
    parameters: RefundParameters,
    *,
    legacy_third_party_cwids: Iterable[str] = (),
) -> pd.DataFrame:
    """Calculate the refund review report from flat Banner extracts."""
    transactions = _normalize_columns(transaction_frame)
    context = _normalize_columns(context_frame)
    _validate_columns(transactions, TRANSACTION_COLUMNS, "Transaction")
    _validate_columns(context, CONTEXT_COLUMNS, "Context")

    normalized_transactions = [
        _normalize_transaction(row, source_id)
        for source_id, row in enumerate(transactions.to_dict("records"), start=1)
    ]
    transactions_by_pidm: dict[int, list[dict[str, Any]]] = defaultdict(list)
    for row in normalized_transactions:
        transactions_by_pidm[row["pidm"]].append(row)

    context_by_pidm: dict[int, list[dict[str, Any]]] = defaultdict(list)
    for row in context.to_dict("records"):
        context_by_pidm[_integer(row["pidm"])].append(row)

    legacy = {str(cwid).strip().upper() for cwid in legacy_third_party_cwids if str(cwid).strip()}
    report_rows = []
    for pidm, account_transactions in transactions_by_pidm.items():
        result = _allocate_account(
            account_transactions,
            context_by_pidm.get(pidm, []),
            parameters,
            legacy,
        )
        if result is not None:
            report_rows.append(result)

    report_rows.sort(key=lambda row: (
        row["last_name"] or "",
        row["first_name"] or "",
        row["cwid"] or "",
    ))
    return pd.DataFrame(report_rows, columns=REPORT_COLUMNS)
