# Mines Bursar Automation desktop app

This Tkinter/ttk application is the staff-facing front end for supported
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
- `pages/` renders the home and generic workflow-detail views from metadata.
- file inputs accept direct paths, Browse selection, and native Explorer/Finder
  drops. `tkinterdnd2` is the single dependency used for external file drops.
- `services/execution.py` runs one task at a time on a worker thread and converts
  exceptions into staff-safe messages while preserving tracebacks in the log.
- workflow-specific service adapters translate form values into existing
  pipeline configuration. They do not reimplement processing rules.
- `launcher/run_gui.ps1` starts the app with the repository virtual environment.
- `powershell/gui/tk_runtime.ps1` discovers and validates the base Python Tcl/Tk
  libraries and supplies process-scoped paths to setup and the GUI launcher.
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
case-insensitively to `config/gui_access.json`. Each user profile contains a
display name, informational job title, and an explicitly assigned view. Job
titles never grant access. The central `views` map is the only place that lists
which workflow IDs each view may display.

Administrator uses the `"*"` workflow allow-list and sees every registered
workflow. The current analyst and cashier allow-lists are deliberately empty;
those staff members receive no workflow cards until the application owner adds
specific workflow IDs. An unassigned login also sees no cards and receives a
contact-the-administrator message.

The live `config/gui_access.json` contains staff account identifiers and is
ignored by Git. `config/gui_access.example.json` documents the public-safe
schema. A private deployment can distribute the live file through an approved
internal channel. Do not commit the live staff mapping to a public repository.

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

Path entry and Browse work even when the optional drag/drop package has not yet
been installed in that Mac Python environment. To enable Finder file drop:

```bash
python3 -m pip install tkinterdnd2==0.6.1
```

The `--review-as` identity override is rejected on Windows staff installations.
Windows setup installs the drag/drop package and creates and destroys a real
TkinterDnD window during verification. A missing or incorrectly resolved
`init.tcl` therefore fails setup with a Tcl/Tk repair message instead of failing
later from the desktop shortcut.

Run the automated suite with:

```powershell
.\tests\run_tests.ps1
```

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
