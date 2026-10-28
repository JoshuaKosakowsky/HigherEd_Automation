# Mines Bursar Automation desktop app

This PySide6 / Qt Widgets desktop application is the staff-facing front end for supported
HigherEd Automation workflows. It calls existing Python workflow logic through
small adapters; business rules remain in `data_processing` and workflow entry
points remain independently runnable.

The interface uses the exact digital colors published in the [Mines
Communications and Marketing palette](https://brand.mines.edu/fonts/). Dark
Blue, Blaster Blue, Pale Blue, white, and the approved neutrals carry the main
layout; accent colors remain limited.

## Current architecture

App 0.24.0 adds **View → Zoom in, Zoom out, Reset zoom** (75–150%).
Use **Ctrl++** (or **Ctrl+=**) to zoom in, **Ctrl+-** to zoom out, and
**Ctrl+0** to reset. Zoom resizes fonts and theme spacing on existing pages
and dialogs without discarding entered values. Use **View → Show navigation**
to hide or restore the sidebar when screen space is limited. Navigation scrolls
vertically when needed. View choices last for the current app session.

The calendar opens with filters and reminders collapsed to reserve space for the
chart. **Filters** opens a compact panel of labeled fields and shows the number
of active filters even when collapsed. **Clear filters** resets category,
semester, role/person and search together, preserving the selected year/range.
**Calendar actions** provides adding/editing, groups, reload and the calendar key;
date and schedule actions require a selected item. Remove item prompts for an
individual-row selection when needed, then asks for scope and confirmation.
Hover over Calendar actions for save status.
**Reminders** shows the existing reminder list with its count. The timeline fills the available width
automatically, with no separate zoom control.
These display changes do not modify shared calendar data or workflow rules.

- `workflow_registry.py` holds typed, staff-facing workflow metadata.
- `models.py` defines workflow inputs, execution context, and results.
- `pages/` renders searchable workflow cards, registry-driven forms, and staff administration.
- `theme.py` provides the Mines palette, a navy navigation sidebar, and light workspace.
- Staff profiles use a single editable form with a view dropdown; permissions use checkboxes.
- `services/operations_calendar.py` owns recurrence, date exceptions, staffing
  roles and optional people within them, visual reminders, and admin-checked shared persistence.
- `pages/operations_calendar.py` renders the Gantt timeline and calendar editors.
  Admins open **Bursar Office Calendar** from the sidebar and see a reminder summary
  on the home page. **Affects** lists the existing Staff access views with their
  users underneath; select a whole role or specific people without creating new
  permission views. See [Bursar Office Calendar instructions](operations_calendar.md).
- Calendar **Groups…** organizes existing schedules under expandable headings.
  Compact group timelines retain individual deadline and coverage marks while
  collapsed. Optional semester labels use Mines colors (Fall Colorado Red,
  Spring Blaster Blue, Summer Muted Blue, General Silver), with a semester filter.
  Existing calendar files load without re-entry; update all calendar editors to
  0.18.0 before saving the new format. Dates and reminders remain independent.
  Group membership is independent of categories and does not link dates;
  existing linked coverage retains its deadline-relative behavior.
- file inputs accept direct paths, Browse selection, and native Explorer/Finder
  drops, using Qt's native local-file URL support. No separate drop package is required.
- `services/parameters.py` preserves input parsing independently of the toolkit.
- Each run has a review dialog. TEST is preferred where modes exist; production
  displays the workflow warning and requires an explicit Run in production action.
- Refund Review, 1305 Graduate Contract Recon and Historical Trends generate their default output
  timestamps when the form opens and refresh them before each **Review & run**,
  including reruns on the same form. Manually entered or browsed output paths
  are preserved. Filenames keep second precision and existing overwrite protections.
- Generated Banner terms, previous-month ranges and filenames, completed fiscal
  years, and prior tax years are calculated when a workflow form opens and
  refreshed before each **Review & run**. Returning to a form also refreshes
  untouched defaults. Explicit edits and browsed paths remain selected, even
  after changing a value back to its original default. No app restart is needed
  after a month, year, fiscal-year or configured Banner term boundary.
  Textbook Brokers keeps the prepared term for its archive step. Insights
  activity report dates similarly refresh before export unless explicitly edited.
- `services/execution.py` runs one task at a time on a worker thread and converts
  exceptions into staff-safe messages while preserving tracebacks in the log.
- `shared/progress.py` supplies toolkit-independent progress updates;
  `progress.py` renders them in one shared Qt widget for all workflows.
- workflow-specific service adapters translate form values into existing
  pipeline configuration. They do not reimplement processing rules.
- `launcher/run_gui.ps1` starts the app with the repository virtual environment.
- Setup installs pinned `PySide6-Essentials` and verifies a real Qt window.
  The GUI launcher verifies native plugin initialization using
  `app.gui.runtime_check` before starting windowed Python. Diagnostics go to
  `%LOCALAPPDATA%\HigherEdAutomation\gui-runtime-check.log`.
  Run `setup.ps1 -RepairGui` to re-download the pinned GUI runtime when files
  are missing or damaged. See the root README's Qt troubleshooting instructions.
- `shared/user_settings.py` reads the same per-user JSON written by `setup.ps1`.
  The home page greets the employee by first name and uses `User` when settings
  are unavailable or invalid.

The integrated workflows are:

- **Set Up Report Watcher** (`setup_report_watcher`), calling the existing
  `setup/setup_report_filing_watcher.ps1` installer on Windows. It installs or
  updates the scheduled task for the signed-in employee, requests an immediate
  start, and enables startup at sign-in. The employee must have completed
  `setup.ps1` to save their name and initials. This action has no file inputs.
  Admins can assign it through **Staff access → Manage views & permissions**;
  it is not automatically granted to Cashier or Analyst. The cashier runs it
  under their own Windows login. Mac review can display the card but cannot
  install the task. The watcher handles the configured RDC filing and JPMLB
  CSV-to-XLSX workflows.
- **Student Testing Population**, using its existing typed Python configuration
  and pipeline. It does not have a run-level TEST or PROD switch: the workflow
  creates balanced TEST/PROD assignments inside the result workbook.
- **Refund Review** is administrator-only. Choose **Drop, browse, or enter
  source file paths** for matching transaction and account-context XLSX/CSV
  exports, or **Run SQL from PROD Insights** to extract both inputs directly
  using the configured PROD connection and existing 20-batch refund pipeline.
  Oversized results automatically subdivide by account and, for a single
  account's transaction history, by transaction number. Each part and the
  recombined batch must pass completeness checks before being saved. Subdivision
  narrows account selection before full-balance aggregation and joins; transaction
  slices leave full-account eligibility unchanged. The GUI log records per-query,
  extraction, calculation, and workbook timings without account identifiers.
  **Cancel run** stops at the next safe checkpoint. Closing the window during
  Refund Review offers to cancel and close once it stops. An active Insights
  request must return or time out first (the client uses a 120-second request
  timeout); cancellation does not terminate a query already running on the
  server. Cancelled runs publish no workbook. Output is staged and moved into
  place only after completion.
  SQL mode requires no input files and shows a production warning in the review
  dialog. Temporary extracts are removed after the run. Both options calculate
  and format the review in Python; neither approves or issues refunds, and
  existing output workbooks are never overwritten. Resuming batches and
  single-account API validation remain available through the PowerShell launcher.
- **Textbook Brokers**, using the existing PowerShell and WinSCP integration to
  download pending `finaid_*.csv` / `ia_*.csv` sources from the configured SFTP
  server and transform them into TSPLOAD. The GUI accepts the Banner term and
  offers two steps: **Prepare TSPLOAD** and **Archive after TSPLOAD**. Successful
  preparation prompts you to complete TSPLOAD in Banner and selects step 2.
  Run step 2 only after verifying that the transactions applied successfully;
  the GUI requires explicit confirmation (default No) before invoking the existing
  guarded local/remote archive process. To resume after closing the app, select
  step 2 with the same term. The PowerShell `archive-textbook-brokers` shortcut
  remains available and still prompts for confirmation.
- **Textbook Recon** has one Home Page entry. Select the monthly Brokers workbook
  with `IA Charge Report` and `FA Charge Report` tabs, then choose the Banner
  data source. Staff upload FRST and/or BOOK exports; administrators can also
  choose **Run SQL from PROD Insights**. If uploaded extracts contain Feed Date,
  every row must belong to the selected month. Leave one Banner file blank when
  that code has no transactions; at least one extract is required. The SQL
  option reads FRST and BOOK transactions from PROD and stops if the API
  truncates the result.

The recon creates the complete workbook, including four refreshable Excel PivotTables, directly in Python. No template file is needed.
They group signed amounts by student ID, compare to the cent, and align the two
sides with blank cells where an ID occurs on only one side. The recon tabs are
sorted by name. Four native PivotTables are created with empty caches and
refresh enabled when Excel opens the workbook. Open the result in
Excel to populate and refresh the pivot tabs; the recon rows themselves are
populated before that refresh. The output path must be new. Student data stays in the selected
output workbook and is not added to the repository.

## Workflow visibility

### Insights connections (administrators)

Active app administrators have a **Connections** page. TEST is selected by
default; choose TEST or PROD explicitly and click
**Connect and sign in**. The dedicated automation browser opens MyMines. Once
the MyMines dashboard appears, it opens the selected environment's configured
Experience address, selects **Reporting**, and clicks **LAUNCH REPORTS** on the
Insights card. If a
page cannot be recognized, finish the sign-in or navigation in that browser.
The browser closes after handoff
or timeout, retains persistent SSO state locally when the identity provider
allows it, and the GUI then shows
the actual result. The check runs only `connection_check.sql` (`SELECT 1`), not
the student sample query, and does not export files.

The Connections page can optionally save a MyMines username and password in
Windows Credential Manager or macOS Keychain through the existing native
`keyring` backend. **Set or update saved login** replaces that local entry;
**Remove saved login** deletes it. Autofill runs only on `https://my.mines.edu`
and only on recognized username and password steps. The person completes Okta
Verify and any unfamiliar prompts. The password is never added to department
configuration, browser logs, the repository, or the Insights API session cache.
If Okta resumes directly at a remembered password step, autofill proceeds only
when the account shown there exactly matches the saved username. Otherwise,
enter the password manually. This saved login is separate from
the cached Insights API session and from Chrome's password manager.

Staff do not create `.env` files or enter environment URLs/database IDs. The
owner maintains non-secret department settings once in
`config/institutions/mines/insights.json`; Git deployment delivers these settings
to all installations. GUI connections deliberately ignore `.env` and ambient
`INSIGHTS_ENV` so a staff selection cannot silently route to another environment.
The command-line proof of concept also uses the bundled department settings by
default; `.env` is optional for an API key or a different deployment.

TEST and PROD are supplied with separately verified hostnames. PROD uses
`https://minessis-insights.50115.elluciancloud.com` and database ID `2`
(`data-warehouse`), identified through authenticated, non-administrative
database metadata. TEST also uses ID `2`, but at its different TEST hostname;
the IDs were not assumed to match. MyMines is the starting portal for both.

The owner maintains these four non-secret fields centrally and distributes any
changes with the app. Setting an environment to `null` disables its connection
actions. Never infer a new host/database from another environment or put
credentials in this file. Staff do not repeat department provisioning when
their daily session expires. The shared client's metadata-only mode can list
accessible databases without a database ID, but refuses SQL until one is set.

Each employee signs in using their own account; sessions remain in their native
OS vault and are separated by environment. A valid session is reused. Staff
may need to sign in each day or sooner if the server invalidates the session;
they do not repeat configuration. **Check connection** never opens a browser.
**Sign in again** revokes/replaces the selected cached session. **Sign out**
revokes the selected API session, not the MyMines browser session. Status text
is a timestamped last check, not a guarantee that a session is still valid.

TEST and PROD use the same persistent automation-browser profile, as do the
repository's Banner and MyMines browser helpers when they use the same channel.
On Windows Chrome it is stored under
`%LOCALAPPDATA%\HigherEdAutomation\Playwright\Shared_Chrome`, outside the
repository and normal OneDrive project folder. It may contain SSO cookies and
local storage and must never be copied, synchronized, committed, or shared.
Only one automation browser window may use it at a time. Chrome is the default;
Edge remains an explicit fallback with a separate profile. Signing out of the API connection does not erase browser
cookies; use the identity provider's own sign-out for a full SSO logout.

Access is rechecked before each connection action. TEST and PROD are selected
explicitly on the page and do not show a separate confirmation. Connection
operations reuse the background executor;
authentication errors are sanitized before the general GUI logger sees them.
The administrator Connections page also has a query picker and **Run selected
query and save Excel**. Select TEST or PROD, choose a report, and choose the
workbook destination. The picker uses
the explicit list in `shared/insights/query_catalog.py`; it never accepts an
arbitrary SQL path. Available reports include current and previous calendar
month transaction and payment activity, the existing historical loan activity
draft, contact lookup, Parent PLUS sample, sponsored student summary,
delinquent student accounts, refund
review SQL, the two manual refund extracts, the Banner term sample, the
institutional-loan recent graduate/leaver review, and two SHIP Fall exceptions. The loan
and SHIP reports prompt for a six-digit Banner term. The SHIP reports require a
Fall term ending in `80`. The loan report accepts Spring `10`, Summer `55`,
or Fall `80`; it uses historical loan activity and a rolling 365-day exit
window, and never infers a stop-out from missing Summer enrollment. Its
source-count check rejects incomplete API results before saving. See
[loan selection rules](../../query/AR/loans/README.md). The term is validated and inserted as a quoted SQL
literal; no raw free-form SQL is accepted from the interface.

In 0.11.0, **Activity — Banner Activity by Date & Detail Code** uses the same
`query/AR/activity/tgiaccd_transactions.sql` template as the staff Insights
question. Select inclusive start/end feed dates with the calendars and enter
comma-separated detail codes. Dates default to the first of the current month
through today. Detail codes start blank with no default selections; enter at
least one four-letter/digit code. Actual date boundaries support periods, quarters, years, and multiple
years without assuming fiscal-calendar rules. Invalid/reversed dates or empty
code selections are rejected before authentication or output selection.

The report uses the existing JWT-to-session login and secure environment-specific
session cache. Application administrators still need native SQL permission in
Insights; staff without that permission use the published saved question.
`shared/insights/banner_activity.py` separates parameter validation and extraction
from GUI/authentication so later reports and the 1305 workflow can reuse it.
It checks source row counts, splits capped results into non-overlapping date
windows, and fails without saving if a single day remains capped. The internal
count is removed from the workbook. Output retains the 12 SQL columns, signed
amounts, and real Excel feed dates, with no Excel Tables or file overwrite.
Direct database transport remains future work. The 1305 reconciliation is
available as a separate workflow in 0.12.0, described below.
See [`query/AR/activity/README.md`](../../query/AR/activity/README.md) for API
limits, permissions, and first-run validation.

In **0.20.0**, **Connections → Activity — W&F - Mines Balance Recon
transactions** adds an administrator-only Banner source export for the future
reconciliation (working name). Detail codes default to **WOFF, BDRC** and can
be replaced. No date inputs or time boundary apply; NULL feed dates, signed
reversals and zero amounts remain included. It preserves the TGIACCD extract's
twelve source columns and rejects API-truncated results before saving. It does
not yet match agency/Workday data or combine the collections-hold report.
See [W&F extract configuration and examples](../../query/AR/activity/README.md#wf_mines_balance_transactionssql-wf---mines-balance-recon-source).

In **0.23.4**, **Accounts Receivable → W&F - Banner Recon** accepts one combined
**W&F - Banner Recon** Insights export (`collections_tracking.sql`), or one direct
PROD query for administrators. Staff use upload mode; the existing
`wf_mines_balance_recon` permission remains unchanged. Legacy separate holds and
transaction exports must be replaced with the combined report.

The W&F section accepts batch CSV/XLS/XLSX/XLSM files. From patch 0.23.5,
commission is maintained by administrators in
`config/institutions/mines/wf_reconciliation.json` (0.25 = 25%), outside the
workflow form. Tab order is Reconciliation, Students in Collections, W&F Collections,
then W&F Returned. Students in Collections uses the updated 11-column Banner
layout with CO From Date / CO To Date and no Latest Feed Date. Fees principal divides Orig. Balance by 1 + fraction;
other types retain Orig. Balance. Unisa filenames containing 12007, 12009, 12559
or 12561 are omitted. Reconciliation includes CWIDs from Banner or W&F Collections,
sums multiple W&F accounts and shows Difference and a 1/0 Returned flag. Unknown
or absent amounts remain blank. Patch 0.23.6 removes explicit Total Accounts
footers from both agency reports; reconciliation zeros display as $0.00, while
blank Differences have a yellow fill and explanatory cell note. Source rows, dates, footer checks, formula-cache
handling, cancellation and exclusive output creation retain their safeguards.
See the [W&F technical guide](../../data_processing/wf_mines_balance_recon/README.md)
for current business rules, synthetic examples and operational validation.

Connections' legacy all-date transaction export remains available independently
and retains its checked cap batching. The new grouped Banner report requires a
complete count-checked result; use a full combined manual export if capped.
Existing workstations retain the normal requirements and setup process.

**1305 Graduate Contract Recon** reads Workday and Banner files and produces
document, CWID, period and combined activity views, plus the original source tabs.
The **Grad Contract Sponsor** view receives this workflow with uploads only;
administrators can also select **Run SQL from PROD Insights** for Banner.
Workday uploads are grouped together in a pale-blue section before Banner data.
The form is titled **Inputs**, with the save location in a separate **Outputs**
section. From patch 0.24.2, CWID Recon includes Banner-derived **Ledger Acct** and
**Spend Cat**, listing all distinct values per student and fiscal period.
Combined excludes entire rows whose Memo / Feed Document is not exactly six or
seven digits, without a current-year prefix requirement; other reconciliation
views retain their full activity.
TPS00080 amounts reverse sign before matching; original source tabs stay intact.
Document/CWID/period views use signed Debit minus Credit amounts, with differences
calculated as Banner minus Workday. Period Totals compares Banner against all
Workday (SIS plus Other) and keeps a blank **Notes** column for staff comments.
See the [1305 technical guide](../../data_processing/graduate_contract_recon/README.md)
for mappings, exceptions and synthetic acceptance examples.
Workday always requires an uploaded export.
the optional **Grad Contract Worktag** upload reads Find Journal Lines to add a
cleaned Worktags tab and separate **Project**, **Grant**, and **Operating Account**
columns on CWID Recon. Each type keeps all distinct numbers per CWID, including
leading zeros; missing types stay blank. Names and unrelated export columns are discarded.
Inclusive dates and detail codes appear only for **Run SQL from PROD Insights**.
SQL detail codes default to **TPDT, TPLE, Z0LE** and remain editable; at least one
code is required. File upload mode uses all valid Banner codes and the dates
contained in the supplied exports; hidden SQL settings do not filter uploads.
Upload both financial exports for the same intended scope.
The combined tab shows Workday rows above matching Banner
detail. Period Totals counts matched activity once; Combined displays both
sources' amounts for review. Worksheets
are plain ranges without Excel Tables, and existing files are not overwritten.
For existing shared policies, grant `graduate_contract_recon` to the employee's
existing view through Access Management; updating code does not replace deployed
access rules. See
[`data_processing/graduate_contract_recon/README.md`](../../data_processing/graduate_contract_recon/README.md)
for source layouts, matching rules, output interpretation, and deployment.

Choose **Term corrections — Payments in a term with no charges** and enter the
payment's posted term (e.g. `202655`). This administrator report lists available
CSH cash-payment credits only where no charge ever posted in that term. It uses
the same SQL staff can run as a saved Insights question, rechecks administrator
access, and rejects incomplete API results. It does not move payments or decide
the destination term. See
[`query/AR/term_corrections/README.md`](../../query/AR/term_corrections/README.md)
for publishing, classification, exclusions, and reconciliation before use.

In 0.16.0, choose **Holds — RH delinquency review** for all students with RH in
`TBBACCT_DELI_CODE`, including former students and accounts without a balance.
It uses the same administrator connection/export setup and completeness check
as the wrong-term payment report. No term or date input is required. Account
activity is included for reference, but it does not establish when RH was set,
so no age cutoff is applied. The workbook supports manual Banner review;
it does not remove holds. Publishing and source details are in
[`query/AR/holds/README.md`](../../query/AR/holds/README.md).

Choose **Contact — Student contact information** for students with account-record
activity (`TBBACCT_ACTIVITY_DATE`) within eight years of the current month, through
today. This limits accounts before selecting contacts; it is a recency
filter, not formal active status. Select **PROD** for production data. Both
contacts and their types must be populated; email age is not restricted. Uses
active Mines (`UNIV`) email and a usable `PR` phone, falling back to `CELL`.
Email preference and phone primary flags are ignored. Export columns now use
`Mines Email` and `Phone Number` instead of the former preferred-contact labels.
This replaces the OS_Checks lookup and does not identify outstanding checks.
The same standalone SQL can be saved in Insights for staff; see
[`query/AR/contact_information/README.md`](../../query/AR/contact_information/README.md)
for selection rules, publishing, and validation. The report has no technical
row-count column.

Administrators can also select **Contact — Refund check contacts for AP matching**
in Connections. This separate read-only report selects RFND/RFDP accounts with
feed dates from 200 days ago through today, provides student or borrower contacts,
and preserves incomplete contacts with review flags. Match its Student CWID or
Borrower CWID to AP's outstanding-check report; Banner activity does not determine
whether a check remains uncashed. TEST/PROD selection, administrator checks,
complete-result checks and new-file Excel export use the existing report service.
See [the report's rules and validation](../../query/AR/contact_information/refund_check_contacts_README.md).

In **0.25.0**, administrators can select **Holds — Collections demographic and
academic profile**. It uses the same SQL that can be pasted into Insights and
includes all historical CO hold date pairs, an active flag, age, current
race/ethnicity/sex/gender codes, and academic context for the term containing
each hold's start date. Majors/level, registered credits, prior GPA/standing and
reconstructed class retain their source terms and review flags. First-generation
status stays Unknown until a local mapping is verified. Later term outcomes are
labeled separately. No parameters are needed; the existing TEST/PROD,
administrator, completeness and new-file export checks apply. See
[profile fields and first-generation verification](../../query/AR/holds/collections_student_profile_README.md).

Choose **Holds — Delinquent student accounts** for the delinquency outreach
review workbook. It needs no term input and exports all-term net balance,
past-due amount, preferred email/phone, and `Hold`. Any CO record excludes the
account. Active PP accounts are included with `Hold = PP` for manual Transact
review before deciding whether to send outreach; Insights cannot identify
Transact payment-arrangement errors. See
[`query/AR/holds/README.md`](../../query/AR/holds/README.md) for the balance and
hold-date definitions and first-run reconciliation requirements.

In 0.19.0, administrators can choose **Holds — W&F - Banner Recon** for
accounts with CO holds ending strictly after today. It exports one row per
account using the latest qualifying hold from date, including zero/credit
balances, all-term total balance, latest account feed date and hold dates.
No term or date inputs are needed. Missing financial data stays blank for
review; feed date does not establish referral to the agency. The export checks
the full source row count before saving. See
[collections rules and acceptance examples](../../query/AR/holds/README.md#collections-tracking).

The previous-month reports preserve the existing activity columns and payment
detail-code list while selecting feed dates from the first of the previous
month through the start of this month. The current-month queries keep their
existing SQL, including the absence of an upper date bound. The historical
loan activity report remains a draft with a two-month historical window and
unvalidated detail-code list/grouping; its name does not describe its actual
window. The contact lookup does not identify outstanding checks despite its
filename. The two manual refund extracts are a matched pair; exporting one
alone does not run the refund review workflow.

Validation queries, SQL templates for the refund pipeline, and the single-CWID
refund diagnostic are omitted. Aging dashboard cards require two inputs plus
Metabase field-filter mappings and are not available through this picker. The
picker runs one read query at a time. It writes the complete result
to the chosen location after the query completes, without replacing an
existing file. Reports may contain student and financial records; use an
approved destination. Large results may exceed the API timeout or Excel's row
limit. Feed Date columns are written as real Excel dates and times in UTC,
matching the API's `Z` timestamps, so Excel can sort and filter them as dates.
This is a proof of concept and does not change operational workflows.

### Staff workflow policy

The GUI reads the signed-in Windows account name and matches it
case-insensitively to the shared policy under the Mines OneDrive root at
`GRP-Bursar Office - General\Y-Brswork\Staff Folders\.highered_automation\gui_access.json`.
Each user profile contains a display name, informational job title,
active/revoked status, and an explicitly assigned view. Job titles never grant
access. The central `views` map is the only place that lists which workflow IDs
each view may display.

Administrator uses the `"*"` workflow allow-list and sees every registered
workflow. The current analyst and cashier allow-lists are deliberately empty;
those staff members receive no workflow cards until the application owner adds
specific workflow IDs. An unassigned login also sees no cards and receives a
contact-the-administrator message.

Active administrators see **Staff access** in the sidebar. They can
add or edit profiles, revoke or restore access, and choose the workflows shown
to each view. **Manage views & permissions** lets any active administrator
create, rename, or remove non-administrator views without editing JSON.
New views start with no workflows. Renaming preserves workflow permissions
and updates assigned profiles, including revoked users; job titles remain
independent and are edited through **Edit profile**. Before removing a view,
reassign all profiles using it (including revoked users). Administrator cannot
be renamed or removed. Save applies all pending changes; Cancel discards them.
Existing owner-password requirements still apply if a rename changes the
owner's assigned view. Updates are validated, written atomically, and
back up the previous policy beside the live file. A file-change check detects locally visible changes since the policy was loaded.
Use Reload after a conflict. OneDrive synchronization is asynchronous, so this
is not a distributed lock across offline or simultaneously editing computers.

The designated owner profile is protected separately. On first use, the owner
must choose a password of at least 12 characters. Only a salted password
verifier is stored; the password cannot be recovered. Subsequent owner-profile
or owner-password changes require that password. Other active administrators
can maintain all non-owner profiles without it.

The application creates `.highered_automation` and applies the Windows Hidden
attribute. That keeps it out of the normal File Explorer view, but it is only a
convenience and not an authorization boundary. The Bursar-only parent location
and OneDrive access remain the actual outer access scope.

The ignored `config/gui_access.json` is retained only as a private bootstrap
and Mac review policy. On the first Windows launch where the shared policy does
not exist, a configured administrator's local policy is upgraded and copied to
the shared location. For a legacy policy without an owner, the intended protected owner should
perform this first launch. Existing schema-3 owner and password data are preserved. `config/gui_access.example.json` documents the public-safe schema. Do
not commit the live staff mapping or shared policy to the repository.

This is staff-interface scoping, not a security boundary: employees with direct
repository and PowerShell access can still run launchers permitted by their
Windows and system credentials. Enforce true authorization at the source-system,
filesystem, and credential layers.

## Launch and test

On a configured Windows workstation, use the desktop shortcut created by
`setup.ps1`. For troubleshooting with terminal output, run:

```powershell
.\launcher\run_gui.ps1 -Console
```

From an activated development environment, the equivalent command is:

```powershell
python -m app.gui.main
```

For a Mac review, use an explicitly configured Windows login. This selects the
same view that account will receive on Windows; the welcome name still comes
from the local setup profile and defaults to `User` when it is unavailable:

```bash
python3 -m app.gui.main --review-as EXAMPLE-ADMIN-LOGIN
```

That command uses the ignored local `config/gui_access.json`. A different local
test policy can be selected explicitly on macOS/Linux:

```bash
python3 -m app.gui.main --review-as EXAMPLE-ADMIN-LOGIN --access-config /path/to/gui_access.json
```

Install the interface dependency in the Python environment used for review:

```bash
python3 -m pip install PySide6-Essentials==6.10.2
```

For a fresh full development environment, use Python 3.11 or later and install
`requirements.txt`. PySide6 6.10.2 requires macOS 13 or later; Windows deployment
should be checked on the institution's supported Windows build.

The `--review-as` identity and `--access-config` overrides are rejected on
Windows staff installations.
After installing this update on Windows, run `.\setup.ps1` once, then use the
existing shortcut or `.\launcher\run_gui.ps1 -Console`. No policy migration is
needed for an existing shared schema-3 policy.

The interface refreshes access when opening pages and before starting a run.
Every registered workflow uses the same progress display: current stage,
completed/total counts when known, percentage **of that stage**, and elapsed
time. Stages without a known total use an activity bar rather than an estimated
percentage or ETA. Progress remains visible on completion, cancellation, or
failure. The native Qt bar is keyboard focusable and exposes an accessible name
and description; visible stage/count text and elapsed time provide the same
information without relying on animation or color.

Refund Review reports extraction batches/partitions, transaction normalization,
completed account calculations, worksheet writing/formatting, saving, and
publication. Other Python workflows report their real processing stages.
Textbook Brokers and Report Watcher setup stream explicit launcher progress
messages while PowerShell runs; ordinary logs are not interpreted as progress.

While a workflow runs, navigation is blocked; Refund Review supports the safe
cancellation described above, while other workflows still block window closing. Completion
provides Open result and Open output folder actions; failures retain log access.

Run the automated suite with:

```powershell
.\tests\run_tests.ps1
```

For headless Qt interaction tests on macOS/Linux:

```bash
QT_QPA_PLATFORM=offscreen python3 -m unittest discover -s tests/python -q
```

Qt licensing notices and source information are in
[THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md), also referenced by About this app.

The GUI writes technical details to `logs/gui/gui_YYYYMMDD.log`. Staff-facing
dialogs intentionally omit tracebacks and secrets.

## Reporting workflow progress

Every runner receives a fresh, thread-safe `context.progress` reporter. Call it
before a blocking stage and after units of real work complete:

```python
context.progress.report("Connecting to source system")  # Unknown total: activity bar.
context.progress.report("Processing files", completed=0, total=len(files))
for completed, file in enumerate(files, 1):
    process_file(file)
    context.progress.report("Processing files", completed=completed, total=len(files))
context.progress.report("Saving workbook")
```

Pass `context.progress` into the existing processing API as the optional
`progress_reporter` argument. Those APIs import only `shared.progress`, never
Qt. Existing command-line callers can omit it. Counts must be integers with
`0 <= completed <= total`; provide both or neither. Counts describe the current
stage and can restart at zero in a new stage. Zero of zero represents a completed
empty stage. Only the final successful workflow result marks the entire run
complete. Workflows without detailed reporting still get the shared starting
indicator, elapsed time, and final state automatically.

The executor keeps only the latest update, and the GUI reads it on its existing
100 ms timer. Worker threads must not update widgets. Stage text should describe
work, never include student/account identifiers, sensitive records, credentials,
or SQL. It is displayed as plain text.

Windows adapters share `services/process.py`. Launchers emit a dedicated JSON
line, for example `HIGHERED_PROGRESS={"stage":"Downloading files"}`, optionally
with integer `completed` and `total` fields. Both output streams are drained
while the launcher runs. Invalid markers are ignored; existing output markers,
diagnostics, exit codes, and timeouts are preserved. Use these explicit markers
rather than parsing ordinary log messages as progress.

## App updates

**App updates** is available to all users, including users without assigned
workflows. **Check for updates** fetches the current branch's configured upstream
without changing installed files. It shows the remote name, branch and number of
new commits. **Install update** applies exactly the checked commit using a
fast-forward; it does not merge divergent history, reset files, stash changes,
or push anything. Git operations run in a background thread with bounded command
timeouts. Navigation and window closing are blocked until the operation ends.

After installation, workflows remain disabled until the app closes. Reopen it
with the normal shortcut so Python modules and launchers use the same revision.
Changes to `requirements.txt`, `setup.ps1`, or files under `setup`, `powershell`,
and `launcher` are flagged as requiring an administrator to rerun setup before
reopening. Dependency installation, automatic relaunch, and initial clone/auth
provisioning are outside this first update feature.

Administrators must provision a separate clone per workstation, install Git on
PATH, and configure its branch to track the intended remote branch. The current
development remote is GitHub `origin`; the updater uses each installation's Git
configuration rather than a hard-coded account or host. Changing that upstream
to Mines GitLab later needs no updater code change. It does not implement the
future work-PC publishing bridge. Grant staff the repository access needed to
fetch, using approved workstation authentication; never distribute your personal
SSH key. HTTPS credentials can use an already configured credential manager;
SSH must work without prompts. Authentication prompts are disabled inside the
updater; failures direct staff to IT and raw Git output is neither shown nor
logged because it can include credentials or private paths.

Copied folders without Git metadata and downloaded ZIPs cannot use this updater.
Existing setup does not install Git or create a clone. Avoid a shared or
concurrently OneDrive-synchronized working directory: in-app busy protection
covers this app process, not other app instances, scheduled workflows or other
machines. Close other automation tools before installation.

Updates refuse tracked modifications, untracked non-ignored files, detached
HEADs, missing upstreams, local commits/divergence, and unfinished Git operations.
The updater rechecks the branch, installed commit, clean state and fetched target
before installation. Ignored settings/data remain in place, and a collision
with a newly tracked file is refused. Git hooks are disabled for these operations.
Failures during installation require closing/reopening and administrator review;
the updater never attempts a destructive rollback. Failed checks can be retried.

## Deployment boundary and next integrations

The next useful migration steps are:

1. decide whether Refund Review batch-resume controls belong
   in the GUI after the manual workflow has been operationally validated;
2. explicitly approve workflows for the AR/Analyst and Cashier views;
3. add a small structured recent-activity file now that more than one workflow is
   available.

Adding a workflow should usually require a `WorkflowDefinition` and a thin
adapter that calls its reusable Python API. Do not put business rules in page or
button callbacks.

## Historical Trends (administrator)

Historical Trends is registered in Accounts Receivable for administrators. It
uses the same Banner data and Outputs blocks, colors, source switching, and busy
blocking as 1305 recon, without Workday inputs. Upload one annual TGIACCD workbook
or CSV per fiscal year, or select Run SQL from PROD Insights. Upload mode derives
years from filenames and does not apply hidden SQL year filters. SQL mode shows
editable year controls with arrows and mouse-wheel scrolling and requires PROD
confirmation. Both sources automatically use `detail_codes.json` beside the
shared `gui_access.json`; users do not supply a reference file. SQL trends runs
refresh it from TBBDETC automatically; uploads use the saved copy. Administrators
can run **Refresh Banner Detail Codes** independently to initialize/update the
shared reference without an Excel export. Checked pages, classification
validation, atomic replacement and conflict checks preserve the previous file
when refresh fails. A missing/syncing file blocks upload runs with setup
instructions. Both paths use a new workbook in an existing approved output
folder, cancellation, and progress. Checked SQL pages
are saved as separate annual CSVs beside the analysis. SQL activity is selected
by July–June Feed Dates; balances reflect the current replicated state.
See [workflow instructions](../../workflows/trends/README.md) for safeguards,
limitations, annual-source reuse, and command-line options.
