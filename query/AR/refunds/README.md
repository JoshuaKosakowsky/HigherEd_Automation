# Student refund review

This family contains two read-only queries with different purposes.

## `Refunds.sql`

`Refunds.sql` is the operational decision-support report. It identifies fully
classified credit-balance accounts, evaluates refund holds and delivery
controls, reviews Parent PLUS ownership, flags third-party accounts, and emits a
staff review status. It does not approve or issue a refund.

The detailed confirmed controls and first-run reconciliation steps remain in
the header of the SQL file. Preserve those controls when changing the query.

## `Refund_info.sql`

`Refund_info.sql` is a small diagnostic that returns up to 20 `TBBACCT` rows
whose delinquency code is `RH`. It is not the refund population and should not
be used as a refund-eligibility report.

## Run order and validation

1. Run `validate_refund_schema.sql` and resolve every `MISSING` result.
2. Follow the first-run validation checklist at the top of `Refunds.sql`.
3. Confirm full-account balances against TSAAREV without a term restriction.
4. Confirm Parent PLUS results using the aid-year code on the target-term FDPL
   transaction.
5. Treat every `MANUAL_REVIEW`, `HOLD`, `TRANSACT_REVIEW`, or `ACTION_REQUIRED`
   row as unresolved until a staff member completes the indicated review.
6. Rerun immediately before taking any action because account state can change.

The schema inventory checks structure only; it cannot confirm local policy
meanings, detail-code ownership, or the legacy third-party CWID list.
