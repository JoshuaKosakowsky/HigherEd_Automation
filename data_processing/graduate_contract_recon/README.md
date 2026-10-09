# 1305 Graduate Contract Receivable reconciliation

The **1305 Graduate Contract Recon** workflow reads an original Workday export
and a complete **Banner Activity by Date & Detail Code** Insights download.
Workday is always uploaded manually. Staff can only upload Banner data;
administrators can upload it or extract it from **PROD Insights**, using the
existing JWT/SSO session and completeness-checked Banner activity extractor.
This is read-only in both source systems.

## Inputs and scope

- Upload XLSX, XLSM or UTF-8 CSV exports. Headers are detected within the first
  30 rows; column order and worksheet name do not determine the mapping. A
  workbook must contain exactly one matching source worksheet for each input.
  XLSX/XLSM readers scan actual worksheet contents even when an export stores
  an incorrect used range, such as A1 for a full Workday report.
- Workday requires Accounting Date, Ledger Account, Journal Source, Memo, and
  debit/credit amounts. Workday Debit/Credit Amount, Ledger Debit/Credit Amount,
  and Line Memo are supported header aliases. Journal Entry/Number, External
  Reference/ID, CWID and Journal Line ID are used when supplied. Workbooks with
  competing amount columns or missing ledger accounts are not guessed into shape.
  Previously edited reconciliation reports may not be valid original inputs.
- Banner requires ID, Description, Detail Code, Amount, Feed Document, Feed Date.
  The current Insights report's quoted headers, transaction description and
  final Transaction User field are supported. Metadata's detail-code description
  does not replace the transaction Description. Additional source columns stay
  in the raw source tab. Legacy header layouts are accepted internally, but the
  staff form advertises only the Insights download.
- Enter **inclusive** start/end dates and at least one approved detail code.
  **No detail codes are preselected.** The workflow does not establish which
  codes post to ledger 1305; the reviewer chooses them. Workday is restricted to
  ledger account 1305. The two sources use Accounting Date and Feed Date
  respectively. Feed timing differences remain review items.
- Dates default to the previous calendar month. Supply actual boundaries for
  periods, quarters, years, or multiple years. The fiscal calendar follows
  `shared/fiscal_period.ps1`: July P01, June P12, fiscal year named for its ending
  year, and three periods per fiscal quarter. Adjusting periods are not inferred.

## Matching and output

Workday **SIS** External Reference is matched to Banner **Feed Document**, falling
back to the SIS Memo when the reference is blank. Numeric references such as an
Excel number and its text equivalent match. Other text uses trimmed whitespace
and case-insensitive comparison, with no fuzzy matching. Keys include fiscal year
and period, preventing a match across unrelated time scopes. A feed appearing in
multiple periods is flagged for timing/reused-reference review.

Both sources must be present and **debits and credits must each agree in exact
cents**. A zero net difference does not hide offsetting errors or a missing zero
amount row. Positive Banner amounts are debits and negative amounts are credits;
the existing September example supports this convention. Non-SIS Workday
journals are retained separately. Invalid dates/amounts and duplicate transaction
identities block automatic substitution; suspect rows are retained in the source
tabs with selection status. No rows are deduplicated.

The output uses plain worksheets, freeze panes and ordinary filters, without
Excel Tables. All financial results are calculated by Python as a snapshot;
editing a source tab does not recalculate them. Rerun with changed input files.
Combined begins with CWID, Term, Recon Period and Journal Number, following the
employee's Journal Lines Data layout. Feed blocks follow the first Workday
source occurrence within each fiscal period; all Workday rows in the block come
before its Banner rows. Banner rows without a Workday feed match follow last.
Document, Combined and source selection statuses retain review warnings; the
workbook does not include separate Verification or Exceptions tabs.
Journal Number displays only a six- or seven-digit SIS Memo / Banner Feed
Document posting code. CWIDs, manual memos and other reference formats leave
this column blank. Original Workday Journal Entry values stay in Workday Data.

| Sheet | Use |
| --- | --- |
| 1305 Combined | Workday rows anchor each feed group, followed by its Banner detail. Matched Workday summaries remain visible as **Summary reference**, with zero Activity Debit/Credit. Unmatched/differing Banner rows remain **Review only**, also with zero Activity Debit/Credit. Sum **Activity Debit/Credit** to count financial activity once. |
| 1305 Doc Recon | Union of feed documents from both sources, with separate debit/credit differences, row counts, calculated status, and editable Notes/Review Status. |
| 1305 CWID Recon | Banner plus non-SIS Workday student activity by fiscal period. Sponsor account descriptions may supply the student's CWID. Missing/conflicting IDs are flagged; no SIS student allocation is invented. Net Period Activity is not an ending balance. |
| 1305 Period Totals | Period/quarter/year labels and source/combined totals across the selected date range, including periods with no supplied activity. |
| Workday Data / Banner Data | Original selected worksheet contents with source row numbers and selection dispositions. Excluded rows are preserved. Source text is stored literally, including values beginning with `=`. |

CWIDs follow the supplied VBA rule: eight digits beginning with `10`, taken
from the explicit ID or the leading description/memo token. A valid Banner
account ID that disagrees with the leading description ID is not silently
assigned to either student. A sponsor ID is not treated as a student ID.

API results are checked against a private full-population row count and split
into non-overlapping date windows if capped. A capped single day or failed API
request does not publish a workbook. Uploaded exports cannot prove completeness;
check source-system row counts and totals for the same scope. The slim Insights
report omits transaction number, so duplicate transaction identities cannot be
independently checked for that input. Legitimate identical rows remain intact.
The program does not claim that agreeing source totals establish complete exports
or independent CWID-level agreement for summarized Workday SIS lines.

A new result is written exclusively and staged before publication. Existing
files and inputs are never overwritten. Cancellation prevents publication.
Prior reviewer notes from an older result are not automatically transferred.
Do not commit source exports or generated financial workbooks.

## Access and deployment

The repository's default and example access policies include **Grad Contract
Sponsor**, granted only `graduate_contract_recon`. Administrators retain all
workflows. The source selector offers one upload option for non-admin users and
both upload/PROD options for admins. The service also rechecks current admin
authorization before SQL, independent of the GUI control.

Existing deployed shared access policies are preserved by application updates.
On the work PC, use **Access Management → view permissions** to grant
`graduate_contract_recon` to the existing **Grad Contract Sponsor** view if it
is not already present. Keep the employee assigned to that view; no employee
login is guessed or reassigned by this feature. New policies seeded from the
repository include the grant. The runtime policy remains authoritative for
revocation and visibility.

## Verification

Synthetic tests cover exact-cent gross matching, zero/missing groups, reversals,
many-to-many hazards, numeric/reference fallback, ledger/date/code selection,
fiscal-year and quarter boundaries, attribution conflicts, invalid/duplicate
rows, literal source text, overwrite/cancellation safeguards, and admin/staff
source access. API tests use synthetic responses rather than live credentials.
Validate a real matching period against the authoritative exports before using
the result to complete her reconciliation.
