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
debit/credit value and identifies its origin. In 0.30.8, the owner reported
confirmation from their supervisor that **every Debit must have its sign
reversed in Adjusted Amount; every Credit keeps its original value**. This
supersedes the earlier restriction to SIS disbursements. The source column,
rather than account, Source or section, determines the adjustment. It applies
to payments, payables, interest, fees, unclassified/Other activity and footnotes.
A debit of 100.00 becomes -100.00; a debit of -5.00 becomes 5.00. Credits of
100.00 and -5.00 remain 100.00 and -5.00. Zero stays zero.

**Beginning Balance of the FY** already follows the Debit rule introduced in
0.30.4: a 1,000.00 opening balance becomes -1,000.00, and -25.00 becomes 25.00.
Apply this once; do not negate the adjusted balance again. Blank stays blank.
Amount, Debit/Credit, saved FY values, preview, Opening Balances snapshot and
raw source sheets retain their original values and origins.
Adjusted Amount remains editable in Excel, and subtotal SUM formulas update
from those cells. Reusing saved balances applies the sign flip to the output
once per run; it never negates the saved balance itself.
A line with two nonzero amount columns is rejected instead of netted. For a
zero line, one amount column must identify its origin; two zeros or two blanks
are ambiguous. Source strings beginning with `=` remain literal text.

## 1621 classification and signs

Owner clarification for 0.30.5 defines these rules for account **1621**
(LT Loan Receivable - Student), superseding the blanket deferral in
[output #44](https://github.com/JoshuaKosakowsky/HigherEd_Automation/issues/44).
The table includes the confirmed 0.30.8 sign rule:

| Source | Debit/Credit | Section | Activity label | Adjusted Amount |
|---|---|---|---|---|
| SIS | Debit | Loan Activity | Loan Disbursement | Opposite sign of Amount |
| SIS | Credit | Loan Activity | Loan Reversal | Same value as Amount |
| Contains Journal (`*Journal*`) | Debit / Credit | Payment | Payment | Opposite sign / Same value as Amount |
| Any other or blank source | Debit / Credit | 1621 — Unclassified | 1621 — Unclassified | Opposite sign / Same value as Amount |

Match Source case-insensitively after trimming surrounding whitespace. SIS is
an exact match; `SIS Import` stays unclassified. Journal may appear anywhere,
as in `Manual Journal` or `Journal Import`. Do not infer classifications from
the memo. The source rule distinguishes loan disbursements/reversals from
payments; Debit/Credit identifies the kind of SIS loan activity.

Classification does not override the common Debit/Credit sign rule. Unmatched
1621 sources remain visible with that same rule, and the completion message
reports their count for review.

## Workbook

`Current Month Recon` is created first and opens by default. As of 0.30.11 it
replaces the empty `Current Recon` placeholder with the initial summary layout
described below. The seven loan worksheets are:

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
**Payables (2100/2402)**, **Payables (2881)**, **AR (1382)**,
**Interest on loans (5909R)** and **Late fees on loans (8309R)**. Each row has an
Accounting Date; sections sort **newest to oldest** by that date. Same-date rows
retain ascending journal number and original source-row order as tie-breakers.
2100 and 2402 remain distinguishable in Activity labels. Qualifying prior-year
2100 payments appear in the footnote block described below. 2881's recipient is
unspecified. Following owner clarification in 0.30.9, ledger **1382** is included
as **AR** immediately after Payables (2881), replacing its earlier exclusion.
Its debit/credit sign rule and newest-first ordering match the other sections.
The subtotal is labeled **1382 Totals** as of 0.30.10. It sums non-footnoted AR
Adjusted Amount cells and contributes once to Loan Total; an empty AR section
shows a zero subtotal. Qualifying July activity is moved to the AR footnote
below. Only 1021/1036 stay excluded from loan activity while remaining in source
data.
When no opening value is supplied, its Amount, Debit/Credit and Adjusted Amount
cells remain blank. The opening subtotal formula stays blank until Adjusted
Amount contains a number; it does not turn an unknown balance into zero.

Each section ends with its own Adjusted Amount subtotal and one blank row.
An empty section has a zero subtotal without a placeholder transaction. Each
configured loan gets a tab even when it has no journal activity. Unknown
accounts for a configured loan appear in **Other ledger activity — review**
instead of being lost. Non-configured projects stay in the source tab with
their import status. A file with no usable configured-loan activity is rejected.

**Loan Total** appears after the last section on every loan worksheet. Its
Adjusted Amount formula adds Beginning Balance Total and each activity section
subtotal exactly once, including unclassified and Other activity when present.
It updates when Adjusted Amount detail cells are edited. Empty sections
contribute zero; a blank opening subtotal is ignored, leaving the total of
available activity without filling in the missing opening balance.

`Opening Balances` records each project's value, original upload timestamp and
source filename, including those retained from older uploads. `Journal Lines`
preserves source columns, source row numbers and import status. `Trial Balance`
is also included when uploaded. With cached balances, the snapshot supplies
their provenance; the original Trial Balance file is not reconstructed.

### Current Month Recon starting layout

For 0.30.11, the owner supplied **Current Month Recon** from the existing FY27
P03 reconciliation as a layout reference. Only that sheet informed the new
summary. This supersedes the empty-summary scope in
[output #44](https://github.com/JoshuaKosakowsky/HigherEd_Automation/issues/44).
The owner confirmed **all uploaded FY activity**, rather than only the latest
month, and explicitly deferred **AP, AR and variance calculations** until the
new accounting treatment is agreed. This is a starting layout, not a completed
reconciliation or an independent GL tie-out.

The summary retains the reference's title, Loan Information, Interest and Fees,
AP/AR columns, Pending Items and Reconciliation Dates blocks. Its loan order is
Parsons, Combined, CSM Board, Welch, Lewis, Pearson, Bruce; the existing loan-tab
order is unchanged. Obsolete Unisa identifiers are removed, Project contains
only the current six-digit worktag, and historical balances, notes, names and
sign-off dates are never copied from the reference. No reference workbook is
required at runtime or stored in the repository.

| Summary field | Live source / calculation |
|---|---|
| Beginning Balance (Adjusted) | Loan tab's Beginning Balance Total; preserve blank and zero separately |
| 1621 Unclassified | 1621 — Unclassified Total; replaces the old Adjustments/Reclass heading without assuming these entries are adjustments |
| FY Loan Activity (Net) | Loan Activity Total, including disbursements and reversals |
| FY Payments | Payment Total |
| 1621 Net Activity | Sum of Unclassified, Loan Activity and Payments, excluding the opening balance |
| Interest / 5909R | Interest on loans Total from that loan's own tab |
| Late Fees / 8309R | Late fees on loans Total from that loan's own tab |
| Total Interest and Fees | Sum of those two amounts; no separate interest/fee worksheets |
| Pending Items: Loan Total | Existing complete Loan Total, including all regular sections and excluding prior-year footnotes |

Links use the subtotal rows actually generated for each loan, so different
transaction counts and optional Other activity cannot shift them onto the wrong
cells. They update with Excel edits to Adjusted Amount. All signs are retained
as already adjusted; the summary does not flip them again or reuse the old
principal subtraction formulas. The header lists the selected FY and exactly
the uploaded periods, including gaps. It does not assert complete FY coverage.

AP/AR amounts and totals, comparison-balance total, and variances display
**Pending**, without a calculation. Comparison balances, review notes and
completion/review fields are blank editable cells. Entering a comparison
balance does not activate a variance formula in this iteration. The aggregate
beginning balance is also Pending if any loan's opening balance is missing;
each missing opening remains blank while its Loan Total includes available
activity, as before. A supplied zero opening is still numeric zero.

Synthetic acceptance examples:

- Opening 1,000 appears as -1,000. SIS debit 100 and SIS credit 25 give net loan
  activity -75. Journal credit 40 and unclassified debit 3 give 1621 Net Activity
  -38. Interest credit 10 and fee debit 2 give Total Interest and Fees 8. These
  examples use multiple uploaded months, all included in the summary.
- Adding offsetting 2100/2402 amounts (-5 and 5), 2881 credit 7, regular 1382
  credit 11 and Other debit 4 gives Loan Total -1,016. Prior-year 2100/1382
  footnotes do not enter this total. The AP/AR and variance fields remain
  Pending rather than treating these components as amounts owed to/from the
  Foundation before their treatment is confirmed.
- A blank Bruce opening remains blank; an explicitly supplied zero remains
  zero. The total opening stays Pending until all seven openings are supplied,
  while existing per-loan activity totals remain available.

### Prior fiscal year payment footnote

Owner clarification in 0.30.7 moves a journal line to the bottom of its loan tab
when all three conditions hold: Ledger Account is **2100**, Source is exactly
**Supplier Invoice Payment**, and Accounting Date is on or before **July 31 of
the selected FY's opening calendar year**. Source matching ignores case and
surrounding whitespace. The existing FY validation still applies: for FY2027,
only July 1–31, 2026 qualifies, including July 31. August 1, 2026 and later
stay in ordinary activity; a date outside FY2027 is still rejected.

Per the owner's explicit confirmation, these payments are **excluded from
Payables Total and Loan Total**. They appear once, below Loan Total, under:

> Footnote* — Payment of a prior fiscal year obligation recorded in the current fiscal year.

The footnote rows retain all transaction columns and original Amount values, with
`Payables — 2100*` as their Activity label. They remain newest first, with the
existing journal/source-row tie-breakers. Only loans with qualifying rows show
the footnote. The raw Journal Lines sheet preserves each line and identifies
its exclusion from activity totals in Import Status. Their Adjusted Amount
follows the common sign rule: negate Debit, preserve Credit. Footnote placement
does not apply a second adjustment or change saved balances.

### Prior fiscal year AR footnote

In 0.30.10, the owner extended the same inclusive July 31 cutoff to **1382**
and explicitly confirmed that it applies to **every Source**, including blank
Source values. For FY2027, July 1–31, 2026 activity moves below Loan Total;
August 1, 2026 onward stays in the regular AR section below Payables (2881).
The selected FY validation remains in effect, so prior/next-FY dates are still
rejected. This does not broaden the Source restriction for 2100.

Footnoted 1382 rows are excluded from **1382 Totals** and **Loan Total**. They
appear once in a separate AR block, after the 2100 block when both are present:

> Footnote** — Prior fiscal year accounts receivable activity recorded in the current fiscal year.

These rows use Activity **AR\*\*** and retain the transaction details and common
Debit/Credit sign rule. Each footnote block remains newest first and is shown
only when that loan has qualifying rows. Journal Lines retains the original
data and identifies prior-year AR exclusions in Import Status. Regular AR
detail labels remain **AR**; its subtotal is exactly **1382 Totals**.

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
  Adjusted Amount -100 and 100. Their Payment subtotal is zero.
- Beginning Balance Total -1,000, Payment Total 200 from two 100 credits, and
  Loan Activity Total -75 produce Loan Total -875 when all other sections are
  zero. Changing a payment's Adjusted Amount from 100 to 125 updates Payment
  Total to 225 and Loan Total to -850. A blank opening balance with only a 75
  credit payment gives Loan Total 75.
- In FY2027, a 2100 Supplier Invoice Payment debit dated July 31, 2026 for 100
  moves below Loan Total with Adjusted Amount -100 and the footnote, contributing
  nothing to either total. Another 2100 Supplier Invoice Payment debit dated
  August 1, 2026 for 40 stays in Payables and contributes -40 to Payables Total
  and Loan Total. A July 31 line for 2402 or a different Source is not moved.
  If all activity is footnoted,
  Payables Total is zero and Loan Total reflects the opening subtotal alone.
- A 1621 debit of 100 with Source `SIS Import` remains unclassified with Amount
  100 and Adjusted Amount -100; a 2100 SIS debit of 100 remains a Payable with
  Adjusted Amount -100. Interest, late fees and Other ledger debits follow the
  same sign rule. Credit values remain unchanged in every section.
- A 1382 debit of 100 and credit of 25 dated August 1 or later appear as two AR
  rows directly below Payables (2881), with Adjusted Amounts -100 and 25.
  1382 Totals is -75 and adds -75 to Loan Total. Source values remain 100 and 25
  in the original order on Journal Lines, with Import Status Included.
- For FY2027, a 1382 debit of 100 dated July 31, 2026 moves to the AR footnote
  regardless of Source and keeps Adjusted Amount -100. A 1382 credit of 25
  dated August 1, 2026 stays in AR, giving 1382 Totals 25. With Beginning Balance
  Total -1,000 and no other activity, Loan Total is -975. Footnote edits do not
  affect either total.
- Two Payment lines occupy rows 10–11, subtotal 12, blank 13, next section 14.
  Five lines occupy 10–14, subtotal 15, blank 16, next section 17. With none,
  subtotal 10, blank 11, next section 12.
- July/August transactions retain individual dates under the same activity
  sections, with August activity above July activity. Identical lines are kept;
  source worksheets retain their uploaded order. SIS and Journal transactions
  have separate section subtotals, without repeated monthly blocks.

## Deferred work and verification

Additional 1621 classifications (including any Adjustment category), final
Current Month Recon accounting rules (AP, AR and variance), further Adjusted
Amount rules, 2100/2402 net-zero checks and JE preparation remain deferred.
Section subtotals sum the editable Adjusted Amount cells; they are not completed
reconciled balances.

Synthetic tests are in `tests/python/test_csmf_loans.py` and
`tests/python/test_gui_csmf_loans.py`. Shared reader changes also run the existing
graduate-contract source/service tests. Real Workday exports, native Windows
Excel behavior and shared-drive operation need owner acceptance. Technical
documentation here does not replace the office's Word SOP/manual fallback.
