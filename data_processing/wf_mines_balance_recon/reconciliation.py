"""Account-level W&F comparisons defined in GitHub issue #15."""
from __future__ import annotations

from decimal import Decimal, InvalidOperation, ROUND_HALF_UP

import pandas as pd

from .agency_reports import _amount


RECONCILIATION_HEADERS = (
    'CWID', 'First Name', 'Last Name', 'Banner Total Balance',
    'W&F Principal Amount', 'Difference', 'W&F Returned',
)
_CENT = Decimal('0.01')


def submission_fraction(value: object) -> Decimal:
    """Validate the commission fraction even when the GUI parser is bypassed."""
    try:
        fraction = Decimal(str(value))
    except (InvalidOperation, ValueError):
        raise ValueError('Submission Percentage must be a fraction between 0 and 1 (0.25 = 25%).') from None
    if not fraction.is_finite() or not 0 <= fraction <= 1:
        raise ValueError('Submission Percentage must be a fraction between 0 and 1 (0.25 = 25%).')
    return fraction


def add_principal_amount(collections: pd.DataFrame, percentage: object) -> pd.DataFrame:
    """Keep original balances; round fee-adjusted principals to cents, half up."""
    fraction = submission_fraction(percentage)
    result = collections.copy()
    principals = []
    for row in collections.to_dict('records'):
        amount = _amount(row['Orig. Balance'])
        if amount is not None and row['Type'] == 'Fees':
            amount = (amount / (1 + fraction)).quantize(_CENT, rounding=ROUND_HALF_UP)
        principals.append(amount)
    result['Principal Amount'] = principals
    if 'Orig. Balance' in result:
        columns = list(result.columns)
        columns.remove('Principal Amount')
        columns.insert(columns.index('Orig. Balance') + 1, 'Principal Amount')
        result = result[columns]
    return result


def _account_key(value: object) -> str:
    """Trim IDs without guessing prefixes or removing significant leading zeros."""
    if pd.isna(value) or isinstance(value, bool):
        raise ValueError('A reconciliation source has a missing or invalid CWID / Your Accnt #.')
    if isinstance(value, (int, float)) and value == int(value):
        value = str(int(value))
    key = str(value).strip()
    if not key:
        raise ValueError('A reconciliation source has a missing or invalid CWID / Your Accnt #.')
    return key


def reconcile_accounts(
    students: pd.DataFrame, collections: pd.DataFrame, returned: pd.DataFrame,
) -> pd.DataFrame:
    """Outer match by CWID; missing/unknown amounts never become a false zero.

    Multiple agency accounts sum their per-account rounded principals. A single
    unknown principal makes that CWID's aggregate unknown. Banner is already
    one row per CWID; duplicates indicate a bad combined export, not amounts to sum.
    """
    banner = {}
    for row in students.to_dict('records'):
        key = _account_key(row['CWID'])
        if key in banner:
            raise ValueError('The combined Banner report contains duplicate CWIDs; upload one row per account.')
        banner[key] = row
    agency: dict[str, Decimal | None] = {}
    for row in collections.to_dict('records'):
        key = _account_key(row['Your Accnt #'])
        amount = _amount(row['Principal Amount'])
        previous = agency.get(key, Decimal(0))
        agency[key] = previous + amount if previous is not None and amount is not None else None
    returned_keys = {_account_key(value) for value in returned.get('Your Accnt #', [])}
    records = []
    for key in dict.fromkeys((*banner, *agency)):
        row = banner.get(key, {})
        banner_amount = _amount(row.get('Total Balance'))
        agency_amount = agency.get(key)
        difference = (banner_amount - agency_amount
                      if banner_amount is not None and agency_amount is not None else None)
        records.append([
            key, row.get('First Name'), row.get('Last Name'), banner_amount,
            agency_amount, difference, int(key in returned_keys),
        ])
    return pd.DataFrame(records, columns=RECONCILIATION_HEADERS)
