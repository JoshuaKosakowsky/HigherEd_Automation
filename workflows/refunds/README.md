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
An ED hold counts as active when its end date is December 31, 2099 or later;
this includes the Banner and cashnet far-future dates.

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
- a common artificial `000` matching/ordering band for stored `800` and `000`
  payments, including TPDT/TPPY and COFP;
- exclusion of Non-Allowable Charges from Title IV payment application;
- earliest transaction-number tie breaking;
- FDPL ownership by aid year and PLUS authorization;
- ACH/credit-card delivery routing and review statuses; and
- Excel output grouped into plain worksheets by refund method and review type.

Financial calculations use `Decimal` cents rather than binary floating point.

### Population and refund amounts

The two exports share one candidate definition: target-term activity, a
qualifying HOMP charge, any TPPY history, **or** a negative stored
payment balance in the last two years of terms through the target term. The
lookback starts with the whole term containing `run_date - 2 years` (September
7, 2026 starts at `202480`). It selects accounts, not transactions: selected
accounts retain their full history. There is no five-year history cutoff. A CWID
filter selects that account directly.

An amount owed in Summer and an equal credit in Fall ordinarily produces no
refund proposal. The exception is unused Title IV funding with confirmed
Non-Allowable Charges still owed, as described below. These accounts may have
a negative, zero, or positive full-account balance.

`full_account_balance` remains charges minus payments across all history,
including refunds already posted. Normally `total_refund_amount` is the account's
net credit. If all remaining unpaid charges are explicitly Non-Allowable, add
the lesser of their unpaid amount and the unused Title IV principal. This allows
the agreed federal refund while leaving those charges owed. Reconstructed source
remainders must equal this permitted refund; otherwise ownership and delivery
remain blocked, without arbitrarily trimming a source. Other unpaid charges,
including fiscal-year cap mismatches, do not qualify for this exception.

Reconstructed unused Title IV or non-Title-IV `FA%` aid must not exceed the
surviving source's stored unapplied credit. A missing aid balance or an excess
adds `APPLIED_AID_REOPENED_BY_RECONSTRUCTION` and blocks the recipient split and
delivery. This prevents money Banner shows as used from becoming a proposed aid
refund. Cash may still be reallocated across terms; cash stored-balance
differences retain their existing review flag. Other input and ownership checks
continue to block unreliable splits. These rules replace the former behavior
that proposed restricted refunds alongside offsetting unpaid charges.

`HIWR` (Health Insurance Waiver/Offset) directly reduces `HLTH` (Health Insurance)
within the same term and charge-priority pool (`879` for both in the supplied
configuration), before aid or cash is allocated. The posted negative HIWR amount
is a charge adjustment. An equal HLTH/HIWR pair leaves zero insurance charges
and consumes no payment; HIWR is not a separate refundable payment source.

Synthetic acceptance examples:

| Account activity | Expected result |
| --- | --- |
| Summer debt $5,000; Fall credit $5,000 | $0 refund; absent from refund tabs. |
| Summer charges $5,000; Fall unrestricted cash $5,500 | $500 refund after cash covers Summer. |
| Summer cash $5,500; Fall charges $5,000 | $500 refund after cash covers Fall. |
| Same-term HLTH $1,000 and HIWR -$1,000 at priority 879; unapplied cash $100 | Insurance nets to $0 before allocation; the $100 cash credit remains available. |
| Summer tuition $1,000 and applied Title IV aid $1,200; Fall tuition $500 and scholarship $600 with $300 unapplied | Earlier aid applies first; $300 of Fall scholarship remains, without reopening Summer aid. |
| Old-FY charges $1,000; newer Title IV payment $1,200, of which the configured cap applies $200 | Net credit $200 goes to manual review with no recipient/delivery; reconstructed unused $1,000 is diagnostic only. |
| Tuition $1,000; LPPF $100 marked Non-Allowable; Pell $1,200 with $200 unapplied | Refund $200; $100 remains owed; new column identifies the balance. |
| Same example with LPPF $200 or $300 | Refund $200 even though the starting account balance is zero or positive; $200 or $300 remains owed. |
| Tuition $1,000; Non-Allowable fee $100; Pell $1,200 followed by cash $100 | Cash pays the fee; Pell refund $200; new column says No. |

### Priorities, delivery, and review

Priorities without a zero, such as `899` and `869`, match only that exact charge
priority. Existing zero wildcard rules and Title IV fiscal-year limits also
apply across terms. Payments use oldest term first, then descending priority
and earliest transaction number within that term. A later scholarship's higher
priority cannot put it ahead of earlier-term aid. ACH and cards have no special
last-payment band. Stored `800` and `000` use the same artificial `000` for both
matching and order, below other nonzero priorities. TPDT/TPPY and COFP have no
special bands; all compete by transaction number within their payment term.
Original priorities, payment identity, and PLUS ownership remain available to
the calculation. This does not edit Banner's detail-code configuration.

### Title IV refunds that leave charges owed (0.28.0)

The [allocation decision in issue #29](https://github.com/JoshuaKosakowsky/HigherEd_Automation/issues/29#issuecomment-6690742823)
defines the common priority. In the implementation follow-up, the owner confirmed
removing the sponsor/COF exceptions, keeping oldest-term-first order, and the
$200 Pell refund/$100 LPPF balance example above. The related
[Title IV flag question](https://github.com/JoshuaKosakowsky/HigherEd_Automation/issues/29#issuecomment-6870164720)
tracks the charge-eligibility context; these confirmations are not live validation.

`TBBDETC_TIV_IND = Y` identifies Title IV payments. A charge with
`TBBDETC_NON_ALLOW_CHG_IND = Y` cannot consume those payments, even under the
common `000` wildcard. Other eligible funding can pay it. Charges pool only
within the same term, priority, and Non-Allowable flag, so differently restricted
charges cannot be combined. Missing/invalid charge flags block recipient splits
and are not treated as Title-IV-eligible. LPPF is not hard-coded: the flag governs
every charge detail code. Stored aid-balance safeguards still apply.

Every workbook tab adds **Title IV Refund Leaves Balance Due**, immediately
after **Total_Owed_to_Student**. A calculated exception displays `Yes` with the
total non-allowable balance remaining after the proposed account refund, not
just the increase in balance or that tab's portion. An unresolved exception
displays `Review required`; other cases display `No`. Holds and sponsor/parent
review routing still apply. The column supports staff follow-up; it neither
confirms issuance nor sends email.

This implements the explicit Non-Allowable exclusion only. Institutional-charge
authorization (`TBBDETC_INST_CHG_IND` and the student's authorization records)
is not inferred; its extraction and rules remain a separate unresolved scope.
Before operational use, validate the new column in the Insights schema and
compare representative Banner accounts. Regenerate paired manual downloads or
start a fresh API extraction; cache format 6 rejects older caches.

After all ordinary charges are allocated oldest-term first, posted student
refunds with detail code `ARFD` or `RFND` reconcile against still-unused payment
sources across the account. The refund transaction must have a higher transaction
number than the payment it consumes. This final reconciliation bypasses priority
matching because the money has already been issued, preventing restrictive
payment remnants from being proposed repeatedly. Partial reconciliation is
identified in `review_reasons`. Refund reversals are netted first. `RFDP` is not
included in this exception.

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
  been applied to charges. Independently, **any TPPY activity in a term with a
  net credit requires review, even if fully reversed**, regardless of transaction
  age or selected target term. Unknown financial data in a TPPY term also requires
  review. The matched code remains visible in `third_party_match_source`, and automatic delivery is
  suppressed with `THIRD_PARTY_REVIEW`. Existing third-party account flags remain
  effective.
- A surviving positive HOMP charge in the target term, or effective 0–32 days
  ago in any term, adds `Mines Park Charge - Review`. This includes paid charges
  in settled history, but excludes fully reversed charges. Refund amounts and
  delivery remain visible for staff review.

These implement the institution's supplied allocation policies; the workbook
remains a review proposal, not approval to disburse funds.

### Third-party review details (0.27.0)

The confirmed review rule and requested context are tracked in
[issue #29, sponsor review comment](https://github.com/JoshuaKosakowsky/HigherEd_Automation/issues/29#issuecomment-6691269422).
This extends review routing; it does not change payment allocation or authorize
returning sponsor funds to the student.

Only **Third Party Reviews** adds these columns:

| Header | Meaning |
| --- | --- |
| Sponsor(s) | Sponsor name from current SPRIDEN identity |
| Sponsor ID(s) | Sponsor ID from current SPRIDEN identity |
| Contract Number(s) | TBBCSTU contract number, retained as text |
| Current Term | Calendar-derived term using the run date and existing Mines term boundaries |
| TPPY Current Term Total | Signed TBRACCD amounts for TPPY in that current term, including reversals |
| Z0LE Current Term Total | Signed TBRACCD amounts for Z0LE in that current term, including reversals |
| Z0LE Activity_Last 7 Days | Yes for any Z0LE activity whose Feed Date is today or one of the preceding six calendar days; otherwise No |

Totals are transaction totals, not remaining unapplied balances. The seven-day
flag checks all extracted terms and includes reversal activity; it does not use
Effective Date or Activity Date. Missing amounts leave the affected total blank
and retain existing data-quality review reasons.

Sponsor attachments cover the calendar-derived current term and terms with
TPPY, Z0LE, or C529 activity. Lists are aligned by sponsor ID, sponsor PIDM and
contract number; a sponsor repeats when it has multiple contracts. Duplicate
attachments are removed before aggregation and PLUS authorization joins, without
multiplying transactions. Missing sponsor identity is labeled unavailable;
missing attachments remain blank. Attachment deletion/authorization flags are
not inferred as ownership decisions: this is context for manual review.

Synthetic acceptance cases:

- TPPY +100 and -100, plus a separate 50 payment in the same term: review the
  50 account credit even though TPPY nets to zero, including historical terms.
- Fully reversed TPPY in a zero-balance old term, with credit only in another
  term: the new same-term rule does not trigger; existing review rules still apply.
- Current-term TPPY +100/-20 and Z0LE +50/-10: show 80 and 40, regardless of
  an overridden target term. Duplicate PLUS rows do not change either total.
- Z0LE Feed Date six days before the run: Yes; seven days before or tomorrow: No.
- RH plus a third-party review condition: the entire refund remains on Refund
  Holds, preserving the third-party reason. Third Party Reviews stays empty.

**Refresh both manual downloads or start a new API extraction after upgrading.**
Old downloads lacking Feed Date, sponsor columns, or the Non-Allowable Charge
flag are rejected with a request to rerun the current export SQL. Caches now
use format version 6 and reject older formats. Run `validate_refund_schema.sql` to confirm TBBCSTU fields and
TBRACCD_FEED_DATE in the actual Insights schema, then compare representative
sponsors/contracts against TSACONT before operational use. Candidate selection
now includes historical TPPY accounts; production-size extraction timing needs
local verification.

The standalone `Refunds.sql` retains its existing output columns and shares the
new TPPY review condition. The sponsor-detail columns are produced by the Python
workflow from the flat extracts, not by that standalone allocation report.

### Workbook tabs

The workbook has these tabs, including headers when a category is empty:

- **ACH or CC Refunds** (light yellow tab): available ACH and credit-card portions.
- **Refund by Check** (light green tab): student `RFND (CHECK)` portions.
- **Refund to Parent** (light orange tab): parent `RFDP` portions.
- **Direct Deposit** (light blue tab): student `ARFD (Direct Deposit)` portions.
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
once per tab. **Detail_Code_Delivery** identifies that tab's method(s), and
**Detail_Code_Refund_Amt** contains only that portion. Sum this portion across
tabs; account-level totals repeat as context. **Detail_Code_Note** explains
account review placement. Retained report columns keep their values and relative
order after these three fields, which follow the student's name.

All tabs use the following displayed-header mapping and retain the student/parent
context fields listed below. Other retained columns keep their original order
and names.

| Original field | Displayed header |
| --- | --- |
| `cwid` | `CWID` |
| `last_name` | `Last_Name` |
| `first_name` | `First_Name` |
| `tab_delivery` | `Detail_Code_Delivery` |
| `tab_refund_amount` | `Detail_Code_Refund_Amt` |
| `tab_review_note` | `Detail_Code_Note` |
| `full_account_balance` | `Current_Total_Balance` |
| `total_refund_amount` | `Total_Owed_to_Student` |
| `proposed_student_delivery` | `Proposed_DetailCode&Amt` |
| `raw_delinquency_code` | `Active RH` |
| `active_ed_ind` | `Active ED` |
| `ed_activity_date` | `ED Start` |
| `plus_to_student_status` | `PPL to Student` |

Every tab omits `original_payment_row_count`, `deceased_ind`, `deceased_date`,
`confidential_ind`, `ambiguous_source_pool_count`, `last_ar_activity_date`, and
`account_control_activity_date`. These omitted fields remain available internally.
Every tab includes `student_refund_amount`, `proposed_parent_delivery`,
`parent_refund_amount`, `plus_to_student_status` (displayed as **PPL to Student**),
`refund_hold_ind`, and `fdpl_aidy_code` as account context. These fields repeat
when an account appears on multiple tabs; they are not the tab's refund portion.
On **Refund to Parent**, `parent_refund_amount` repeats the parent portion in
**Detail_Code_Refund_Amt**.
Sum **Detail_Code_Refund_Amt** when combining portions across tabs;
**Total_Owed_to_Student** remains the account-level total.

Both **Detail_Code_Delivery** and **Proposed_DetailCode&Amt** display the system
route as `ARFD (Direct Deposit)`, including mixed-method values. The underlying
detail code remains ARFD; the internal allocation report uses `ARFD (System)`.
The renamed columns retain their existing values: **Active RH** is the raw
delinquency code, **Active ED** is the ED indicator, and **ED Start** is the
existing ED hold activity timestamp.

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

The GUI also supports **Cancel run**, or cancelling and closing from the window
close button. Its shared progress display shows extraction batches and partitions,
transaction normalization, completed account calculations, worksheet creation,
formatting, saving, and publication. Percentages describe the current stage;
unknown totals use an activity bar. Elapsed time remains visible throughout.
Cancellation waits for an in-flight request to return or time out,
checks between account calculations and workbook stages, and discards staged
output before publication. A successfully published workbook remains available
if cancellation is requested after the publication step. Other workflows retain
their existing close restrictions. Query and processing timings appear in the
GUI log and launcher progress output.

## Recover from failures

The following recovery options apply only to API/batched mode. If authentication
or a connection fails after some batches finish, use the
same term and batch count with `-Resume`:

```powershell
.\launcher\run_refunds.ps1 -TargetTerm 202680 -BatchCount 20 -Resume
```

The API extractor automatically subdivides truncated transaction and context
batches by disjoint PIDM ranges. If a single account's transaction history is
still too large, it subdivides by transaction number. This handles Insights'
response row limit without changing the initial `-BatchCount` or account scope.
PIDM bounds apply inside candidate selection, before full-account balance
aggregation and history joins. Transaction-number bounds apply to the final
transaction extract, so they never alter full-account eligibility. Smaller
queries therefore avoid rebuilding the entire original batch on every retry.
Every part passes the row-count guard, and recombined totals must match the
parent batch before the completed batch is cached. Each filtered query retains
its own row-count guard. Progress is printed by the
launcher and written to the GUI log without account identifiers. Subdivision
is bounded; an indivisible result or a population change that breaks count
reconciliation stops extraction
with a descriptive error rather than accepting incomplete data.

Only complete top-level batches are cached; a failed subdivided batch is
retried in full on `-Resume`. Existing compatible complete caches remain valid.
If a query itself times out, increase `-BatchCount` and start a fresh extraction
without `-Resume`. Changing the batch count changes every PIDM partition, so
old batches cannot safely be mixed with the new run. Manual file downloads
still require complete exports; they cannot be automatically subdivided.

To recalculate an already complete extraction without Insights, use `-Offline`
with the same term, batch count, extract directory, optional CWID, and run date
used for the original extraction. When resuming or recalculating on a later
date, set `-RunDate YYYY-MM-DD` to the original date. The cache manifest also
records the extraction policy version; caches from before this population
change must be extracted again.

Re-download **both** manual exports after an extraction population update.
Older downloads may omit newly eligible accounts. Use identical SQL settings
and pass the matching `-TargetTerm` and `-RunDate` to Python.

The later workbook-tab-only change does not require new SQL downloads; existing
compatible extracts can be recalculated to produce the new layout.

Version 0.28.0 requires the new `non_allowable_charge_ind` transaction column.
Older downloads are rejected with a refresh instruction. Use the updated SQL
for both paired downloads before recalculating this version.

## Validation expectation

Run a known account first by setting `cwid_filter` in both manual SQL files (or
use `-Cwid` in API mode). Compare the workbook to the account activity and the
expected Banner/staff result before running the population. Treat every status
other than `READY_FOR_STAFF_REVIEW` as requiring the listed review or wait
action.
