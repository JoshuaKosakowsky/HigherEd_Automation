# Student refund review

This family contains read-only queries for refund review and diagnostics.

## `Refunds.sql`

`Refunds.sql` is the operational decision-support report. It identifies fully
classified credit-balance accounts, evaluates refund holds and delivery
controls, reviews Parent PLUS ownership, flags third-party accounts, and emits a
staff review status. It does not approve or issue a refund.

The detailed confirmed controls and first-run reconciliation steps remain in
the header of the SQL file. Preserve those controls when changing the query.

### Stored application balances and priority context

**Source ownership is limited to `params.target_term`, which defaults to the current
term using the existing Mines term-date boundaries.** `target_term_override`
remains available for an intentional run for a different term. Transactions
from other terms are not replayed into the target term.

The candidate population, `full_account_balance`, and `total_refund_amount`
still cover the full account. If target-term negative payment balances differ from that
full-account refund, the report retains the account, leaves recipient amounts
NULL, and flags `TARGET_TERM_STORED_BALANCES_DIFFER_FROM_FULL_ACCOUNT_REFUND`.
This avoids ignoring another term's debit or silently assigning its credits.
Settled historical activity must not change the target-term split.

The report now uses each target-term transaction's `TBRACCD_BALANCE` after
Banner application. A negative payment balance is an unapplied refund source;
a positive charge balance is an unpaid charge. This preserves corrections made
when staff manually apply payments because configuration or prior application
is wrong. Original transaction amounts still determine the full-account balance,
but they are not replayed to infer which payment remains.

`TBBDETC_PRIORITY` remains visible beside each remaining source as configuration
context. A missing or malformed priority requires review but does not override
a reconciled stored balance. The former FDPL same-priority tie assumption has
been retired. The existing output column `fdpl_priority_tie_rule` now returns
`NOT_APPLICABLE_BALANCE_BASED_SOURCE` so saved output consumers do not break.

The output places `proposed_student_delivery` immediately after
`total_refund_amount` and `proposed_parent_delivery` immediately after
`student_refund_amount`. These are proposed delivery detail codes, not approval
to issue a refund. A parent amount with PLUS-to-student status `N` uses `RFDP`.
A student amount without a refund hold uses `ARFD (System)` when an active ED
record exists and `RFND (CHECK)` otherwise. A refund hold displays
`Refund Hold - Student`.

Remaining `ACHK` sources use `TBRACCD_EFFECTIVE_DATE` as the posting-date basis.
Amounts more than 16 days old and less than 90 days old are netted with all ACHK
activity in that same window, including reversals, before `AFRD (Transact)` is
proposed. Recent ACHK balances display `ACHK Clearing Wait`; a partial net or an
unusable date requires review. A remaining `CRVC` source uses `CRVC (Transact)`
without an age delay. When a student refund spans more than one route, the
delivery column lists each route with its allocated amount.

`banner_pidm`, `target_term_fdpl_tran_number`,
`calculated_parent_plus_credit`, and `invalid_priority_count` are omitted from
the displayed output; the internal calculations and validation checks remain.
`refund_split_status` distinguishes `CALCULATED_SUBJECT_TO_REVIEW` from
`UNDETERMINED_SEE_REVIEW_REASONS`. Source, authorization, delivery, and hold
reviews remain separate from displaying the expected split. When the split
itself cannot be determined, the amounts stay NULL and `review_reasons` explains
the blockers; unknown amounts are never displayed as zero.

Missing transaction balances, unexpected balance signs, unpaid charge balances,
and unmatched reconciliation require manual review; the account remains in the
report, but proposed parent/student amounts are NULL. Missing priorities are
reviewed without suppressing an otherwise reconciled split. Existing multiple
target-term FDPL and authorization checks remain in place. The report uses the
current stored application state; reconcile it against Banner before
operational use because the balance can be wrong until application is corrected.

`balance_sources` describes the exact target-term payment transactions with
negative stored balances. ACH/card review uses the exact remaining balance on
those transactions; historical card payments are not selected again.

The obsolete output columns `credits_after_target_term_fdpl`,
`credits_after_target_term_fdpl_detail`, and `later_payment_count` were removed.
Their replacements include `unused_fdpl_amount`, `unused_non_fdpl_amount`,
`total_unused_payment_amount`, `unpaid_charge_amount`, and allocation review
indicators. Update saved report consumers that referenced the removed columns.

The synthetic regression example has $7,500 in charges and $9,500 in payments.
Its stored payment balances identify $500 FDPL and $1,500 non-FDPL as the
remaining sources, regardless of transaction numbering or priority order.

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
It does not calculate refund ownership. Compare its stored balances with the
manual Banner application before relying on the operational report.

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
alone do not verify source-split correctness. Coverage includes stored-balance
ownership, both completed-team patterns using synthetic amounts, transaction
order independence, reversals, exact cents, account isolation, settled prior
terms, cross-term balance mismatches, authorization/hold controls, delivery-code
routing, ACHK age boundaries and net returns, and immediate CRVC routing.
