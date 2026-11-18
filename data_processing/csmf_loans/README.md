# CSMF Loans — R1

Version 0.30.0 introduces `csmf_loans` under Accounts Receivable. R1 reads
Workday files, prepares loan activity, and saves FY opening balances. It does
not complete a reconciliation. The owner confirmed this scope in
[parent #24](https://github.com/JoshuaKosakowsky/HigherEd_Automation/issues/24),
[source/storage #25](https://github.com/JoshuaKosakowsky/HigherEd_Automation/issues/25),
and [output #44](https://github.com/JoshuaKosakowsky/HigherEd_Automation/issues/44).

## Inputs and run review

- Select one **fiscal ending year**. FY2027 is July 2026–June 2027. The default
  follows the previous calendar month, including June's FY when run in July.
- Upload **Find Journal Lines - GA**, including every month that should appear.
  All source activity comes from this file. Previous outputs are never inputs.
  R1 handles one FY per run; a relevant line from another FY is reported rather
  than silently dropped or combined with the wrong opening balance.
- Upload **Trial Balance** on first use of that FY or when replacing its opening
  balances. Otherwise leave this input empty to reuse the shared saved balances.
- Choose an existing approved output folder and a new `.xlsx` filename.
- **Review & run** displays the selected FY, all seven balances, their source
  filename and last-uploaded/updated timestamp before execution. Cancelling
  review makes no storage changes. A supplied replacement is labeled as new.

No Banner/Insights login or TEST/PROD choice is needed. Existing Access Management
controls apply: administrators can see the workflow; grant `csmf_loans` to an
appropriate existing staff view without replacing the deployed access policy.

## Source formats and exact values

XLSX, XLSM and UTF-8 CSV are supported. The shared report reader detects headers
in the first 30 rows and requires exactly one matching worksheet. Columns are
matched by normalized header, not fixed positions. Sources are never modified.

Journal headers: **Project, Ledger Account, Journal Number, Accounting Date,
Source** (or **Journal Source**), **Line Memo, Ledger Debit Amount, Ledger Credit
Amount**. Line Memo becomes Description. Dates determine periods and ordering.
No repeated monthly section blocks or row deduplication are applied.

Trial Balance requires **Worktags** and **Debit Amount**. Accounting Date is
optional and is not the cache timestamp or selected FY authority. The user
selects the correct FY. Extract the exact `Project: 694511` token from, for
example, `Fund: 32 Other tags <br> Project: 694511 Parson Loan`. HTML breaks,
newlines and other tags do not change project matching. Loan-name spelling is
not used. There must be one balance for each configured project; duplicates,
missing balances and invalid amounts stop the run without replacing saved data.

Amounts use exact cents during parsing. R1 preserves the original debit/credit
value and identifies its origin. Adjusted Amount is initially a copy of Amount.
It is editable in Excel, and section SUM formulas update from those cells.
A line with two nonzero amount columns is rejected instead of netted. For a
zero line, one amount column must identify its origin; two zeros or two blanks
are ambiguous. Source strings beginning with `=` remain literal text.

## Workbook

`Current Recon` is created first and left empty. The seven loan worksheets are:

| Project | Worksheet |
|---|---|
| 694511 | Parsons - 694511 |
| 694512 | Combined - 694512 |
| 694513 | CSM Board - 694513 |
| 694514 | Welch - 694514 |
| 694516 | Bruce - 694516 |
| 694518 | Lewis - 694518 |
| 694521 | Pearson - 694521 |

Rows 1–6 contain the specified report/column headers. Row 7 is the FY opening
balance, row 8 its subtotal, row 9 blank, and activity begins at row 10. Sections
are **1621 — Unclassified**, **Payables (2100/2402)**, **Payables (2881)**,
**Interest on loans (5909R)** and **Late fees on loans (8309R)**. Each row has an
Accounting Date; sections sort by date, journal number, then original row order.
2100 and 2402 remain distinguishable in Activity labels. 2881's recipient is
unspecified. 1021/1036/1382 do not enter loan activity but remain in source data.

Each section ends with its own Adjusted Amount subtotal and one blank row.
An empty section has a zero subtotal without a placeholder transaction. Each
configured loan gets a tab even when it has no journal activity. Unknown
accounts for a configured loan appear in **Other ledger activity — review**
instead of being lost. Non-configured projects stay in the source tab with
their import status. A file with no usable configured-loan activity is rejected.

`Opening Balances` records the values/timestamp actually used. `Journal Lines`
preserves source columns, source row numbers and import status. `Trial Balance`
is also included when uploaded. With cached balances, the snapshot supplies
their provenance; the original Trial Balance file is not reconstructed.

## Persistence and replacement

The existing Mines OneDrive resolver locates the shared Bursar automation folder:
`GRP-Bursar Office - General/Y-Brswork/Staff Folders/.highered_automation/`.
Balances are stored in `csmf_opening_balances/FY2027.json` (one file per FY),
with decimal strings, source filename/hash, schema version and timezone-aware
update timestamp. No source transactions or student records are stored there.

Previewing does not save. A successful replacement run saves the previewed new
balances and timestamp; a run using saved balances leaves the file unchanged.
The previous FY file is backed up before atomic replacement. A local lock and
digest check reject changes made since preview. Cancellation is accepted until
final publication; failed validation or saving preserves the previous cache.
If cache replacement fails after workbook publication, that run's newly created
workbook is removed. Existing outputs are never overwritten.

OneDrive is asynchronous: these local controls do not provide distributed
locking across offline computers. Synchronize before editing shared balances;
do not run simultaneous replacements from separate workstations. Invalid saved
JSON stops the run; restore its `.backup.json` or have the owner repair the cache.

## Synthetic acceptance examples

- Upload opening balance 1,000.00 on July 10. Run August 10 without Trial Balance:
  the same 1,000.00 and July 10 timestamp are displayed and used, even if an
  accounting adjustment occurred upstream on July 20. The app cannot infer it.
- Upload a replacement with 1,500.00 on August 10: replace that FY's values and
  timestamp after success, preserve the prior backup and all other FY files.
- Debit 100 and credit 100 are two rows with matching direction labels and
  Adjusted Amount 100 each. Their section subtotal is 200, not net zero.
- Two 1621 lines occupy rows 10–11, subtotal 12, blank 13, next section 14.
  Five lines occupy 10–14, subtotal 15, blank 16, next section 17. With none,
  subtotal 10, blank 11, next section 12.
- July/August transactions retain individual dates under the same activity
  sections. No Payment/Adjustment classification is inferred for 1621.

## Deferred work and verification

1621 classification, full Current Recon/current-month output, final Adjusted
Amount rules, 2100/2402 net-zero checks and JE preparation remain deferred.
Section subtotals are source-value totals, not reconciled balances.

Synthetic tests are in `tests/python/test_csmf_loans.py` and
`tests/python/test_gui_csmf_loans.py`. Shared reader changes also run the existing
graduate-contract source/service tests. Real Workday exports, native Windows
Excel behavior and shared-drive operation need owner acceptance. Technical
documentation here does not replace the office's Word SOP/manual fallback.
