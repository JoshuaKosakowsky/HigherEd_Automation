# W&F - Mines Balance Recon (early source review)

App 0.21.0 adds an initial workspace for the analyst and owner to review the
source data together before agreeing on matching/reconciliation rules. It
collects sources into a new workbook; it does not identify differences, match
accounts, determine agency status, or change Banner or W&F records.

## Inputs and access

The GUI has three separate sections:

- **Insights data**: upload the complete **Collections tracking** report and
  **W&F - Mines Balance Recon transactions** report. Both XLSX/XLSM and UTF-8
  CSV exports are supported. The two matching source tables are required;
  the reader allows up to 30 title/header rows and rejects ambiguous tables.
- **Williams and Fudge uploads**: select/drop several XLSX/XLSM workbooks at
  once. Additional browse/drop batches append to the list. Repeated paths are
  not added twice. Files with the same name in different folders remain
  separate. Every worksheet, including hidden and empty ones, is included.
  Older XLS files must first be converted to XLSX in Excel.
- **Outputs**: choose an approved existing folder and a new XLSX filename.

Administrators can instead choose **Run SQL from PROD Insights** in the
Insights section. This replaces both report uploads with direct queries of
the existing `collections_tracking` and `wf_mines_balance_transactions`
catalog reports. W&F uploads are still required. Codes default to WOFF/BDRC
and are editable for the direct query. The workflow rechecks administrator
access before authentication, uses existing browser/cached-session controls,
shows the normal PROD review, and requires both completeness checks to pass.
API-capped/malformed results stop the entire run without saving a workbook;
complete Insights downloads are the manual fallback. Separate queries in one
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
| WF file - worksheet (one per original worksheet) | W&F value snapshot with cell formats, row/column sizes, merged cells and freeze panes retained |
| Sources | Output-tab mapping to original file/worksheet or query; copied row counts including headers |

The SQL retains its existing definitions: CO end date strictly after today,
latest qualifying from date per current identity, and all-date selected-code
transactions. See the [holds rules](../../query/AR/holds/README.md) and
[W&F extract rules](../../query/AR/activity/README.md). Upload mode retains
the supplied report rows without applying hidden hold/code/date filters.
Headers identify the expected reports; uploads cannot prove source coverage
when no report count is supplied. A supplied `Report Row Count` is checked and
removed. Dates, including 9999-12-31 hold end dates, remain real Excel dates.
No current balance is derived from W&F data in this version.

W&F worksheet names are made Excel-safe, shortened to 31 characters, and given
unique suffixes when needed. Sources records the original file and worksheet
for every renamed tab. Hidden worksheets become visible for review; blank
worksheets remain present. Cell values and number formats retain identifiers
such as text `0000123`; the app does not infer a financial schema or header
location for arbitrary W&F worksheets. Charts, drawings, macros, workbook links,
conditional formatting and Excel calculation models are not copied.

Formula cells use their saved cached values, preserving the source snapshot
without moving formulas that could reference renamed worksheets or external
workbooks. A formula without a cached value stops the run and asks for an
Excel-recalculated/saved source or a values-only copy. Cached values are not
independently recalculated or certified current. Text starting with `=` stays
literal text. Source files remain untouched.

The workflow supports cancellation before publication, stages the complete
workbook and publishes using exclusive creation. Errors/cancellation do not
leave a partial final workbook, and existing files/source paths cannot be
overwritten. Inputs must fit Excel worksheet limits; no source rows are
silently truncated.

## Verification and next steps

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
