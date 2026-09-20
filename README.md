# HigherEd Automation

This repository contains the Colorado School of Mines automation tools used by
the Bursar's Office and related business processes.

The instructions below are written for Windows users. You do not need to know
Python to set up or run the standard workflows.

## First-time setup

### 1. Confirm the prerequisites

Before starting, make sure:

- You are using a Mines-managed Windows computer.
- The complete `HigherEd_Automation` folder is synchronized to your computer.
- You have an internet connection.
- Python 3.11 or newer is installed.

If Python is not installed, download the current 64-bit Windows installer from
[python.org](https://www.python.org/downloads/windows/). During installation,
select **Add python.exe to PATH**.

### 2. Open PowerShell in this folder

Open the `HigherEd_Automation` folder in File Explorer. Right-click an empty
area in the folder and select **Open in Terminal**.

The PowerShell prompt should now show that it is inside the
`HigherEd_Automation` folder.

### 3. Run setup

Copy this command, paste it into PowerShell, and press Enter:

```powershell
.\setup.ps1
```

Setup creates a private Python environment inside this repository, installs
the required packages, verifies them, installs Playwright browser support, and
asks for your name and initials. It also installs the PowerShell shortcuts used
to run the automation tools and creates a **Mines Bursar Automation** desktop
shortcut. Your user details are stored only under your Windows account and can
be changed by running setup again. Setup may take several minutes the first
time.

The desktop interface uses PySide6 (Qt). When updating from version 0.4,
run setup again to install its new dependency. Setup verifies a real Qt window;
the desktop launcher no longer depends on Tcl/Tk.

Setup is successful when the terminal displays:

```text
SETUP COMPLETE
```

You do not need to activate Python manually. You can safely run `setup.ps1`
again after an update or if package installation was interrupted.

### If PowerShell says scripts are disabled

Run this command once:

```powershell
Set-ExecutionPolicy -Scope CurrentUser RemoteSigned
```

Enter `Y` if PowerShell asks for confirmation, then run `setup.ps1` again.

### 4. Open Mines Bursar Automation

Double-click **Mines Bursar Automation** on the Windows desktop. The app starts
with the repository's private Python environment; staff do not need to activate
Python or keep a PowerShell window open.

Available workflows are based on the signed-in Windows login and the shared
GUI access policy maintained by administrators from inside the app. The name saved
during setup is used only for the welcome message. The initial GUI integrations
are **Student Testing Population**, the manual-download **Refund Review**, and
the local **Textbook Brokers** CSV-to-TSPLOAD transformation. File inputs accept
a typed or pasted path, the Browse button, or a file dropped from Explorer.
Existing command-line workflows remain available.

### Optional PowerShell shortcuts

The shortcuts are the normal way to run the automation tools on computers that
need a workflow that has not yet moved into the desktop app. Setup installs them
automatically. Close PowerShell after setup completes, then open a new PowerShell
window. The shortcuts will load without any additional commands.

The following commands will now be available:

| Shortcut | Action |
| --- | --- |
| `open-auto` | Opens the repository folder in PowerShell. |
| `start-setup` | Runs setup again. |
| `test-automation` | Runs all automated repository tests. |
| `start-population-testing` | Runs Population Testing with default settings. |
| `start-refunds` | Runs the read-only refund review workflow. |
| `start-trends` | Runs Historical Trends with default settings. |
| `start-textbook-brokers` | Runs Textbook Brokers. |
| `archive-textbook-brokers` | Archives the current Textbook Brokers term after Banner upload. |
| `setup-report-watcher` | Installs or updates the Cashier Downloads watcher for the signed-in employee. |

GUI architecture, developer launch instructions, and the rollout boundary are
documented in [app/gui/README.md](app/gui/README.md).

## Cashier report filing watcher

This optional role-specific tool watches the signed-in employee's Downloads
folder and ignores unrelated files silently. A matching report opens a
confirmation window showing its report date, final filename, fiscal period, and
complete destination before anything is moved or transformed.

Submission confirmations named `Submission_Confirmation_MM_DD_YYYY_HH_MM_SS.pdf`
default to the filename's date and the employee's saved initials. The confirmation
allows another cashier's initials and an optional `2723` bank suffix. The watcher
also handles JPMLB transaction results named
`Transaction_Results_MM_DD_YYYY_HH_MM_SS.csv`; those CSVs are converted to
formatted XLSX workbooks and routed to the Cashier Payments fiscal-period folder.
Configuration and installation instructions are
in [workflows/report_filing/README.md](workflows/report_filing/README.md).

## Trusted browser sessions

Mines and Banner can use saved browser sessions so you do not have to complete
2FA every time.

For Banner, run:

```powershell
.\powershell\credentials\setup_trusted_session.ps1 -System Banner -Browser edge
```

For Mines, run:

```powershell
.\powershell\credentials\setup_trusted_session.ps1 -System Mines -Browser edge
```

A browser window will open. Log in normally, complete 2FA, and select
**remember this device** if prompted. When login is complete, return to
PowerShell and press Enter.

Never copy or commit the browser-profile folders to this repository.

## Troubleshooting

### Python was not found

Install the current 64-bit Windows version of Python from
[python.org](https://www.python.org/downloads/windows/). Select
**Add python.exe to PATH**, close PowerShell, reopen it in this folder, and run
`setup.ps1` again.

### The `.venv` environment is incomplete or uses an old Python version

Close any automation programs, rename the `.venv` folder to `.venv_old`, and
run `setup.ps1` again. After setup succeeds and the workflows run correctly,
the old folder can be deleted.

### Package or browser installation failed

Confirm that the computer is connected to the internet and rerun:

```powershell
.\setup.ps1
```

Setup is safe to rerun and will reuse a valid existing environment.

### A workflow cannot find its input

Read the missing-file path shown in the error. Confirm that the input filename
matches exactly and that OneDrive has finished synchronizing it.

### A workflow failed after it started

Review the newest file under `logs`. Preserve that log when requesting support;
it identifies the stage that failed without requiring another production run.

The desktop application writes its technical log under `logs/gui`. Use **Open
Log Folder** on a workflow page to locate it without opening PowerShell.
