# Cashier report filing watcher

This Windows-only workflow watches the signed-in employee's Downloads folder.
Downloads that do not match a configured report filename are ignored silently.
When a matching report finishes downloading, the employee confirms its report
date, final filename, and complete destination before it is processed.

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

## JPMLB transaction results

The watcher recognizes `Transaction_Results_MM_DD_YYYY_HH_MM_SS.csv` with a
valid date and time. Browser duplicate names such as `... (1).csv` are ignored.

The confirmation starts with the date from the downloaded filename. Correct
the date when the business date differs from the download date. The date updates
the fiscal year, period, output filename, and destination shown on screen.

After confirmation, the workflow reproduces the JPMLB macro's column changes,
summary rows, formulas, colors, number formats, widths, filter, and frozen header.
It creates:

```text
%OneDriveCommercial%\GRP-Bursar Office - General\Y-Brswork\Cashier\Payments\FY27\P01 - July 2026\JPMLB 07-31-2026.xlsx
```

The CSV must contain a header, at least one data row, and at least 16 columns.
Original columns L:N are removed. New CWID and NAME columns are inserted in O:P.
The resulting amount column M must contain numeric amounts or blanks.

The fiscal-year and period folders must already exist. An existing JPMLB workbook
is never overwritten. The CSV stays in Downloads if validation or workbook
creation fails and is removed only after the XLSX is created and reopened
successfully.

## Before installing

1. Run `setup.ps1` and enter the employee's name and initials.
2. Open `config/report_filing.psd1`.
3. Confirm the RDC `BusinessDirectory`, the JPMLB
   `DestinationBusinessDirectory`, and the `FiscalYearDirectoryPattern` (`FY27`,
   for example). Ensure both destination fiscal-year and period folders exist.

`SourceFilePattern` narrows discovery; `SourceTimestampFormat` validates the full
filename and extracts its date before a confirmation can appear.

## Install or update the watcher

From the desktop GUI, an administrator can enable **Set Up Report Watcher**
for the Cashier view under **Staff access → Manage views & permissions**.
The cashier then opens that workflow under their own Windows account, chooses
**Review & run**, and confirms **Run workflow**. This invokes the same installer
as the shortcut below; it does not install for a different selected staff member.
Complete `setup.ps1` first to save the cashier's name and initials.

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
- RDC reports verify the `%PDF-` signature before moving.
- JPMLB CSVs are structurally validated before a workbook is created.
- The file must be unlocked, nonempty, and stable before a prompt appears.
- The report date controls the July-through-June fiscal year and period folder.
- Destination folders must already exist.
- Existing destination files are never overwritten.
- RDC files are copied to a temporary file and hash-verified before the final
  move. JPMLB workbooks are created under a temporary name, reopened and checked,
  and then assigned the final name. Only then is the Downloads copy removed.
- Cancel leaves the file in Downloads and suppresses that exact unchanged file.
  A modified or newly downloaded file with the same name is considered new.

Local settings, cancellation state, and logs are stored under:

```text
%LOCALAPPDATA%\HigherEdAutomation
```
