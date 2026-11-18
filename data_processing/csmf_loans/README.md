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
- Upload **Trial Balance** on first use of that FY or when updating any opening
  balances. A file may contain just one project. Otherwise leave this input
  empty to reuse the shared saved balances.
- Choose an existing approved output folder and a new `.xlsx` filename.
- **Review & run** displays the selected FY, all seven balances (including
  blanks), each project's actual upload date, and which values come from the
  new upload or saved data. It also shows the latest upload's filename/date.
  Cancelling review makes no storage changes.

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
not used. Owner feedback from the first R1 run established the following rules
in 0.30.2, superseding the initial complete-upload requirement in #25:

- A loan may be omitted from the upload. Keep its saved value and original
  date/source, or leave it blank if no balance has ever been supplied.
- An included project with an empty/null **Debit Amount** explicitly sets that
  project's balance to blank. Empty cells, whitespace and literal `null`/`NULL`
  are accepted. A numeric zero remains a supplied zero, distinct from blank.
- Update only projects actually included in the upload. A one-project update
  does not erase other loans or change their dates/sources, and never affects
  another FY.
- Duplicate rows for one project and invalid nonblank amounts remain errors.
  The upload must contain at least one configured loan row; unrelated or empty
  reports do not update the saved file.

Bruce (694516) is still reconciled because collections may occur even though
the loan has not been used for a long time. Its missing opening balance must
not block processing or remove its tab/activity. The same omission/blank rules
apply to every configured loan.

Amounts use exact cents during parsing. Journal activity preserves the original
debit/credit value and identifies its origin. Adjusted Amount copies Amount
except for the confirmed 1621 SIS debit rule below. Following owner feedback in
0.30.4, **Beginning Balance of the FY** uses the opposite sign for Adjusted
Amount: a 1,000.00 opening balance
becomes -1,000.00, and -25.00 becomes 25.00. Zero stays zero and blank stays
blank. Its Amount, Debit/Credit, saved FY value, preview and Opening Balances
snapshot retain the original source value and origin.
Adjusted Amount remains editable in Excel, and subtotal SUM formulas update
from those cells. Reusing saved balances applies the sign flip to the output
once per run; it never negates the saved balance itself.
A line with two nonzero amount columns is rejected instead of netted. For a
zero line, one amount column must identify its origin; two zeros or two blanks
are ambiguous. Source strings beginning with `=` remain literal text.

## 1621 classification and signs

Owner clarification for 0.30.5 defines these rules for account **1621**
(LT Loan Receivable - Student), superseding the blanket deferral in
[output #44](https://github.com/JoshuaKosakowsky/HigherEd_Automation/issues/44):

| Source | Debit/Credit | Section | Activity label | Adjusted Amount |
|---|---|---|---|---|
| SIS | Debit | Loan Activity | Loan Disbursement | Opposite sign of Amount |
| SIS | Credit | Loan Activity | Loan Reversal | Same value as Amount |
| Contains Journal (`*Journal*`) | Either | Payment | Payment | Same value as Amount |
| Any other or blank source | Either | 1621 — Unclassified | 1621 — Unclassified | Same value as Amount |

Match Source case-insensitively after trimming surrounding whitespace. SIS is
an exact match; `SIS Import` stays unclassified. Journal may appear anywhere,
as in `Manual Journal` or `Journal Import`. Do not infer classifications from
the memo. The source rule distinguishes loan disbursements/reversals from
payments; Debit/Credit identifies the kind of SIS loan activity.

Only Adjusted Amount is sign-adjusted. A SIS debit of 100.00 becomes -100.00;
a SIS debit of -5.00 becomes 5.00. Zero stays zero. SIS credits and Journal
payments retain their value, including any negative sign. These rules do not
change other ledger accounts, original Amount/Source/Debit/Credit, raw source
sheets or saved FY balances. Unmatched 1621 sources remain visible, and the
completion message reports their count for review.

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
are **Payment**, **Loan Activity**, **1621 — Unclassified**,
**Payables (2100/2402)**, **Payables (2881)**,
**Interest on loans (5909R)** and **Late fees on loans (8309R)**. Each row has an
Accounting Date; sections sort **newest to oldest** by that date. Same-date rows
retain ascending journal number and original source-row order as tie-breakers.
2100 and 2402 remain distinguishable in Activity labels. 2881's recipient is
unspecified. 1021/1036/1382 do not enter loan activity but remain in source data.
When no opening value is supplied, its Amount, Debit/Credit and Adjusted Amount
cells remain blank. The opening subtotal formula stays blank until Adjusted
Amount contains a number; it does not turn an unknown balance into zero.

Each section ends with its own Adjusted Amount subtotal and one blank row.
An empty section has a zero subtotal without a placeholder transaction. Each
configured loan gets a tab even when it has no journal activity. Unknown
accounts for a configured loan appear in **Other ledger activity — review**
instead of being lost. Non-configured projects stay in the source tab with
their import status. A file with no usable configured-loan activity is rejected.

`Opening Balances` records each project's value, original upload timestamp and
source filename, including those retained from older uploads. `Journal Lines`
preserves source columns, source row numbers and import status. `Trial Balance`
is also included when uploaded. With cached balances, the snapshot supplies
their provenance; the original Trial Balance file is not reconstructed.

## Persistence and partial updates

The existing Mines OneDrive resolver locates the shared Bursar automation folder:
`GRP-Bursar Office - General/Y-Brswork/Staff Folders/.highered_automation/`.
Balances are stored in `csmf_opening_balances/FY2027.json` (one file per FY),
under the local Mines OneDrive root (`OneDriveCommercial`, or the existing
`USERPROFILE/OneDrive - Colorado School of Mines` fallback). The XLSX workbook
is separate and goes to the location selected in **Save CSMF workbook as**.

JSON schema 2 stores decimal strings or JSON `null`, plus each project's
source filename/hash and timezone-aware upload timestamp. A never-supplied
project has null metadata as well. Top-level metadata identifies the latest
upload to that FY. Existing schema-1 files still load with their original
shared date/source applied to each project. Reading them does not rewrite
them; the next successful upload saves schema 2 and backs up the prior file.
No source transactions or student records are stored in the JSON.

Previewing does not save. A successful update run saves the previewed merged
balances; a run using saved balances leaves the file unchanged. Before atomic
replacement, the prior file for that FY is backed up as `FY2027.backup.json`.
A local lock and
digest check reject changes made since preview. Cancellation is accepted until
final publication; failed validation or saving preserves the previous cache.
If cache replacement fails after workbook publication, that run's newly created
workbook is removed. Existing outputs are never overwritten.

OneDrive is asynchronous: these local controls do not provide distributed
locking across offline computers. Synchronize before editing shared balances;
do not run simultaneous updates from separate workstations. Invalid saved
JSON stops the run; restore its `.backup.json` or have the owner repair the cache.

## Synthetic acceptance examples

- Upload opening balance 1,000.00 on July 10. Run August 10 without Trial Balance:
  the same 1,000.00 and July 10 timestamp are displayed and used, even if an
  accounting adjustment occurred upstream on July 20. The app cannot infer it.
- Upload only Parsons with 1,500.00 on August 10: update Parsons and its date
  after success. Combined's earlier value and July 10 date/source stay intact.
  Preserve the prior backup and all other FY files.
- Omit Bruce (694516) on first use: save a null opening balance, create its
  worksheet, and include a later collection of 75.00 as ordinary activity.
- Supply Bruce with a blank/null amount: keep/set it blank; supply 0.00 instead
  to record an explicit zero. Omit it on a later upload to retain its saved state.
- Opening Amount 1,000.00 produces Adjusted Amount -1,000.00 and opening subtotal
  -1,000.00. A later run using the saved 1,000.00 again produces -1,000.00.
- Two 1621 SIS lines, debit 100 and credit 25, appear as Loan Disbursement and
  Loan Reversal. Their Adjusted Amounts are -100 and 25, and Loan Activity
  subtotal is -75. Original Amounts remain 100 and 25.
- Two 1621 Journal lines, debit 100 and credit 100, appear as Payments with
  Adjusted Amount 100 each. Their Payment subtotal is 200, not net zero.
- A 1621 line with Source `SIS Import` remains unclassified with its original
  value; a 2100 SIS debit of 100 remains a Payable with Adjusted Amount 100.
- Two Payment lines occupy rows 10–11, subtotal 12, blank 13, next section 14.
  Five lines occupy 10–14, subtotal 15, blank 16, next section 17. With none,
  subtotal 10, blank 11, next section 12.
- July/August transactions retain individual dates under the same activity
  sections, with August activity above July activity. Identical lines are kept;
  source worksheets retain their uploaded order. SIS and Journal transactions
  have separate section subtotals, without repeated monthly blocks.

## Deferred work and verification

Additional 1621 classifications (including any Adjustment category), full
Current Recon/current-month output, further Adjusted Amount rules, 2100/2402
net-zero checks and JE preparation remain deferred. Section subtotals sum the
editable Adjusted Amount cells; they are not completed reconciled balances.

Synthetic tests are in `tests/python/test_csmf_loans.py` and
`tests/python/test_gui_csmf_loans.py`. Shared reader changes also run the existing
graduate-contract source/service tests. Real Workday exports, native Windows
Excel behavior and shared-drive operation need owner acceptance. Technical
documentation here does not replace the office's Word SOP/manual fallback.
