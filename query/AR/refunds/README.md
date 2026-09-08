# Student refund review

These read-only queries support refund review. They do not approve or issue a
refund and do not create Transact or TSARFND files.

## Recommended workflow: manual SQL downloads plus local Python allocation

Run these two flat, non-recursive files in the Insights website and download the
complete result of each as XLSX or CSV:

- `refund_transactions_manual.sql` reads account transactions and current
  detail-code configuration.
- `refund_context_manual.sql` reads identity, account controls, ED status, and
  Parent PLUS authorization.

Python then performs the priority, fiscal-year, Title IV, Parent PLUS, and
delivery calculations locally and creates an Excel workbook under
`data/refunds`. That directory and its CSV extracts are ignored by Git because
they contain student-account data.

The workbook separates refund methods and review queues into plain worksheets,
without Excel tables. For mixed refunds, use `tab_refund_amount` for each tab's
portion; account totals repeat as context. See the
[workbook tab guide](../../../workflows/refunds/README.md#workbook-tabs).

Rename the files `refund_transactions.xlsx` and `refund_context.xlsx`, then put
them in `data\refunds\input`. From the repository root on the work laptop, run:

```powershell
.\launcher\run_refunds.ps1 `
    -TargetTerm 202680 `
    -TransactionsFile ".\data\refunds\input\refund_transactions.xlsx" `
    -ContextFile ".\data\refunds\input\refund_context.xlsx"
```

After running `setup.ps1` again to install the updated shortcuts, the equivalent
command is:

```powershell
start-refunds `
    -TargetTerm 202680 `
    -TransactionsFile ".\data\refunds\input\refund_transactions.xlsx" `
    -ContextFile ".\data\refunds\input\refund_context.xlsx"
```

The files can remain in Downloads if their complete paths are passed instead.
The `data\refunds\input` location is recommended because it is easy to find and
XLSX/CSV data is excluded by `.gitignore`.

For one-account validation, populate the same `cwid_filter` inside both manual
SQL files. Leave it NULL for a population run. The downloaded files record their
target term and total expected row count; Python rejects mismatched terms or a
truncated download.

Candidate selection is shared in `refund_scope.sql`: target-term activity,
qualifying HOMP charges, or a negative stored payment balance within two years
of terms. Known positive full-account balances are excluded. Selected accounts
retain all transaction history; the two-year condition is not a replay cutoff.
Python can report zero-net accounts with restricted refunds and offsetting
unpaid charges. See [the workflow rules](../../../workflows/refunds/README.md)
for current delivery, ownership, housing, and third-party review behavior.

Re-download both exports after this change. To maintain the standalone manual
SQL, edit the extract templates or shared scope, then regenerate from the
repository root:

```python
from data_processing.refunds.extract import QUERY_DIRECTORY, render_manual_extract_sql

for name in ("transactions", "context"):
    template = (QUERY_DIRECTORY / f"refund_{name}_extract.sql").read_text(encoding="utf-8")
    (QUERY_DIRECTORY / f"refund_{name}_manual.sql").write_text(
        render_manual_extract_sql(template), encoding="utf-8"
    )
```

Tests ensure checked-in manual exports match this shared source. Change manual
run settings for a specific run only; do not commit identifying filters.

### Optional API/batched mode

The repository can run the extraction automatically when its Insights API/SSO
connection is configured. This mode uses `refund_transactions_extract.sql` and
`refund_context_extract.sql` internally:

```powershell
start-refunds -TargetTerm 202680
```

The default is 20 batches. If any flat query is still slow, or the workflow
reports that Insights truncated a result, increase the batch count and start a
fresh extraction without `-Resume` because the PIDM partitions have changed:

```powershell
start-refunds -TargetTerm 202680 -BatchCount 50
```

Each completed batch is cached. After a failed connection or session, rerun the
same term and batch count with `-Resume`. The manifest prevents mixing a cache
from a different term, batch count, run date, policy version, or validation
account. For a later-day resume/offline run, use `-RunDate YYYY-MM-DD` with the
original extraction date. Older policy-version caches must be extracted again.

```powershell
start-refunds -TargetTerm 202680 -BatchCount 50 -Resume
```

For a one-account validation, use `-Cwid`. The workflow automatically uses one
batch and does not print the CWID in its progress messages.

```powershell
start-refunds -TargetTerm 202680 -Cwid TEST-CWID
```

To recalculate from an already complete cache without contacting Insights, add
`-Offline` and keep the same term, run date, and batch count. `Refunds.sql` remains
as a historical SQL reference. It does not implement the latest Python refund
policy and must not be used as an equivalent operational fallback.

## Legacy `Refunds.sql` reference (not the current Python rules)

`Refunds.sql` reconstructs payment application from transaction amounts,
current detail-code configuration, Mines fiscal-year policy, and the approved
priority rules. `TBRACCD_BALANCE` is retained as a diagnostic comparison because
Banner application may be wrong until staff correct it; it does not decide
refund ownership.

### Terms and fiscal years

`params.target_term` defaults from `run_date` using Mines boundaries: Spring
`10`, Summer `55`, and Fall `80`. The query also recognizes historical Summer
terms `50` and `60`. Use `target_term_override` for an intentional historical or
work-ahead run. Use `previous_term_override` only when a historical Fall should
point to Summer `60` rather than the modern `55`.

A fiscal year begins with Fall and ends with Summer. For example, fiscal year
2026 contains `202680`, `202710`, and `202755`; historical `50` and `60` terms
use the same rule. The immediately previous term has its own audit balance. All
older terms appear as one prior-term balance, while internal allocation still
retains fiscal years for the Title IV caps.

### Fund classification and cross-term rules

Payments use `TBBDETC_TIV_IND` and `TBBDETC_DCAT_CODE`:

- `TIV_IND = 'Y'` is Title IV and takes precedence over category.
- A non-Title-IV category beginning `FA` is unrestricted financial aid.
- `CSH` is cash.
- Remaining non-Title-IV categories are treated as other unrestricted funds.

Title IV may pay charges freely within its fiscal year. When it crosses a
fiscal-year boundary, each source fiscal year may give at most $200 total and
each destination fiscal year may receive at most $200 total. The two ledgers are
independent, and the oldest unpaid fiscal year is handled first. Non-Title-IV
aid and other unrestricted payments may cross terms and fiscal years without a
dollar cap. A prior surplus may pay current charges, but Title IV retains the
cross-fiscal-year cap.

`total_refund_amount` is the reconstructed unused payment amount. It can exceed
the absolute full-account credit when Title IV restrictions leave an older
charge unpaid. The unfiltered operational population first selects PIDMs with
target-term TBRACCD activity, then reads full account history only for those
PIDMs. Within that scope, candidates include accounts with a full-account
credit, a fiscal-year credit, or a negative target-term stored payment balance.
The final output removes candidates with neither a calculated refund nor a
full-account credit. This target-term scope is deliberate: an account cannot
have a current-term refund without current-term activity.

For a targeted validation run, set `params.cwid_filter` or
`params.last_name_filter`. Both are applied during account screening, before
historical allocation, so they reduce runtime rather than filtering only the
final display. A populated filter may also inspect an account without target-
term activity. Do not commit a populated CWID.

Balanced and debit pre-current fiscal years are carried into allocation as one
net fiscal-year amount. Source-level priority reconstruction runs only for a
pre-current fiscal year with an actual credit, because only such a year can
contribute a refundable historical source. Any remaining historical recursion
is partitioned by PIDM and fiscal year rather than growing across the account's
entire history. Account-level control and audit summaries are explicitly
materialized once; this prevents PostgreSQL from inlining them into the wide
final join and repeatedly rescanning the same Banner data.

### Priority application

Current charges apply from priority `999` downward. A payment priority uses
positional zeros as wildcards: `899` matches `899`, `890` matches `89x`, `800`
matches `8xx`, and `000` matches any charge.

Payments apply in this order:

1. `999` through `801`
2. artificial `800A`: `TPDT`, `TPPY`
3. regular `800`, including `FDPL`
4. `799` through `001`
5. artificial `000A`: `COFP`
6. regular `000`
7. artificial `000Z`: `ACHK`, `CRAM`, `CRDS`, `CRMC`, `CRVC`

The lowest `TBRACCD_TRAN_NUMBER` wins a tie within an effective priority. The
artificial suffix affects order only; charge eligibility always uses the base
three-digit `TBBDETC_PRIORITY`. If a listed detail code does not have its
expected base priority, the report flags the configuration instead of silently
changing eligibility.

Positive payments are netted with reversals within PIDM, term, aid year, and
detail code. Charge-side credits are netted within PIDM, term, and charge
priority. That distinction is necessary when Banner uses paired codes, such as
an insurance charge and waiver, that have different detail codes but the same
priority. A reversal reduces the newest positive transaction first, preserving
the earliest surviving transaction as the tie winner. A charge-priority pool
that remains negative after netting still requires review.

### Parent PLUS and delivery

Every unused `FDPL` source is matched to `RLRPAPP_PLUS_TO_STUDENT` by PIDM and
that source's aid year. `N` assigns it to the parent and `Y` assigns it to the
student. Missing, blank/invalid, or conflicting authorization prevents a split.
Multiple unused FDPL aid years are supported, including a mixed parent/student
result. A calculated parent delivery uses `RFDP`.

For student funds:

- An `RH` refund hold displays `Refund Hold - Student`.
- Ordinary funds use `ARFD (System)` when exactly one active ED hold exists, or
  `RFND (CHECK)` when ED is not active.
- Unused `CRVC` uses `CRVC (Transact)`.
- Unused `ACHK` uses its effective date. It becomes eligible on effective date
  plus 16 calendar days, so August 1 is eligible August 17. Through day 180 it
  uses `AFRD (Transact)`. After day 180, it remains AFRD with a
  `May Be Too Old` note. A waiting result states the exact eligibility date.

If the student amount contains multiple delivery sources, the delivery column
lists each route and amount separately.

### Audit and review fields

The output includes:

- previous-term balance before current payments,
- one prior-terms balance before current payments,
- Title IV applied to older fiscal years,
- unrestricted payments applied to older terms,
- reconstructed unused payment sources and unpaid charges,
- current target-term FDPL context and aid-year authorization,
- stored-balance differences, holds, delivery status, and review reasons.

A lawful cap can produce both a refund and an unpaid older charge. In that case
the calculated parent/student amounts remain visible while
`allocation_review_required_ind` is `Y`. Missing/invalid allocation metadata or
missing/conflicting Parent PLUS authorization makes the split undetermined.

`banner_pidm`, `target_term_fdpl_tran_number`,
`calculated_parent_plus_credit`, and `invalid_priority_count` remain omitted from
the displayed output as requested. `fdpl_priority_tie_rule` now reports
`EFFECTIVE_PRIORITY_THEN_EARLIEST_TRAN_NUMBER`.

## Diagnostics

Run `validate_refund_schema.sql` first. It now checks the category and Title IV
columns in addition to the existing transaction, identity, hold, and aid
authorization columns.

Use `Refund_allocation_diagnostic.sql` when an account disagrees with the report.
Set its local `params.cwid`; the default `NULL` intentionally returns no rows.
Do not save or commit a populated identifier or production output. The diagnostic
omits person identifiers but still contains student financial data. It shows all
term/detail/aid-year groups, transaction-number ranges and row detail, effective
dates, raw amount and balance totals, reversal counts, priority, category, and
Title IV flag. The transaction detail is needed to verify same-priority source
ordering and ACH timing. It does not calculate refund ownership.

## Validation workflow

1. Run `validate_refund_schema.sql` and resolve every `MISSING` result.
2. Confirm `full_account_balance` against the unrestricted TSAAREV Query Balance.
3. Review priority, category, Title IV, stored-balance, and policy-refund
   differences before production use.
4. Confirm the $200 give/receive rule and artificial detail-code bands with the
   functional owner.
5. Rerun the report immediately before taking action.

The automated suite executes the full query against synthetic PostgreSQL tables:

```sh
REFUNDS_TEST_DSN='host=localhost dbname=refunds_test user=refunds_test' \
  python -m unittest discover -s tests/python -p test_refunds_query.py -v
```

Set `REFUNDS_TEST_PSQL` if `psql` is not on `PATH`. Without a DSN, database tests
skip explicitly. Current coverage includes fiscal-year mapping, both Title IV
caps, same-year and cross-year transfers, unrestricted funds, artificial and
base priority order, wildcard matching, tie breakers, reversals, full-account
debit cases with legally refundable Title IV, per-aid-year FDPL authorization,
ACH clearing/180-day boundaries, CRVC, standard delivery routes, output order,
and stored-balance diagnostics.
