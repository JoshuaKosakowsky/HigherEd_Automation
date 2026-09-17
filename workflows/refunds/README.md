# Refund review workflow

This read-only workflow moves the expensive allocation work out of Insights.
It does not approve or issue refunds.

For a single Insights execution, `query/AR/refunds/Refunds.sql` also implements
the current allocation rules entirely in SQL. See the
[single-query guide](../../query/AR/refunds/README.md#single-query-alternative-refundssql)
for its execution design and performance limits. The SQL result is one account
report; this Python workflow adds the refund-type workbook tabs.

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
  raw account balance and every stored transaction balance in that prefix are
  known to be zero, preventing closed payments and refunds from being reopened
  while retaining unresolved, offsetting restricted credits and charges;
- Title IV classification and separate $200 giving/receiving fiscal-year caps;
- unrestricted cross-term allocation;
- Banner positional priority matching;
- the 800A (TPDT/TPPY) and 000A (COFP) artificial ordering bands;
- earliest transaction-number tie breaking;
- FDPL ownership by aid year and PLUS authorization;
- ACH/credit-card delivery routing and review statuses; and
- Excel output grouped into plain worksheets by refund method and review type.

Financial calculations use `Decimal` cents rather than binary floating point.

### Population and refund amounts

The two exports share one candidate definition: target-term activity, a
qualifying HOMP charge, a qualifying TPPY payment, **or** a negative stored
payment balance in the last two years of terms through the target term. The
lookback starts with the whole term containing `run_date - 2 years` (September
7, 2026 starts at `202480`). It selects accounts, not transactions: selected
accounts retain their full history. There is no five-year history cutoff. A CWID
filter selects that account directly.

The SQL excludes known positive full-account balances. Python also excludes
positive balances and accounts with no reconstructed unused payments. A zero
balance is eligible when restricted payments leave a refund and offsetting
unpaid charges. For example, $10,000 of `899` charges plus $1,000 of `897`
charges, paid by $9,500 at `899` and $1,500 at `897`, produces a $500 student
refund and $500 unpaid tuition, despite a zero net balance.

`full_account_balance` remains charges minus payments across all history.
`total_refund_amount` is now the reconstructed unused payment total, split by
ownership; it is not capped at the net account credit. Restricted refunds with
unpaid charges show amounts and delivery methods but require manual review with
`RESTRICTED_PAYMENT_REFUND_WITH_UNPAID_CHARGE`. Missing or inconsistent allocation
inputs still suppress an unreliable recipient split. The former
`REAPPLICATION_REQUIRED` gate no longer hides a valid restricted refund.

### Priorities, delivery, and review

Priorities without a zero, such as `899` and `869`, match only that exact charge
priority. Existing zero wildcard rules and Title IV fiscal-year limits also
apply across terms. Payments use descending priority and then earliest
transaction number. ACH and cards have no special last-payment band: at `000`
they follow COFP (`000A`), then compete with other `000` payments by transaction
number. FDPL likewise uses the existing chronological tie rule.

Only each unused ACH/card source remainder routes to Transact. Remaining aid,
scholarship, and PLUS funds authorized for the student use the student's normal
`ARFD (System)` or `RFND (CHECK)` route; PLUS authorized for the parent uses
`RFDP`. `CRAM`, `CRDS`, `CRMC`, and `CRVC` display their own code plus `(Transact)`
with no clearing wait. ACHK uses its effective date: available on day 16
(August 1 becomes August 17), through day 180. Younger funds show the eligibility
date; older funds show `AFRD (Transact) - May Be Too Old`. Reversals are netted
before identifying the surviving source and its refund amount. Holds continue
to override student delivery. Unused CHCK remains on the student's normal System
or Check tab, but cannot be initiated until effective date +16 days. While it is
waiting, the tab note shows the CHCK amount and exact eligibility date. Missing
or future CHCK effective dates require manual review. RH still sends the entire
account to Refund Holds and retains the CHCK clearing note.

- Surviving target-term refund sources `C529` or `Z0LE` add `Possible Third Party
  refund`. A surviving TPPY payment adds the same review when it is in the target
  term or effective 0–32 days ago in any term. TPPY still qualifies after it has
  been applied to charges, but not after it is fully reversed. The matched code
  remains visible in `third_party_match_source`, and automatic delivery is
  suppressed with `THIRD_PARTY_REVIEW`. Existing third-party account flags remain
  effective.
- A surviving positive HOMP charge in the target term, or effective 0–32 days
  ago in any term, adds `Mines Park Charge - Review`. This includes paid charges
  in settled history, but excludes fully reversed charges. Refund amounts and
  delivery remain visible for staff review.

These implement the institution's supplied allocation policies; the workbook
remains a review proposal, not approval to disburse funds.

### Workbook tabs

The workbook has these tabs, including headers when a category is empty:

- **Transact Refunds:** available ACH and credit-card portions.
- **Check Refunds:** student `RFND (CHECK)` portions.
- **Parent Refunds:** parent `RFDP` portions.
- **System Refunds:** student `ARFD (System)` portions.
- **Third Party Reviews:** the entire account refund pending ownership review.
- **Refund Holds:** the entire account refund when RH is present, including any
  student and parent portions. No portion remains on a delivery or other review
  tab while the hold is active.
- **ACH Clearing:** ACH portions still within the clearing period, with the
  eligibility date retained.
- **ACH Reviews:** ACH portions over 180 days old or requiring effective-date review.
- **Mines Park Reviews:** the entire account refund pending housing review.
- **Manual Reviews:** undetermined splits, unrecognized delivery methods, or
  delivery components that do not reconcile to recipient amounts.

RH takes precedence over every delivery and review tab. Without RH, third-party
review takes precedence over Mines Park review. All applicable reasons remain
visible so staff can address them after a hold is removed. Other existing review
statuses and reasons stay on the applicable method tabs: a tab assignment is
**not approval to issue a refund**.

Mixed refunds can appear on multiple tabs, but each account appears at most
once per tab. `tab_delivery` identifies that tab's method(s), and
`tab_refund_amount` contains only that portion. Sum **tab_refund_amount**, not the
original account-level totals, across tabs. `tab_review_note` explains account
review placement. Original report columns retain their values and relative
order after these three fields, which follow the student's name.

The sheets use ordinary cells with formatted headers, currency/date formats,
frozen headers, and regular column filters. They contain no Excel Table objects.
This presentation change does not alter allocation, ownership, or SQL scope.

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
with the same term, batch count, extract directory, optional CWID, and run date
used for the original extraction. When resuming or recalculating on a later
date, set `-RunDate YYYY-MM-DD` to the original date. The cache manifest also
records the extraction policy version; caches from before this population
change must be extracted again.

Re-download **both** manual exports after this update. Older downloads do not
necessarily contain the newly eligible accounts. Use identical SQL settings
and pass the matching `-TargetTerm` and `-RunDate` to Python.

The later workbook-tab-only change does not require new SQL downloads; existing
compatible extracts can be recalculated to produce the new layout.

## Validation expectation

Run a known account first by setting `cwid_filter` in both manual SQL files (or
use `-Cwid` in API mode). Compare the workbook to the account activity and the
expected Banner/staff result before running the population. Treat every status
other than `READY_FOR_STAFF_REVIEW` as requiring the listed review or wait
action.
