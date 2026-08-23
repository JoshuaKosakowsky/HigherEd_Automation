# Cashier report filing watcher

This Windows-only workflow watches the signed-in employee's Downloads folder.
Downloads that do not match a configured report filename are ignored silently.
When a matching PDF finishes downloading, the employee must confirm its report
date, cashier initials, final filename, and complete destination before it moves.

## Before installing

1. Run `setup.ps1` and enter the employee's name and initials.
2. Open `config/report_filing.psd1`.
3. Replace `PLACEHOLDER_DAILY_CLOSING*.pdf` with the website's downloaded
   filename or a narrowly scoped PowerShell wildcard pattern.
4. Confirm the `BusinessDirectory` spelling and the
   `FiscalYearDirectoryPattern`. The initial fiscal-year assumption is `FY27`.

## Install or update the watcher

Run this PowerShell shortcut after installing the repository shortcuts:

```powershell
setup-report-watcher
```

The installer creates a Task Scheduler task for the current Windows employee.
It starts the watcher at sign-in, keeps the PowerShell window hidden, prevents
overlapping instances, and restarts the watcher after an unexpected failure.

Run `setup-report-watcher` again after moving the repository or changing the
PowerShell installation. Changes to report configuration do not require a new
scheduled task. Apply them by signing out and back in or by rerunning
`setup-report-watcher`, which restarts the watcher immediately.

## Safety behavior

- The source must match exactly one configured report definition.
- The first version accepts PDF reports only and verifies the `%PDF-` signature.
- The file must be unlocked, nonempty, and stable before a prompt appears.
- The report date controls the July-through-June fiscal year and period folder.
- Destination folders must already exist.
- Existing destination files are never overwritten.
- The workflow copies to a temporary file, compares SHA-256 hashes, assigns the
  final name, and only then removes the Downloads copy.
- Cancel leaves the file in Downloads and suppresses that exact unchanged file.
  A modified or newly downloaded file with the same name is considered new.

Local settings, cancellation state, and logs are stored under:

```text
%LOCALAPPDATA%\HigherEdAutomation
```
