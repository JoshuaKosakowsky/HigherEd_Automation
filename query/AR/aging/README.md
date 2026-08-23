# Receivable aging dashboard

These four SQL files are separate Insights dashboard cards over the same ODS
population:

- `0-30Days.sql`: 0 through 30 days, inclusive
- `31-60Days.sql`: 31 through 60 days, inclusive
- `61-90Days.sql`: 61 through 90 days, inclusive
- `91+Days.sql`: 91 days or more

Together they cover every non-future positive balance without overlapping.
Each card returns one summed value rather than account-level detail.

## Data model

- `ODSMGR.RECEIVABLE_ACCOUNT_DETAIL` supplies transaction balance and bill,
  due, and effective dates.
- `ODSMGR.RECEIVABLE_ACCOUNT` supplies account-level fields used by optional
  Insights filters.
- The two views are joined by both `ACCOUNT_UID` and `ID`.

Run `validate_aging_schema.sql` first. It checks the columns referenced directly
by the SQL. The optional filters are Insights field-filter variables, so their
saved-question mappings must also be reviewed in the Insights interface.

## Required parameters

- `p_RunDate`: date used to calculate age
- `p_DateColumnType`: text containing `bill`, `due`, or `effective`

Optional filters are `p_detailcode`, `p_accountentityind`, `p_academicperiod`,
and `p_category`. They must remain configured as field filters for the bracketed
optional clauses to work.

The date-column parameter currently uses substring matching. Supply one clear
value such as `Bill Date`, `Due Date`, or `Effective Date`; a value containing
more than one keyword is ambiguous.

## First-run validation

1. Run all four cards with the same run date, date type, and filters.
2. Confirm boundary items aged exactly 30, 31, 60, 61, 90, and 91 days appear
   in exactly one card.
3. Confirm future-dated and zero/negative balances are intentionally excluded.
4. Reconcile the sum of all four cards to an account-level ODS extract using
   the same filters.
