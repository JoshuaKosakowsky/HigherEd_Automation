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

- `workflow_registry.py` holds typed, staff-facing workflow metadata.
- `models.py` defines workflow inputs, execution context, and results.
- `pages/` renders searchable workflow cards, registry-driven forms, and staff administration.
- `theme.py` provides the Mines palette, a navy navigation sidebar, and light workspace.
- Staff profiles use a single editable form with a view dropdown; permissions use checkboxes.
- file inputs accept direct paths, Browse selection, and native Explorer/Finder
  drops, using Qt's native local-file URL support. No separate drop package is required.
- `services/parameters.py` preserves input parsing independently of the toolkit.
- Each run has a review dialog. TEST is preferred where modes exist; production
  displays the workflow warning and requires an explicit Run in production action.
- `services/execution.py` runs one task at a time on a worker thread and converts
  exceptions into staff-safe messages while preserving tracebacks in the log.
- workflow-specific service adapters translate form values into existing
  pipeline configuration. They do not reimplement processing rules.
- `launcher/run_gui.ps1` starts the app with the repository virtual environment.
- Setup installs pinned `PySide6-Essentials` and verifies a real Qt window.
  The GUI launcher checks Qt availability; the obsolete Tcl/Tk helper and its
  dedicated tests have been removed.
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
- **Refund Review**, using the existing manual-download Python pipeline. An
  administrator selects the matching transaction and account-context exports
  from Insights. The app calculates and formats the review locally; it does not
  approve or issue refunds. API extraction, resuming batches, and single-account
  API validation remain available through the existing PowerShell launcher.
- **Textbook Brokers**, using the existing PowerShell and WinSCP integration to
  download pending `finaid_*.csv` / `ia_*.csv` sources from the configured SFTP
  server and transform them into TSPLOAD. The GUI accepts the Banner term and
  runs the launcher in non-interactive prepare-only mode. It does not confirm a
  Banner upload or archive local or remote files. After the upload succeeds, run
  `archive-textbook-brokers -TermCode <the same term>` from PowerShell to perform
  the existing guarded archive step.

## Workflow visibility

### Insights connections (administrators)

Active app administrators have a **Connections** page. TEST is selected by
default; choose TEST or PROD explicitly and click
**Connect and sign in**. Sign in to MyMines in the dedicated automation browser, open the
selected environment's Experience address shown on the page in that same window,
and launch its Insights reporting application. The browser closes after handoff
or timeout, retains persistent SSO state locally when the identity provider
allows it, and the GUI then shows
the actual result. The check runs only `connection_check.sql` (`SELECT 1`), not
the student sample query, and does not export files.

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

Access is rechecked before each connection action. PROD connection checks
require confirmation. Connection operations reuse the background executor;
authentication errors are sanitized before the general GUI logger sees them.
The administrator Connections page also has a query picker and **Run selected
query and save Excel**. Select TEST or PROD, choose a report, and choose the
workbook destination. PROD requires a separate confirmation. The picker uses
the explicit list in `shared/insights/query_catalog.py`; it never accepts an
arbitrary SQL path. Available reports include current and previous calendar
month transaction and payment activity, the existing historical loan activity
draft, contact lookup, Parent PLUS sample, sponsored student summary, refund
review SQL, the two manual refund extracts, the Banner term sample, four
institutional-loan enrollment reports, and two SHIP Fall exceptions. The loan
and SHIP reports prompt for a six-digit Banner term. The SHIP reports require a
Fall term ending in `80`. The term is validated and inserted as a quoted SQL
literal; no raw free-form SQL is accepted from the interface.

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
limit. This is a proof of concept and does not change operational workflows.

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
While a workflow runs, navigation and window closing are blocked. Completion
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

## Deployment boundary and next integrations

The next useful migration steps are:

1. decide whether Refund Review API extraction and batch-resume controls belong
   in the GUI after the manual workflow has been operationally validated;
2. explicitly approve workflows for the AR/Analyst and Cashier views;
3. integrate Historical Trends after confirming its role and input/output selection;
4. add a small structured recent-activity file now that more than one workflow is
   available.

Adding a workflow should usually require a `WorkflowDefinition` and a thin
adapter that calls its reusable Python API. Do not put business rules in page or
button callbacks.
