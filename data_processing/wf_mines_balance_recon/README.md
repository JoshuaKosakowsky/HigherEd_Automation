# W&F - Banner Recon

App **0.23.4** implements [issue #15](https://github.com/JoshuaKosakowsky/HigherEd_Automation/issues/15):
one combined Banner report, agency principal calculations, and account reconciliation.
The owner clarified the population and aggregation rules in the implementation
conversation: Banner includes **active CO accounts only**; WOFF/BDRC use signed
**Amount**, and reconciliation includes CWIDs from either source, summing multiple
W&F accounts. This workflow reads sources and saves a new workbook; it does not
change Banner or W&F records.

## Inputs and access

- **Insights data**: upload one complete **W&F - Banner Recon** export from
  `query/AR/holds/collections_tracking.sql`. CSV, XLS, XLSX and XLSM are supported.
  The old separate holds and transaction exports cannot substitute for this
  combined report. Update saved Insights questions to the current SQL before
  downloading reports with the renamed CO date columns. Up to 30 title/header rows are allowed; exactly one matching
  table is required. Headers are matched without case/quote/whitespace differences.
- **Williams and Fudge uploads**: select/drop multiple CSV, XLS, XLSX or XLSM files.
  Additional batches append to the list; repeated paths are not added twice.
  Every file whose name contains `12007`, `12009`, `12559` or `12561` is omitted
  completely, including extra worksheets, because these are Unisa verifications.
  All files may remain selected in the upload batch; source files are untouched.
- **Outputs**: choose an approved existing folder and a new XLSX filename.

Administrators can choose **Run SQL from PROD Insights** instead of uploading
Banner data. It runs the combined `collections_tracking` query once, with fixed
WOFF/BDRC codes and no term/date parameters. It rechecks administrator access
before sign-in, requires PROD, and retains existing session/authentication controls.
Staff have upload mode only, without TEST/PROD settings. Keep the existing
`wf_mines_balance_recon` permission ID; no shared policy is changed automatically.

The API result must include a valid `Report Row Count`; missing, invalid or
capped results stop before saving. This grouped query does not use the legacy
transaction batching path. The fallback is one complete combined Insights export.
Uploads check a supplied count but cannot prove coverage if no count is supplied.
Errors identify configuration, sign-in, named query, completeness or session-close
stage without exposing raw URLs, server responses, credentials or student rows.
Connections offers **Holds — W&F - Banner Recon** for standalone query verification.
Publishing/updating a saved question in Insights is a separate operational step.

## Commission configuration (0.23.5)

The workflow has no commission input for staff or administrators. The institution
configuration at `config/institutions/mines/wf_reconciliation.json` sets
`submission_percentage` to `0.25` (25%). Administrators maintain this non-secret
file through the normal application deployment process. It accepts a finite
fraction from 0 to 1, applies to upload and SQL modes, and is recorded in workbook
metadata. Invalid or missing configuration stops the run. Workflow parameters
cannot override it.

## Banner business rules

One row per current identity/PIDM with a CO hold ending strictly after today,
using the latest qualifying CO From Date (NULL last), then latest CO To Date.
There is no enrollment, positive-balance or From Date restriction. Separate
`CO Hold` and `TO Hold` columns prevent hold joins from duplicating accounts.
TO is present when a TO hold also ends strictly after today; it does not expand
the CO population. CO From Date and CO To Date describe the selected CO hold.

`Current Account Balance` retains all-term charges minus payments using detail
code types C/P and signed reversals. `WOFF` and `BDRC` each sum all-history signed
posted Amount values for that code, including NULL/future feed dates and reversals;
they do not use remaining transaction Balance or a feed-date window.
`Total Balance = Current Account Balance + WOFF + BDRC`, as requested in issue #15.
A code with no activity is zero when account transactions exist. Unknown code
amounts remain blank; unknown detail types/missing amounts leave account balance
blank. Accounts without transactions retain blank balances. Missing amounts
never become a known zero. Latest Feed Date is omitted from the combined report.
See [SQL rules and validation](../../query/AR/holds/README.md).

## Workbook and reconciliation rules

| Tab | Content |
| --- | --- |
| Reconciliation | CWID, First Name, Last Name, Banner Total Balance, W&F Principal Amount, Difference, W&F Returned |
| Students in Collections | Combined Banner report: CWID, Last Name, First Name, CO Hold, TO Hold, CO From Date, CO To Date, Current Account Balance, WOFF, BDRC, Total Balance (in this order) |
| W&F Collections | Consolidated Account Status reports with creditor, fee type, source file and Principal Amount |
| W&F Returned | Consolidated Returned Accounts reports with creditor and source file |
| WF file - worksheet | Other source worksheets, retaining value snapshots and layout |

From patch 0.23.5, tab order is Reconciliation, Students in Collections,
W&F Collections, W&F Returned, then other source worksheets. Agency tabs appear
when those reports are supplied.

Students in Collections sorts newest first by CO From Date; agency tabs sort
newest first by Placement / Return Date. Dates display without times, including
9999-12-31; blank/unreadable agency dates sort last and unreadable text stays
visible. Equal dates keep source order. No Sources tab is added.

For rows whose Type is exactly `Fees`, `Principal Amount = Orig. Balance /
(1 + Submission Percentage)`, rounded per account to cents using half-up rounding.
Other types, including `No Fees` and `unspecified`, keep Orig. Balance. Blank or
unreadable amounts yield blank principal. Original source amounts stay intact.

Reconciliation matches Banner CWID to agency `Your Accnt #`, trimming outside
whitespace while preserving leading zeros. It does not infer prefixes, strip
zeros, or match names. Banner must have unique, nonblank CWIDs; agency identity
fields must be nonblank. Invalid identities stop the run rather than create a
false match. W&F names are retained on agency tabs; unmatched agency records
have blank Banner First Name/Last Name.

Every CWID from Banner or W&F Collections appears once. Multiple W&F account
principals for a CWID are summed without deduplicating source records. An unknown
principal makes that CWID's aggregate unknown. Banner Total Balance is copied
from Banner; `Difference = Banner Total Balance - W&F Principal Amount` only
when both amounts are known. An absent source stays blank, including Difference.
From patch 0.23.6, reconciliation money columns display known zero as `$0.00`.
A blank Difference means the comparison cannot be calculated because a source or
amount is missing/unreadable. It stays blank, with a yellow fill and explanatory
Excel cell note. A known zero Difference means both known totals are equal.
Amounts are not replaced with text or assumed to be zero.
`W&F Returned` is numeric 1 when the CWID appears in any included Returned report,
otherwise 0; returned-only accounts do not expand the reconciliation population.
Reconciliation follows Banner's displayed order, then W&F-only CWIDs in upload order.

### Synthetic acceptance examples

- Charges 500, WOFF payment amounts 125 and -25, BDRC payment amount 50:
  account balance 350, WOFF 100, BDRC 50, Total Balance 500.
- Repeated TO holds add one TO indicator without multiplying the balance.
  A TO-only or WOFF/BDRC-only account without qualifying CO is not selected.
- Fees balance 125 at 0.25 gives principal 100; No Fees/unspecified balance 125
  remains 125. A signed Fees reversal -125 gives -100.
- Two Fees accounts 125 and 62.50 for one CWID give aggregate principal 150;
  Banner Total Balance 150 gives Difference 0. A Returned match sets 1.
- Banner-only and W&F-only accounts remain visible with the absent amount and
  Difference blank. `0000123` and `123` remain distinct identities.

### Agency source parsing and safeguards

Recognized names (case-insensitive, flexible spaces around hyphens):
`Report - AccountStatusReport_NoBreakout - 12003-2026-09-30.xlsx` and
`Report - ReturnedAccounts- 12003-2026-09-30.xlsx`, including CSV/XLS/XLSM
variants. Any five-digit creditor is supported except the filename exclusions
above. Malformed known report filenames fail; unknown reports stay on separate
tabs. Additional/hidden/empty worksheets remain visible as source snapshots.

Known tables require their original row-6 headers, mapped by name with flexible
case/spacing/order; missing, duplicate or unexpected headers fail. Creditor
comes from the filename. Row-4 WITH FEES / NO FEES (singular FEE accepted) maps
to Fees / No Fees; missing or ambiguous labels become literal `unspecified`.
Collections retains Your Accnt #, Name, Placement, Orig. Balance, Curr. Balance,
Collected and Remarks, adding Principal Amount after Orig. Balance, followed
by Creditor, Type and Source File. Returned retains its original nine columns,
then Creditor and Source File. Text IDs and simple zero-padded numeric IDs retain
leading zeros. Duplicate agency records remain separate source rows.

From patch 0.23.6, both Collections and Returned rows whose Your Accnt # is
explicitly labeled `Total Accounts` are removed in full. A colon and numeric
count (including comma-grouped counts) are optional; case and whitespace are
ignored. These rows do not contribute to principal totals or reconciliation. Unlabeled summaries require matching account count and at
least two monetary totals, or exact full-range SUM formulas. An uncertain row
is retained; data after an identified footer fails. Financial/missing-name rows
are not silently dropped. Review unexpected source layouts before use.

Other worksheets retain cell values, number formats, dimensions and merged cells.
Names become Excel-safe and unique. Charts, macros, drawings, calculation models
and workbook links are not copied. Formula snapshots use cached values; modern
Excel formulas without a saved value stop the run. Literal formula-like text
remains text. Source files are never modified.

### Input format handling (0.23.0)

CSV is read directly using the standard library. UTF-8 (with/without BOM),
UTF-16 with BOM, and Windows-1252 exports are supported. Blank lines keep their
physical row positions so fee metadata remains on row 4 and headers on row 6.
CSV identifiers/text remain text (including leading zeros and literal `=`);
recognized agency monetary columns become numeric when their values can be
parsed without guessing. Unrecognized amount text remains supplied text for
review, not zero.

Legacy binary XLS files are read directly with `xlrd==2.0.2`, without rewriting
or converting the employee's file. Worksheet names, saved values, Excel dates
(including 1904-epoch workbooks), number formats, merged ranges and row/column
sizes are carried into the source review. Legacy fonts/decorative styling are
not guaranteed. XLS formulas expose their saved values rather than formula
definitions; unlike modern Excel sources, this reader cannot independently
detect a missing formula cache. Use the originally saved report and check
source freshness. XLSX/XLSM keep the existing modern Excel path and formula
cache checks. No macros are executed or copied into output.

Existing workstations must rerun the normal `setup.ps1` once after updating to
install the XLS reader. The app does not install packages during a staff run.
The GUI picker accepts all four formats for both Insights and W&F inputs;
output is still a new XLSX workbook. Synthetic regression fixtures include real
BIFF8 XLS data, not modern workbooks renamed to XLS.

The workflow supports cancellation before publication, stages the complete
workbook and publishes using exclusive creation. Errors/cancellation do not
leave a partial final workbook, and existing files/source paths cannot be
overwritten. Inputs must fit Excel worksheet limits; no source rows are
silently truncated.

## Verification and operational boundary

Synthetic tests execute the combined SQL (SQLite date/clock adaptation), actual
workbook publication, fee calculations, duplicate-account aggregation, outer
matching, returned flags, excluded files, format readers, GUI source switching,
backend access, completeness failures, cancellation and output conflicts.
These tests do not establish live PostgreSQL compatibility, Insights permissions,
replication freshness or production report completeness. Validate the combined
query and a representative approved export before operational use.

The owner classifies 0.23.4 as a patch correcting the W&F reconciliation
workflow. Follow the repository patch-release policy and run appropriate local
checks before publication. Staff procedures and manual fallback belong in the approved office Word
SOPs. This technical guide does not replace those procedures.
