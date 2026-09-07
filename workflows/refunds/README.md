# Refund review workflow

This read-only workflow moves the expensive allocation work out of Insights.
It does not approve or issue refunds.

## What runs where

For the normal manual process, Insights runs two flat queries. One returns
TBRACCD rows with current TBBDETC metadata; the other returns identity, account
controls, ED holds, and RLRPAPP Parent PLUS authorization. Each response
includes a total-row guard so Python stops if the website download is truncated.

The local Python process then performs:

- payment and charge reversal netting;
- Mines term and Fall-through-Summer fiscal-year mapping;
- separate charge pools for every term and priority, processed oldest term first;
- a settled-history boundary at the latest completed term where the cumulative
  raw account balance returned to zero, preventing closed payments and refunds
  from being reopened under current priorities;
- Title IV classification and separate $200 giving/receiving fiscal-year caps;
- unrestricted cross-term allocation;
- Banner positional priority matching;
- the 800A, 000A, and 000Z artificial ordering bands;
- earliest transaction-number tie breaking;
- FDPL ownership by aid year and PLUS authorization;
- ACH/credit-card delivery routing and review statuses; and
- Excel output in the same column order as `Refunds.sql`.

Financial calculations use `Decimal` cents rather than binary floating point.

`total_refund_amount` is the actual full-account credit available for a refund.
`total_unused_payment_amount`, `unused_fdpl_amount`, and `unpaid_charge_amount`
show the reconstructed policy allocation. If reconstructed unused payments do
not equal the account credit, the workflow leaves the parent/student amounts
blank, suppresses actionable delivery codes, and reports
`REAPPLICATION_REQUIRED`. This keeps the allocation discrepancy visible without
recommending a refund that the current account balance cannot support.

## Run

Complete the repository's normal `setup.ps1` process. In the Insights website:

1. Run `query/AR/refunds/refund_transactions_manual.sql` and download the full
   result as XLSX or CSV.
2. Run `query/AR/refunds/refund_context_manual.sql` with the same settings and
   download the full result.
3. Rename and place them under `data/refunds/input` as
   `refund_transactions.xlsx` and `refund_context.xlsx`.

Then run from the repository root:

```powershell
.\launcher\run_refunds.ps1 `
    -TargetTerm 202680 `
    -TransactionsFile ".\data\refunds\input\refund_transactions.xlsx" `
    -ContextFile ".\data\refunds\input\refund_context.xlsx"
```

The output workbook is written under `data/refunds` by default. CSV and Excel
files are excluded by `.gitignore`; never commit or move these student-account
extracts into the repository as another file type.

The files may remain in Downloads instead. Pass their complete paths to
`-TransactionsFile` and `-ContextFile`; Python does not require a particular
folder. The recommended input folder simply makes the two files easy to identify
and is already protected by `.gitignore`.

Administrators may run this same manual-download pipeline from **Refund Review**
in the Mines Bursar Automation desktop app. The GUI accepts a path, Browse
selection, or file drop for each download and refuses to overwrite an existing
review workbook. The analyst and cashier views are not assigned this workflow.

For a single-account validation, set the same `cwid_filter` inside both manual
SQL files before running them. Leave `cwid_filter` NULL for the population.
Do not save or commit a populated CWID in either SQL file.

The API/batched mode remains available when the existing Insights API connection
has been configured. It does not require manual downloads:

```powershell
.\launcher\run_refunds.ps1 -TargetTerm 202680
```

## Recover from failures

The following recovery options apply only to API/batched mode. If authentication
or a connection fails after some batches finish, use the
same term and batch count with `-Resume`:

```powershell
.\launcher\run_refunds.ps1 -TargetTerm 202680 -BatchCount 20 -Resume
```

If a flat batch itself times out or the row-count guard reports truncation,
increase `-BatchCount` and start a fresh extraction without `-Resume`. Changing
the batch count changes every PIDM partition, so old batches cannot safely be
mixed with the new run.

To recalculate an already complete extraction without Insights, use `-Offline`
with the same term, batch count, extract directory, and optional CWID used for
the original extraction.

## Validation expectation

Run a known account first by setting `cwid_filter` in both manual SQL files (or
use `-Cwid` in API mode). Compare the workbook to the account activity and the
expected Banner/staff result before running the population. Treat every status
other than `READY_FOR_STAFF_REVIEW` as requiring the listed review or wait
action.
