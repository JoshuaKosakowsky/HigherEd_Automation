# Historical Trends

Historical Trends is available in the app's **Administrator** view under
Accounts Receivable. Its form uses the same **Banner data** and **Outputs**
blocks as 1305 recon, without Workday inputs. Choose one of two sources:

- **Upload annual TGIACCD files** (default): browse, drop, or paste one path per
  line. Select one `.xlsx` or `.csv` per fiscal year. Years come from filenames
  such as `TGIACCD_fy2026.xlsx`; no hidden SQL year filters narrow uploads.
- **Run SQL from PROD Insights**: select first and last fiscal years using the
  editable year controls. Type a year, use the up/down arrows, or scroll the
  mouse wheel. The default is the most recently completed fiscal year. Review
  the PROD confirmation and complete the usual Insights sign-in if prompted.

Uploads automatically load the saved shared Banner `detail_codes.json` reference.
SQL runs refresh that reference from PROD before extracting transactions.
Users select only their source and a new output workbook in an existing approved
folder; the reference file is not a form input. The form and navigation
are blocked while running; cancellation and progress are shared with 1305 recon.
Uploads do not use TEST/PROD or contact Insights. Existing source files and
reports are preserved.

FY2026 means **July 1, 2025 through June 30, 2026**, selected by **Feed Date**.
All detail codes, terms, and accounts in that window are included. No Banner
records are changed. The app uses the existing PROD Insights profile, including
its verified database ID and authentication settings; no new credentials or
connection configuration are needed.


## Shared reference setup

An administrator maintains `detail_codes.json` in the same synchronized folder
as `gui_access.json`:

```text
<OneDriveCommercial>/GRP-Bursar Office - General/Y-Brswork/Staff Folders/.highered_automation/detail_codes.json
```

Run **Refresh Banner Detail Codes** from the Administrator view under Accounts
Receivable to initialize or update this file. Review the PROD confirmation and
complete normal Insights sign-in. This queries all TBBDETC codes, including
inactive/historical codes, in checked pages; treats detail codes as opaque nonblank text (including punctuation and shorter
codes), validates uniqueness and C/P types,
nonempty categories and result completeness; and replaces the saved JSON only
after validation. Extra Excel-derived metadata is retained for codes still
present in Banner. Codes absent from Banner are removed from the new reference.
The refreshed metadata includes `priority` from `TBBDETC_PRIORITY`, `active`
from `TBBDETC_DETC_ACTIVE_IND`, and `title_iv` from `TBBDETC_TIV_IND`.
Priority is stored as text, retaining leading zeros. Y/N indicators become
JSON true/false, matching the Excel converter; blank values remain null.
Unexpected values stop the refresh and preserve the saved reference. These
fields are refreshed even if the saved file contains older Excel-derived values.
Inactive and non-Title-IV codes are still included; no transaction population
or financial classification rules change.

No Banner records are changed. The refresh does not require a prior Excel export.
Copying the existing `data/banner/detail_codes.json` there remains an optional
bootstrap method.

GUI SQL trends runs refresh this same shared reference automatically. If refresh
fails, the trends run stops and the previous reference remains intact; stale
classifications are not silently used for SQL runs. Uploads use the saved file
without database access. If it is missing, run the refresh action first and check
OneDrive synchronization. Unknown transaction codes still stop the report.
A successful refresh may remain even if later transaction extraction fails or
a trends run is cancelled.

The update uses an atomic file replacement, a local lock, and a check that the
reference has not changed during extraction. It leaves the saved file intact
on invalid, empty or truncated results, request failure, cancellation before
replacement, or detected conflicting edits. OneDrive synchronization is not a
distributed lock; run one refresh at a time across workstations. If a refresh
process exits unexpectedly, an administrator must verify that no refresh is
running before removing `.detail_codes.json.lock`. Malformed existing JSON must
be reviewed before refreshing so extra metadata is not silently lost.
The folder's hidden attribute is cosmetic, not an access control.

The command-line workflow keeps its existing repository-local reference default;
`--detail-codes-file` / `-DetailCodesFile` can point it to the shared reference.
CLI SQL runs refresh their selected reference file; file-only runs read it.

## Extraction and outputs

The query in `query/AR/trends/transactions_extract.sql` reads TBRACCD and joins
current SPRIDEN identity records. It retrieves disjoint calendar months in
PIDM/transaction-number order, normally 1,000 rows per page. A server-side
remaining-row count guards each page. If the API returns fewer rows than the
SQL LIMIT requested, the same cursor is retried with a smaller page size before
any rows are accepted. Duplicate or unordered transaction keys, missing guards,
and inconsistent counts stop the run. Remaining counts must also agree across
pages; changed populations require a retry. Connection or query failures also stop
rather than publish an incomplete report.

A matching `<output stem>_sources` folder contains one completed
`TGIACCD_fyYYYY.csv` per fiscal year. These CSVs are streamed into the existing
analysis, preserving its signs, category mappings, collection/write-off rules,
sheet names, and calculations. Whole years are not held in a pandas DataFrame.
The complete year files remain available after a later failure or cancellation;
unfinished year files are removed. A retry requires a new output filename/source
folder; automatic resume is not implemented. The final analysis workbook is
saved only after all requested years have been extracted and analyzed. Existing
workbooks and source folders are never overwritten by SQL runs.

**Balance values are the current replicated balances at extraction time, not
historical fiscal-year-end snapshots.** Insights replication freshness also
applies. Selecting a current or future fiscal year can produce an incomplete
year. The shared detail-code reference controls GUI classifications; missing
codes stop the report unless explicitly permitted in the CLI. Source CSVs contain
student account data and must stay in approved storage; Git ignores CSV/XLSX data.

Paging bounds returned data but cannot eliminate server-side query timeouts.
Monthly slices and keyset pagination reduce the request scope; a live PROD run
is needed to validate performance and coverage against the former TGIACCD export.

## Command line

Historical workbook ingestion remains the default, preserving the existing
`start-trends` / `launcher/run_trends.ps1` behavior:

```powershell
.\launcher\run_trends.ps1
```

For direct SQL, provide an explicit year range and PROD confirmation:

```powershell
.\launcher\run_trends.ps1 -Source sql -FirstFiscalYear 2024 -LastFiscalYear 2026 -ConfirmProd -OutputFile .\data\statistics\trends_2024_2026.xlsx
```

The equivalent Python command, from the repository root:

```text
python -m workflows.trends.run_trends --source sql --first-fiscal-year 2024 --last-fiscal-year 2026 --confirm-prod --output-file data/statistics/trends_2024_2026.xlsx
```

Optional SQL arguments: `--extract-dir` / `-ExtractDir` chooses a new source
folder; `--page-size` / `-PageSize` selects 1–10,000 rows (default 1,000).
The standard administrator policy grants all registered workflows. If your
shared administrator policy lists explicit workflow IDs, grant `trends` through
Access Management. Non-administrator views cannot expose this workflow.

The GUI independently checks administrator access and requires PROD mode.
CLI usage remains subject to database permissions, as with the existing refund
launcher. It does not bypass Insights authorization.

To reanalyze completed annual CSVs without contacting Insights:

```text
python -m workflows.trends.run_trends --input-dir data/statistics/trends_2024_2026_sources --file-pattern "TGIACCD_fy*.csv" --output-file data/statistics/trends_reanalysis.xlsx
```
