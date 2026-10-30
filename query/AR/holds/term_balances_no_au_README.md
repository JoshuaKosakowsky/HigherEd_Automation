# Term balances > 0 and no AU hold

Added in **0.26.0** for [issue #21](https://github.com/JoshuaKosakowsky/HigherEd_Automation/issues/21).
`term_balances_no_au.sql` is the shared read-only query for native Insights and
the app. These rules include the owner's clarifications during implementation.
It supplies a review list and projected totals; it does not apply holds, post
late fees, transfer payments, or establish eligibility to charge a fee.

## Population and term window

There is one row per student and selected term with a positive net term amount.
A student is an account with any `SGBSTDN` history; current enrollment is not
required, and multiple student-history rows cannot duplicate results. Other
account types are excluded. Current `SPRIDEN` supplies CWID and names.

The database's `CURRENT_DATE` selects the current Mines term and the two
immediately preceding configured terms, including Summer:

- Spring `YYYY10`: January 1 through May 15.
- Summer `YYYY55`: May 16 through July 15.
- Fall `YYYY80`: July 16 through December 31.

For example, Fall 2026 selects `202680`, `202655`, and `202610`; Spring 2027
selects `202710`, `202680`, and `202655`. The SQL uses the same boundaries as
`config/institutions/mines/banner_terms.json`; synthetic tests compare it to
the shared term resolver at every seasonal boundary. No term input is required.
An absent term produces no row. A zero or negative known term amount produces
no row. The all-term account balance does not restrict the population.

## Financial rules and cross-term review

`TBBDETC_TYPE_IND` classifies charges (`C`) and payments/credits (`P`).
Codes are trimmed and compared without case sensitivity. For each term:

```text
Amount = ROUND(SUM(charge TBRACCD_AMOUNT) - SUM(payment TBRACCD_AMOUNT), 2)
Amount w/ LF = ROUND(Amount * 1.015, 2)
```

Original transaction signs remain intact, including reversals. This does not
sum remaining `TBRACCD_BALANCE`. `Amount w/ LF` is the projected **total including
the 1.5% fee**, not the fee alone, and is calculated independently for each term.
Posted fees already in term charges remain in Amount; no detail codes are
silently exempted. No minimum balance, due-date test, billing-month restriction,
or payment-type allocation policy is inferred.

`Account Balance` is net charges minus payments across **all terms**, including
older history, future terms, and terms outside the three-term output window.
Raw amounts are aggregated before rounding the account total to cents. This
account-level context repeats on each student's rows: **do not sum it across
the exported term rows**.

Any term with a negative net amount sets `Cross-Term Credit` to `Yes` for that
account. All its reported term amounts remain unchanged, and **every reported
Amount w/ LF is blank**, including when the account balance is zero or negative.
`Review Notes` explains that payment application needs review. Credits are not
allocated to a different term or assumed freely transferable; payment
restrictions and Banner's actual application still need investigation. This
flag is based on net posted term activity, not proof of unused cash or a
correct destination term. A payment that only reduces a positive amount in
its own term does not create a cross-term flag.

## Hold rules

Any `AU` record with a calendar **end date strictly after today** excludes the
whole account. Its start date is intentionally ignored, including a future
start. A hold ending today is not current, even if its timestamp is later
today. The owner states AU holds have end dates; a NULL end does not satisfy
this comparison. Hold codes are trimmed and case-insensitive.

PP accounts remain included. `PP Hold` displays `PP` for the existing delinquency
report's active-PP definition: start date today or earlier (or NULL), and end
date strictly after today, ignoring time of day. Expired or future-start PP
records do not set the indicator. Multiple PP records cannot duplicate rows.
PP alone does not blank the fee projection or prove fee eligibility; the
owner requested these accounts remain visible for discussion. No additional
CO, RH, other-hold, or current-enrollment exclusion is applied.

## Missing or ambiguous data

Unmapped, unknown, or duplicate detail-code metadata and missing transaction
amounts are never assumed zero. An affected selected term remains as an
exception row with blank Amount and fee projection and a review note, even
though its positivity cannot be established. Account Balance is blank when
any account activity has uncomputable amounts. Known positive selected terms
remain visible when the error occurs elsewhere in the account.

Missing transaction terms also require review. Known amounts still contribute
to Account Balance, but fee projections are blank. `Cross-Term Credit` is
`Unknown` when missing data prevents a reliable conclusion and no known credit
term exists; a known negative term still yields `Yes`.

Accounts with missing current identities remain visible with blank identity
fields. Duplicate current identities produce one deterministic displayed
identity, not duplicated monetary rows. Both cases have review notes and blank
fee projections. Do not combine blank CWIDs as one person.

## Output and application integration

Columns are `CWID`, `Last Name`, `First Name`, `Term`, `Amount`, `Amount w/ LF`,
`Account Balance`, `Cross-Term Credit`, `PP Hold`, and `Review Notes`.
Results sort by last name, first name, CWID, then newest selected term first.
`Report Row Count` is an internal completeness control, counting term/exception
rows rather than distinct students. The app removes it from the workbook.

Administrators select **Connections → Holds — Term balances > 0 and no AU hold**,
choose TEST or PROD explicitly, and export to a new `.xlsx` file. The existing
Insights service rechecks administrator access, validates the complete row
count, preserves blank fee projections, and refuses to overwrite a workbook.
No new authentication, permissions, workflow runner, or workbook formatter is
introduced. Native Insights runs the exact same SQL without template variables.

## Synthetic acceptance examples

| Posted activity | Expected output |
| --- | --- |
| Fall charges 30,000; Fall payments 15,000; no other activity | Fall Amount 15,000; account 15,000; fee-inclusive total 15,225 |
| Summer charges 1,000; Fall charges 500; no credits | Two rows; fee-inclusive totals 1,015 and 507.50; repeated account balance 1,500 |
| Fall net 15,000; Summer net -15,000 | Fall row retained at 15,000; account 0; Cross-Term Credit Yes; fee projection blank |
| Summer net 1,000; Fall net 500; Spring net -100 | Two positive rows retained unchanged; account 1,400; both fee projections blank |
| Fall net 1,000; credit -300 outside the output window | Fall Amount 1,000; account 700; Cross-Term Credit Yes; fee projection blank |
| Positive selected term plus current AU ending tomorrow | Account excluded, even with a future AU start |
| Positive selected term plus AU ending today | Included; AU is not current under the strict end-date rule |
| Positive selected term plus active PP | Included with PP indicator; fee projection remains unless another review condition exists |

## Configure and validate

1. Run `validate_hold_schema.sql` in the intended Insights database, including
   the added `TBRACCD_TERM_CODE` field, and resolve missing fields.
2. Paste the full SQL into a native Insights question in the Banner database.
   No variables are needed. Save and grant intended staff access through the
   normal owner-managed Insights process.
3. Reconcile representative term and all-term amounts to TSAAREV and AU/PP end
   dates to SOAHOLD. Include the cross-term zero-account example, partial and
   older/future credits, payment/charge reversals, and unknown-data exceptions.
4. Check the projected totals and blank-review cells in both Insights and an
   app workbook before operational use. Allow for Insights replication lag.

Synthetic tests execute the actual SQL in SQLite with only date syntax/clock
adaptations and helper functions for date construction/concatenation. SQLite
uses floating-point arithmetic; these tests do not establish PostgreSQL NUMERIC
half-cent rounding, real schema correctness, production performance, or live
payment application. Export tests use mocked Insights results and real workbook
files; they do not authenticate to Banner or Insights.
