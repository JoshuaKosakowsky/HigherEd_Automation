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
- Workday uploads (1305 export and optional Grad Contract Worktag) are grouped
  together in a pale-blue section, followed by the Banner source section.
  The form is titled **Inputs**; the save location has its own **Outputs** section.
- **Run SQL from PROD Insights** shows inclusive start/end dates and detail codes.
  The 1305 workflow prepopulates **TPDT, TPLE, Z0LE**. Reviewers can add, change
  or remove codes for the reconciliation; at least one code is required.
  These are editable workflow defaults, not an inferred ledger mapping.
  Workday is restricted to
  ledger account 1305. The two sources use Accounting Date and Feed Date
  respectively. Feed timing differences remain review items.
- **Upload Banner Insights file** hides and ignores extraction dates/codes.
  Upload complete exports for the same intended scope. The reconciliation uses
  all valid detail codes in the Banner upload and the earliest/latest valid
  dates across Workday 1305 and Banner rows. It does not silently apply prior SQL
  selections or previous-month defaults. Invalid source rows still require review;
  different source coverage remains visible in document/period differences.
- SQL dates default to the previous calendar month. Supply actual boundaries for
  periods, quarters, years, or multiple years. The fiscal calendar follows
  `shared/fiscal_period.ps1`: July P01, June P12, fiscal year named for its ending
  year, and three periods per fiscal quarter. Adjusting periods are not inferred.
- **Grad Contract Worktag** optionally accepts the Workday **Find Journal Lines**
  export. Only Line Memo and Worktags are used (M and O in the supplied layout;
  mapping uses headers). Student CWIDs are eight digits beginning with `10`.
  SU/FA/SP/WI plus two-digit year are separated into term code and description
  (for example SU26 → Summer 2026). Names and unrelated source fields are omitted.
  Only Grant, Project and Operating Account with six-digit numbers are kept;
  leading zeros remain intact.
- **Project**, **Grant**, and **Operating Account** on CWID Recon match by CWID
  across the supplied worktag export. Each field lists every distinct six-digit
  number for that type, separated by semicolons; leading zeros remain intact.
  The Worktags tab preserves the term for each assignment. These are student
  metadata, not allocation of amounts; fiscal periods are not assumed to match
  academic terms. Upload the relevant worktag population. Missing types, unmatched
  CWIDs, and runs without the optional upload leave these three fields blank.
  Repeated identical CWID/term/tag assignments are collapsed. Ambiguous/missing
  CWIDs are not assigned; malformed rows contribute to the worktag warning count.

## Matching and output

Workday **SIS** External Reference is matched to Banner **Feed Document**, falling
back to the SIS Memo when the reference is blank. Numeric references such as an
Excel number and its text equivalent match. Other text uses trimmed whitespace
and case-insensitive comparison, with no fuzzy matching. Keys include fiscal year
and period, preventing a match across unrelated time scopes. A feed appearing in
multiple periods is flagged for timing/reused-reference review.

Both sources must be present and **debits and credits must each agree in exact
cents**. A zero net difference does not hide offsetting errors or a missing zero
amount row. Positive Banner amounts are debits and negative amounts are credits, after
the TPS00080 sign correction described below. Non-SIS Workday
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
Source selection statuses retain review warnings; the
workbook does not include separate Verification or Exceptions tabs.
Combined includes a row only when its normalized Memo / Feed Document is exactly
six or seven digits. It keeps the complete reference in both Journal Number and
Memo / Feed Document; it does not blank a reference and retain the row. There is
no current-year prefix requirement. Other Workday activity with a numeric memo
qualifies under the same rule. Rows failing the filter remain in the raw source
tabs and still contribute to document/CWID/period calculations and controls.
Original Workday Journal Entry values stay in Workday Data. Alternating retained
journal groups have a light grey background across their Workday and Banner rows.
Combined omits Status, Source Row, Included in Activity, Quarter and Activity
Debit/Credit. Use Period Totals for source comparisons: Combined is a filtered
review view and displays both summaries and detail.

| Sheet | Use |
| --- | --- |
| 1305 Combined | Workday rows anchor each feed group, followed by its Banner detail, with alternating grey journal groups. Both sources' Debit/Credit remain visible for comparison, including the TPS00080 correction; Period Totals keeps each source separate. |
| 1305 Doc Recon | Union of feed documents from both sources, with signed Workday Total Amt (SIS), Banner Total Amt, Difference (Banner minus Workday), and editable Notes. |
| 1305 CWID Recon | Signed Banner Total Amt and Workday Total Amt (non-SIS only) by student/fiscal period. Net Period Activity is Banner minus Workday, not an ending balance. Sponsor descriptions may supply the CWID; no SIS student allocation is invented. Notes / Explanation remains; Project, Grant, Operating Account, Ledger Acct and Spend Cat provide student coding. |
| 1305 Period Totals | Fiscal Year, Period, Quarter, Workday SIS Amt, Workday Other Amt, Banner Amt, Difference, Notes. Difference is Banner minus (Workday SIS + Workday Other). Includes empty periods in the selected range; Notes starts blank. |
| Workday Data / Banner Data | Original selected worksheet contents with source row numbers and selection dispositions. Excluded rows are preserved. Source text is stored literally, including values beginning with `=`. |
| Worktags (when uploaded) | Cleaned CWID, term code/description, worktag type and six-digit number. Only the requested metadata is retained. |

## Workday coding and signed amounts (0.24.2)

[Issue #17](https://github.com/JoshuaKosakowsky/HigherEd_Automation/issues/17)
defines the Banner description mappings and the compact amount layout. The owner
confirmed signed **Debit minus Credit**, **Banner minus Workday** differences,
and **Review** for unmatched ledger accounts in the implementation chat.
Credits are stored internally as positive magnitudes, so adding Debit and Credit
would hide reversal signs. These output changes retain the existing separate
exact-cent debit/credit matching controls; a zero displayed Difference does not
prove that both sides agree or authorize Banner substitution.

CWID Recon appends **Ledger Acct** and **Spend Cat**, calculated from Banner rows
for the same student, fiscal year and period. Each cell lists every distinct
matching code or exception label, separated by semicolons; no first-match choice
or allocation of the student's total to a single code is inferred. A student
with only non-SIS Workday activity shows Review for both. Combined has neither
column. Comparisons ignore case and surrounding whitespace. Rules follow:

| Banner Description | Ledger Acct | Spend Cat |
| --- | --- | --- |
| Ends in RA | 1631e | 6152 |
| Ends in TA | 1631e | 6153 |
| Ends in GTF | 1631e | 6154 |
| Contains FELLOW T&F | 5893e | 7503 if it ends in T&F; otherwise Review |
| Contains Grad Fellowship Living Stipend | 5893e | 7502 |
| Other description ending in T&F | Review | 7503 |
| No matching rule | Review | Review |

Ledger and spend rules are independent: the RA/TA/GTF suffix rules take priority
for both; the living-stipend spend rule takes priority over the T&F spend suffix.
When Banner ID contains **TPS00080**, it overrides all description rules with
**No Ledger Applicable** and **No Spend Applicable**. Its Amount changes sign
before matching and aggregation, including document, CWID, period and Combined
views. Original Banner Data retains the supplied Amount and Description.

Synthetic acceptance examples:

- Description `Synthetic RA` maps to `1631e` / `6152`.
- Description `Synthetic FELLOW T&F` maps to `5893e` / `7503`.
- ID `TPS00080`, Description `10000001 Synthetic RA`, Amount +4,000 becomes
  a credit of 4,000 (signed amount −4,000); Amount −4,000 becomes a debit of
  4,000. Both classification fields show the exception labels above.
- Workday SIS −25, Other Workday −7, and Banner −20 produce document Difference
  +5, CWID Net Period Activity −13, and period Difference +12.
- Posting references `260001`, `2600001`, and `250001` retain their rows in
  Combined; rows with `12345`, `12345678`, or `26A001` are excluded from that
  sheet entirely. No current-year prefix is required. Raw source rows and other
  reconciliation sheets retain the full selected activity.
- A student with RA and TA Banner rows has Ledger Acct `1631e` and Spend Cat
  `6152; 6153`. A worktag export containing Project `654321`, Grant `012345`,
  and Grant `000001` supplies Project `654321`, Grant `000001; 012345`, and a
  blank Operating Account. Financial rows are not duplicated.

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
