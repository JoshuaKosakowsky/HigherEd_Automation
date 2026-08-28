# Student refund review

This family contains read-only queries for refund review and diagnostics.

## `Refunds.sql`

`Refunds.sql` is the operational decision-support report. It identifies fully
classified credit-balance accounts, evaluates refund holds and delivery
controls, reviews Parent PLUS ownership, flags third-party accounts, and emits a
staff review status. It does not approve or issue a refund.

The detailed confirmed controls and first-run reconciliation steps remain in
the header of the SQL file. Preserve those controls when changing the query.

### Priority allocation and temporary FDPL assumption

**Allocation is limited to `params.target_term`, which defaults to the current
term using the existing Mines term-date boundaries.** `target_term_override`
remains available for an intentional run for a different term. Charges,
payments, reversals, and issued refunds from other terms are excluded before
source grouping and are never reapplied to the target term.

The candidate population, `full_account_balance`, and `total_refund_amount`
still cover the full account. If target-term unused payments differ from that
full-account refund, the report retains the account, leaves recipient amounts
NULL, and flags `TARGET_TERM_ALLOCATION_DIFFERS_FROM_FULL_ACCOUNT_REFUND`.
This avoids ignoring another term's debit or silently assigning its credits.
Settled historical activity must not change the target-term split.

The report reads `TBBDETC_PRIORITY` through the existing detail-code join for
both charges and payments. Charges are processed in descending priority order;
each charge consumes eligible payments in descending payment priority order.
Each `0` in a payment priority matches any digit in the corresponding charge
priority position. Leading zeros are preserved; numeric-looking values with
one or two digits are padded to three digits. Invalid/missing priorities are
not treated as unrestricted payments. Transaction numbers and posting dates
are used only as reference information, not to allocate funds.

**TEMPORARY BUSINESS ASSUMPTION: FDPL applies last among payments with the same
priority (currently 800). This has not been confirmed as a Banner rule.**
The single setting `params.fdpl_last_at_same_priority = TRUE` implements this.
Change it to `FALSE` only if FDPL should apply first within the same priority;
a different rule requires revising the allocation and tests. Priorities are
read from the data, so the rule is not hard-coded to 800. The output column
`fdpl_priority_tie_rule` displays the active assumption on every report row.

Payments are pooled by priority and FDPL/non-FDPL ownership. A partially used
pool with multiple source groups cannot identify which individual sources
remain: it lists all possible sources, flags `SAME_PRIORITY_SOURCE_SPLIT_UNRESOLVED`,
and keeps the account in manual review. Ambiguity among non-FDPL sources does
**not** suppress the expected parent/student totals: those sources share the
same side of the ownership split. This avoids adding an unconfirmed tie rule
for other payments while retaining calculable recipient totals. Fully used or
wholly unused pools are unambiguous.

`student_refund_amount` and `parent_refund_amount` appear immediately after
`total_refund_amount`. These are expected amounts, not approval to issue a refund.
The output starts with CWID, last name, first name, full-account balance, total
refund, student refund, parent refund, and balance sources, followed by the
authorization and review details. `banner_pidm`, `target_term_fdpl_tran_number`,
`calculated_parent_plus_credit`, and `invalid_priority_count` are omitted from
the displayed output; the internal calculations and validation checks remain.
`refund_split_status` distinguishes `CALCULATED_SUBJECT_TO_REVIEW` from
`UNDETERMINED_SEE_REVIEW_REASONS`. Source, authorization, delivery, and hold
reviews remain separate from displaying the expected split. When the split
itself cannot be determined, the amounts stay NULL and `review_reasons` explains
the blockers; unknown amounts are never displayed as zero.

Target-term reversals are netted within the same detail code, term, and aid year.
Negative net groups, missing priorities, unpaid charges, and unmatched
reconciliation require manual review; the account remains
in the report, but proposed parent/student amounts are NULL. Existing multiple
target-term FDPL and authorization checks remain in place. The allocation uses
current detail-code configuration within the target term, not historical
priority snapshots or Banner's stored application records; reconcile against
actual Banner application before operational use.

`balance_sources` describes unused target-term priority pools and their exact
remaining amounts, not the newest posted payments. ACH/card review follows
those same target-term pools; historical card payments are not selected again.
If an ACH/card pool's individual source amounts are unresolved,
`original_payment_total` is NULL rather than a fabricated amount. Its row count
now counts net source groups (detail code/term/aid year), not original transactions.

The obsolete output columns `credits_after_target_term_fdpl`,
`credits_after_target_term_fdpl_detail`, and `later_payment_count` were removed.
Their replacements include `unused_fdpl_amount`, `unused_non_fdpl_amount`,
`total_unused_payment_amount`, `unpaid_charge_amount`, and allocation review
indicators. Update saved report consumers that referenced the removed columns.

The approved synthetic example has $7,500 in charges and $9,500 in payments:
tuition 899/$6,000, fees 897/$1,000, other charge 700/$500; payments
899/$2,000, 890/$1,500, FDPL 800/$4,000, and 000/$2,000. Its remaining funds
are $500 FDPL and $1,500 non-FDPL, regardless of transaction numbering.

## `Refund_info.sql`

`Refund_info.sql` is a small diagnostic that returns up to 20 `TBBACCT` rows
whose delinquency code is `RH`. It is not the refund population and should not
be used as a refund-eligibility report.

## `Refund_allocation_diagnostic.sql`

Use this diagnostic when the expected parent/student split disagrees with the
report. Set `params.cwid` locally to the affected account; the default NULL
returns no rows. Do not save or commit the identifier or production results.
The output omits names and identifiers but still contains student financial data.

Unlike the allocation report, this diagnostic intentionally retains all terms.
It returns each detail-code/term/aid-year group, its current charge/payment type
and priority, raw net transaction amount, raw net stored balance, and counts
for positive, negative, and missing amounts. It includes the full account and
zero-net groups so prior-term activity and reversals remain visible.
It does not treat stored balances as a replacement allocation rule or calculate
refund ownership. Compare the inputs with the manual calculation before changing
priority order, term scope, or the treatment of already-applied payments.

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

## Automated verification

The existing `tests/python/test_refunds_query.py` contains contract checks and
optional behavioral tests that execute the full report against synthetic
PostgreSQL temporary tables. The tests do not require Banner access or production
credentials, and roll back all fixture data. Use an isolated test database:

```sh
REFUNDS_TEST_DSN='host=localhost dbname=refunds_test user=refunds_test' \
  python -m unittest discover -s tests/python -p test_refunds_query.py -v
```

`psql` must be on PATH, or set `REFUNDS_TEST_PSQL` to its executable path.
Without `REFUNDS_TEST_DSN`, the PostgreSQL tests explicitly skip; contract tests
alone do not verify allocation correctness. Coverage includes the worked
example, changing the FDPL tie setting, priorities other than 800, transaction
order independence, wildcard matching, reversals, unresolved sources, exact
cents, account isolation, settled prior/future terms, cross-term balance
mismatches, and existing authorization/hold controls.
