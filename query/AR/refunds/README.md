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
`-Offline` and keep the same term, run date, and batch count.

## Single-query alternative: `Refunds.sql`

Run the entire `Refunds.sql` file once in Insights to calculate the report in
the database. It implements the current Python allocation rules in one read-only
statement, with no database functions, temporary tables, schema changes, or
Python process. Run settings and optional validation filters remain near the top.

The result has one row per account with the allocator's existing column order,
source breakdown, recipient amounts, delivery methods, and review flags. SQL
produces one result set; the separate Excel tabs remain a Python workbook-export
feature. The two-download Python workflow remains available if Insights cannot
complete the single query within its ten-minute limit.

### Terms, population, and settlement

The target defaults from the run date using Mines boundaries: Spring `10`,
Summer `55`, and Fall `80`. Historical Summer `50` and `60` are supported.
Use `target_term_override` for a historical/work-ahead run and
`previous_term_override` when an old Fall should follow Summer `60`.

A fiscal year starts with Fall and ends with Summer: FY2026 contains `202680`,
`202710`, and `202755`. Previous and prior terms have separate audit totals.
Internal allocation keeps every term and charge priority separate and processes
the oldest charges first.

Candidates have target-term activity, a qualifying HOMP charge, or a negative
stored payment balance within the last two years of whole terms through the
target term. The two-year condition selects accounts; their complete history
is retained. There is no five-year history cutoff. A CWID or last-name validation
filter bypasses the activity conditions but still excludes positive balances.
Do not commit identifying filters.

Positive full-account balances are excluded. Zero-balance accounts can contain
restricted refunds and offsetting unpaid charges. Final output requires a
positive reconstructed refund. `total_refund_amount` is unused payment principal
and may exceed the net account credit.

The latest completed historical prefix is excluded from replay only if its
cumulative raw balance is zero and every stored transaction balance in that
prefix is known zero. A zero account total with unresolved row balances does
not count as settlement. All remaining historical charges retain their actual
term and priority; no fiscal-year deficit becomes an unrestricted synthetic
charge. Stored balances provide settlement evidence and diagnostics, while
reconstructed allocation determines refund ownership.

### Classification and priority

`TBBDETC_TIV_IND = 'Y'` classifies Title IV and overrides category. Non-Title-IV
`FA%` is unrestricted aid, `CSH` is cash, and other non-Title-IV categories are
also unrestricted for this allocation. Title IV has no same-FY cap. Between
different FYs, each source FY may give at most $200 total and each destination
FY may receive at most $200 total, in independent ledgers. This includes older
funds paying newer charges. Non-Title-IV payments cross FYs without a cap.

Within each term, charges apply from priority `999` downward. Payment zeros
are positional wildcards: `899` matches only `899`, `890` matches `89x`,
`800` matches `8xx`, and `000` matches any charge. Strict priorities retain
this restriction when crossing terms and fiscal years.

Payments apply by descending priority, then earliest transaction number:
`999..801`, `800A` (TPDT/TPPY), regular `800`, `799..001`, `000A` (COFP),
and regular `000`. ACH/cards use their configured numeric priority like ordinary
payments; the former `000Z` band is removed. Artificial suffixes change order
only; matching still uses the stored three digits. Conflicting base priorities
for TPDT/TPPY/COFP require review.

Reversals reduce newest positive payments within term/aid year/detail, and
charges within term/priority. Charge pooling permits paired detail codes, such
as a charge and waiver at the same priority, to offset. Negative net source
groups still require review.

### Ownership, delivery, and review

Each unused FDPL source uses its own aid year's PLUS authorization. N assigns
the refund to the parent/RFDP; Y assigns it to the student. Missing or conflicting
authorization blocks the recipient split. Multiple aid years can produce a
mixed parent/student result.

Only unused ACH/card principal routes to Transact. Ordinary student funds use
ARFD (System) with active ED, otherwise RFND (CHECK). RH overrides student
delivery. CRAM, CRDS, CRMC, and CRVC use their own code plus (Transact), without
a clearing delay. ACHK becomes eligible on effective date +16 days; day 180 is
included, and older funds carry the May Be Too Old note. Waiting funds show the
eligibility date. Multiple methods show their individual amounts.

Unused target-term C529/Z0LE/TPPY sources add `Possible Third Party refund`
and suppress delivery with `THIRD_PARTY_REVIEW`. Existing TPS-prefix and legacy
account flags remain effective. A surviving HOMP charge in the target term, or
effective 0–32 days ago in any term, adds `Mines Park Charge - Review` without
hiding amounts or delivery. Paid HOMP charges qualify; fully reversed charges
do not.

Restricted refunds with unpaid charges retain their recipient amounts and add
`RESTRICTED_PAYMENT_REFUND_WITH_UNPAID_CHARGE`. Allocation metadata problems,
negative source groups, authorization problems, or a ledger mismatch block an
unreliable split. Existing account controls and review columns are preserved.
The full rules and workbook presentation are also described in the
[workflow guide](../../../workflows/refunds/README.md).

### Execution design

The query loads and normalizes selected history once. Window aggregates net
reversals before charges are pooled by term and priority. Each account builds one
ordered list of matching payment indexes per distinct charge priority and reuses
it across terms. For each charge, the allocator selects the first source with
remaining principal and available FY allowance. Exhausted sources and capped
transfers do not generate recursive steps. Each step transfers money or finishes
a charge. Numeric arrays hold payment principal; separate small JSON ledgers
track FY caps. Recursion never rejoins population-wide transaction relations.

Summaries and vectors are materialized where repeated evaluation was observed.
Boolean classification flags help PostgreSQL 16 retain usable row estimates
across those boundaries; string comparisons on intermediate results had caused
repeated nested-loop scans in local population tests. See PostgreSQL's
[CTE evaluation and materialization](https://www.postgresql.org/docs/16/queries-with.html)
and [correlated lateral evaluation](https://www.postgresql.org/docs/16/queries-table-expressions.html#QUERIES-LATERAL).

#### Local synthetic measurements

Measured on PostgreSQL 16.2 with `EXPLAIN (ANALYZE, BUFFERS, TIMING OFF)` on
September 8, 2026. These are individual query execution measurements, excluding
fixture loading and result download, not Insights timings or a production SLA.

| Synthetic workload | Original SQL (`8b666fd`) | Updated SQL |
| --- | ---: | ---: |
| 2,500 accounts, 17,500 current-term transactions | 8.10 seconds | 0.75 seconds |
| 1,000 accounts, 103,000 transactions, eight years of settled history | Not measured | 0.51 seconds |
| 1,000 accounts, 103,000 transactions, eight years of open history | Not measured | 2.35 seconds |

The direct comparison repeats the test suite's seven-transaction worked example
for each account. The history workloads prepend eight years of spring, summer,
and fall tuition, fee, FDPL, and unrestricted payment rows. The two versions
differ only in whether those historical stored balances are zero (settled) or
nonzero (open). Temporary fixture tables have transaction PIDM, term, and
detail/effective-date indexes, a unique detail-code index, and an identity CWID
index; table statistics are analyzed before each measurement. Real account
histories, population sizes, table statistics, and available indexes will differ.

The query changes no database settings and does not bypass the timeout.
Remaining costs include candidate selection, history lookups, source sorting,
priority matching, and open-history length. Production runtime must be measured
in Insights. If it still times out, use the Python workflow and obtain an
execution plan from an administrator before changing planner settings or indexes.

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

Set `REFUNDS_TEST_PSQL` if `psql` is not on `PATH`. Without a DSN, database
tests skip explicitly. The SQL tests also run the existing Python allocation
scenarios through the SQL and compare every output column (review-reason order
is ignored). Daily population selection and a seeded population of 80 accounts
with open histories, varied priorities, reversals, and Title IV classifications
are compared with Python as well. Synthetic data contains no real student IDs.
