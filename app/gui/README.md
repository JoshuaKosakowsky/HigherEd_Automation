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

- **Student Testing Population**, using its existing typed Python configuration
  and pipeline. It does not have a run-level TEST or PROD switch: the workflow
  creates balanced TEST/PROD assignments inside the result workbook.
- **Refund Review**, using the existing manual-download Python pipeline. An
  administrator selects the matching transaction and account-context exports
  from Insights. The app calculates and formats the review locally; it does not
  approve or issue refunds. API extraction, resuming batches, and single-account
  API validation remain available through the existing PowerShell launcher.
- **Textbook Brokers**, using the existing local transformation to combine one
  or more selected `finaid_*.csv` / `ia_*.csv` sources into a new TSPLOAD file.
  The GUI action does not connect to SFTP, move source files, confirm a Banner
  upload, or archive anything. Those consequential orchestration stages remain
  in the existing PowerShell launcher.

## Workflow visibility

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
to Analyst and Cashier views. Updates are validated, written atomically, and
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

1. split Textbook Brokers SFTP discovery/preview from its consequential archive
   execution before exposing those stages in the GUI;
2. decide whether Refund Review API extraction and batch-resume controls belong
   in the GUI after the manual workflow has been operationally validated;
3. explicitly approve workflows for the AR/Analyst and Cashier views;
4. integrate Historical Trends after confirming its role and input/output selection;
5. add a small structured recent-activity file now that more than one workflow is
   available.

Adding a workflow should usually require a `WorkflowDefinition` and a thin
adapter that calls its reusable Python API. Do not put business rules in page or
button callbacks.
