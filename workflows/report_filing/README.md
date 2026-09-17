# Cashier report filing watcher

This Windows-only workflow watches the signed-in employee's Downloads folder.
Downloads that do not match a configured report filename are ignored silently.
When a matching PDF finishes downloading, the employee must confirm its report
date, cashier initials, final filename, and complete destination before it moves.

## Submission confirmations

The watcher recognizes `Submission_Confirmation_MM_DD_YYYY_HH_MM_SS.pdf`
with a valid date and time. Other names, including browser duplicate names such
as `... (1).pdf`, are ignored.

The confirmation starts with the date from the downloaded filename and the
signed-in employee's initials saved during setup. Edit the initials when filing
for another cashier; this does not change the employee's saved defaults. The
report/deposit date can also be corrected before confirming.

The final name is `MM-DD-YYYY_INITIALS RDC.pdf`. Select the unchecked-by-default
**Bank 2723** option to use `MM-DD-YYYY_INITIALS RDC 2723.pdf` instead.
Review the filename and destination, then choose **Confirm and Move**.

For example, `Submission_Confirmation_07_31_2026_14_05_09.pdf` with initials
`ABC` is filed as:

```text
%OneDriveCommercial%\GRP-Bursar Office - General\Y-Brswork\Cashier\Daily Closing\FY27\P01 - July 2026\07-31-2026_ABC RDC.pdf
```

The shared fiscal-period logic uses July as period 1 and June as period 12.
The confirmed report date determines both folders.

## Before installing

1. Run `setup.ps1` and enter the employee's name and initials.
2. Open `config/report_filing.psd1`.
3. Confirm the `BusinessDirectory` spelling and the
   `FiscalYearDirectoryPattern` (`FY27`, for example), and ensure the destination
   fiscal-year and period folders exist.

`SourceFilePattern` narrows discovery; `SourceTimestampFormat` validates the full
filename and extracts its date before a confirmation can appear.

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
