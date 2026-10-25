# W&F - Mines Balance Recon (early source review)

App 0.21.0 adds an initial workspace for the analyst and owner to review the
source data together before agreeing on matching/reconciliation rules. It
collects sources into a new workbook; it does not identify differences, match
accounts, determine agency status, or change Banner or W&F records.

## Inputs and access

The GUI has three separate sections:

- **Insights data**: upload the complete **Collections tracking** report and
  **W&F - Mines Balance Recon transactions** report. CSV, XLS, XLSX and XLSM
  exports are supported. The two matching source tables are required;
  the reader allows up to 30 title/header rows and rejects ambiguous tables.
- **Williams and Fudge uploads**: select/drop several CSV, XLS, XLSX or XLSM files at
  once. Additional browse/drop batches append to the list. Repeated paths are
  not added twice. Files with the same name in different folders remain
  separate. In 0.22.0, recognized report tables are concatenated into the two
  agency tabs described below; other worksheets remain separate. Hidden and
  empty worksheets are retained as well.
  Files can be mixed in one batch. No manual conversion is needed.
- **Outputs**: choose an approved existing folder and a new XLSX filename.

Administrators can instead choose **Run SQL from PROD Insights** in the
Insights section. This replaces both report uploads with direct queries of
the existing `collections_tracking` and `wf_mines_balance_transactions`
catalog reports. W&F uploads are still required. Codes default to WOFF/BDRC
and are editable for the direct query. The workflow rechecks administrator
access before authentication, uses existing browser/cached-session controls,
shows the normal PROD review, and requires both completeness checks to pass.
Malformed/incomplete results stop the run without saving a workbook; from
0.23.1, proven transaction row caps trigger the checked batching described below.
Complete Insights downloads remain the manual fallback. Separate queries in one
session are not a transactional source snapshot.

Staff see upload mode only. Grant `wf_mines_balance_recon` to the intended
existing GUI view through the administrator's access editor; this change
does not modify the shared access policy or automatically grant staff access.
Administrator views retain their existing workflow access. Manual mode never
authenticates to Insights and has no TEST/PROD execution setting.

## Workbook

| Tab | Content |
| --- | --- |
| Active CO Holds | Uploaded/query hold report, preserving zero/credit balances, missing data and selected hold dates |
| Banner Detail Codes | Uploaded/query transaction detail, preserving signed amounts, duplicates and blank feed dates |
| W&F Collections | All supplied AccountStatusReport_NoBreakout tables, concatenated with creditor, fee type and source file |
| W&F Returned | All supplied ReturnedAccounts tables, concatenated with creditor and source file |
| WF file - worksheet (other worksheets) | Unclassified/additional source value snapshots, retaining their original formatting/layout |

From patch **0.23.3**, the four report tabs sort newest to oldest by From Date,
Feed Date, Placement and Return Date, respectively. Date columns contain real
Excel dates without times. Blank or unreadable sorting dates remain at the end;
unreadable agency date text is retained for review. Sorting preserves source
order for equal dates/times; agency/transaction timestamps determine order
before times are removed. There is no Sources tab. Named agency rows retain
their Source File column.

### Named agency reports (0.22.0)

Keep one batch upload. Routing uses these filename patterns (case-insensitive,
with flexible spaces around hyphens); any five-digit creditor is allowed,
including leading zeros and IDs outside the current 12003–12561 range:

- `Report - AccountStatusReport_NoBreakout - 12003-2026-09-30.xlsx`
- `Report - ReturnedAccounts- 12561-2026-09-30.xlsx`

CSV, XLS and XLSM equivalents are accepted. Filenames that contain a known report type but
have malformed creditor/date components fail explicitly. Otherwise unknown
reports remain on separate source tabs.
There is no demographic parsing or matching in this version.

Known tables must have the supplied column headings on row 6. The parser maps
by heading, tolerating whitespace/case and column order, but rejects missing,
duplicate or unexpected report headings. All matching worksheets in a file
are combined before sorting; additional unrelated worksheets remain separate.
No fixed number of files or creditor whitelist is imposed, and duplicate account
records across reports remain separate rows.

`W&F Collections` retains `Your Accnt #`, `Name`, `Placement`, `Orig. Balance`,
`Curr. Balance`, `Collected`, and `Remarks`, then adds `Creditor`, `Type`, and
`Source File`. Creditor comes from the filename, not row 4. Row 4 supplies the
fee classification: WITH FEES → Fees, NO FEES → No Fees (singular FEE is also
accepted). From patch 0.23.2, blank, unrecognized or conflicting fee labels
produce the literal `unspecified` in Type, without failing
the import. The other row-6 schema and financial completeness checks remain.

`W&F Returned` retains `Your Accnt #`, `Name`, `Consumer #`, `Orig. Balance`,
`Curr. Balance`, `Last Pay Date`, `Placement Date`, `Return Date`, and `Reason`,
then adds `Creditor` and `Source File`. The original report filename is the last
column in both tables. Text identifiers retain leading zeros; numeric identifiers
with a simple all-zero Excel display format retain those displayed zeros.

The owner describes rolling totals immediately after the records, with no blank
separator. From patch **0.23.3**, a Returned row whose Your Accnt # is
`Total Accounts:` followed by a count is removed in full, including its other
values. This explicit footer marker does not require matching financial totals.
For unlabeled totals, removal does not rely on an empty name or blank row.
It checks a candidate's account count against preceding
rows and at least two monetary aggregates against their sums (rounded to cents),
with other descriptive fields empty. Exact SUM formulas over the complete detail
range can also establish a summary. No account data is accepted after an
identified summary; an unexpected layout stops the run.

Rows that do not meet these checks remain in the data, including missing-name
rows. Review final rows before using aggregate values: unlabeled footer layouts
have not yet been validated against an actual agency workbook.
Unknown or incomplete financial data
is not treated as zero to make totals reconcile. These are import checks, not
approved reconciliation/matching rules.

Synthetic acceptance examples: two creditors' account reports become two rows
in one Collections tab with different Creditor/Type/Source File values; a
contiguous count/Orig./Curr./Collected summary matching those source records is
excluded. An incomplete account row is retained. A total that does not reconcile
is retained for review. Returned rows labeled `Total Accounts:1`,
`Total Accounts:5` or `Total Accounts: 2` are excluded in full.
Returned reports use their own nine-column schema and
do not require fee metadata. The eight-Collections/three-Returned/one-other-file
batch is covered by an end-to-end test.

The SQL retains its existing definitions: CO end date strictly after today,
latest qualifying from date per current identity, and all-date selected-code
transactions. See the [holds rules](../../query/AR/holds/README.md) and
[W&F extract rules](../../query/AR/activity/README.md). Upload mode retains
the supplied report rows without applying hidden hold/code/date filters.
Headers identify the expected reports; uploads cannot prove source coverage
when no report count is supplied. A supplied `Report Row Count` is checked and
removed. Dates, including 9999-12-31 hold end dates, remain real Excel dates.
No current balance is derived from W&F data in this version.

Unclassified W&F worksheet names are made Excel-safe, shortened to 31 characters, and given
unique suffixes when needed. Hidden worksheets become visible for review; blank
worksheets remain present. Cell values and number formats retain identifiers
such as text `0000123`; the app does not infer a financial schema or header
location for arbitrary W&F worksheets. Charts, drawings, macros, workbook links,
conditional formatting and Excel calculation models are not copied.

Modern Excel formula cells use their saved cached values, preserving the source snapshot
without moving formulas that could reference renamed worksheets or external
workbooks. A formula without a cached value stops the run and asks for an
Excel-recalculated/saved source or a values-only copy. Cached values are not
independently recalculated or certified current. Text starting with `=` stays
literal text. Source files remain untouched.

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

## Verification and next steps

### PROD extraction diagnostics (0.23.1 patch)

The all-date WOFF/BDRC path, shared by this workflow and Connections, first runs
the normal query. Only a valid count greater than received rows triggers
automatic retries in disjoint integer PIDM ranges; a single capped PIDM is
further split by transaction number. NULL keys are handled separately, not
discarded. No feed-date boundary or new selection filter is introduced. Every
batch must pass the count check and combined rows must match parent counts.
Duplicate transactions remain separate. Missing/invalid counts, changed source
counts or an indivisible key group that still exceeds the cap stop the run.
This batching is not a transactional snapshot; source changes can require a retry.

Failures identify the stage: configuration, sign-in/session validation, querying
one of the two named reports, checking that report's completeness, or closing
the session. Safe API categories distinguish timeouts, connectivity, a query
not completing, and HTTP status failures. Completeness failures distinguish a
missing count, invalid counts, and a capped result with received/expected counts.
These messages appear in the existing GUI error and gui.log traceback; they
do not expose credentials, authentication URLs, query text, server error bodies
or student rows. Unexpected technical exception text remains withheld.

If investigating a PROD extraction failure, run **Collections tracking** and
**W&F - Mines Balance Recon transactions** (WOFF, BDRC) separately in Connections
with PROD selected. Record the report name and exact error, without student
data. Successful sign-in/SELECT 1 does not prove report permissions, SQL
completion or complete results. Uploading both complete saved Insights exports
continues to bypass API extraction while preserving the W&F import workflow.

An extraction error occurs before W&F source parsing. A generic 0.23.0 error
alone cannot establish whether authentication, query execution or truncation
caused it. This diagnostic patch improves failure visibility; it does not
claim to resolve an unobserved server or access problem.

Synthetic tests cover manual/direct-query modes, backend authorization,
batch selection, every source worksheet, duplicate/long names, source data and
formats, year-9999 dates, cached/missing formulas, incomplete API results,
cancellation and output conflicts. They do not validate live Insights access,
replication timing, actual W&F file layouts or the future reconciliation rules.

Review the workbook together using approved source exports, confirm which
W&F fields establish account identity and balances, and agree on the desired
comparisons before implementing matching. Staff operating instructions and
manual fallback belong in the approved office Word SOP; this technical guide
does not deliver or replace that SOP.
