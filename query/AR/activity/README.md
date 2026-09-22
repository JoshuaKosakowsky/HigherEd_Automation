# Accounts Receivable activity reports

These reports read Banner account transactions from `TBRACCD` and current
identity information from `SPRIDEN`.

## Reports

### `Current_month_activity.sql`

Returns every transaction whose feed date is on or after the first day of the
current month. `TBBDETC` supplies the description, category, charge/payment
indicator, and priority. The displayed `Balance` is the transaction-level
`TBRACCD_BALANCE`, not a calculated full-account balance.

### `Last_month_activity.sql`

Returns the same transaction detail for the previous calendar month, using a
feed-date range from the first of last month through the start of this month.

### `Current_month_payment_activity.sql`

Returns current-month activity for a maintained list of payment detail codes
plus `CFEE`. `CFEE` is labeled as a credit-card fee rather than a payment.

### `Last_month_payment_activity.sql`

Uses the same payment detail-code list and `CFEE` classification for the
previous calendar month's feed dates.

The query currently uses a hard-coded detail-code list. Before broadening it to
category-based selection, confirm the intended Banner detail-code category and
the special treatment of `CFEE`.

### `Current_month_loan_activity.sql`

Returns selected loan detail codes from a historical feed-date window beginning
two months before the current month and ending at the start of the current
month. Despite the filename, it does not currently return current-month rows.

This query also contains placeholder empty detail codes and groups by the raw
amount before applying `SUM`. Those behaviors are preserved pending business
validation; do not interpret its output as a fully consolidated loan total.

## Run order and validation

1. Run `validate_activity_schema.sql` and resolve every `MISSING` result.
2. Reconcile a small date range to TSAAREV or an authoritative TBRACCD extract.
3. Confirm the payment and loan detail-code lists with the report owner.
4. Confirm whether `FEED_DATE`, rather than entry, effective, or activity date,
   is the intended operational date for each report.
5. Check that current `SPRIDEN` filtering returns one identity row per PIDM.
