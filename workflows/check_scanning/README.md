# PaperCut check scan review

The Cashier Tools workflow **Check Scan Review** watches the top level of the
signed-in user's business OneDrive folder `Apps/Scans for PaperCut MF`.
All locally readable PDFs are eligible regardless of filename, employee login,
case or batch. It recognizes PDFs by content even if a name has lost its
extension. Temporary transfer files are skipped. The watcher waits for two
unchanged observations before opening a file and checks again after reading.
On startup it checks the whole folder, including older scans.

## Running on a workstation

Run the usual `setup.ps1` after installing this development update. The pinned
PDFium renderer and RapidOCR CPU models run on the workstation. Models ship with
the installed wheel. The workflow uses no remote OCR service.
An empty intake opens normally and waits for scans. If the workflow reports
missing PDF or OCR components, close the app, run `setup.ps1` from the updated
repository, and reopen the app.

An administrator can assign **Check Scan Review** (`check_scan_review`) to the
Cashier view under **Staff access → Manage views & permissions**. Opening it
starts intake and catches up while the review queue is open. To prepare the queue
while the window is closed, select **Enable scanning at sign-in** under the
cashier's Windows login. This installs and starts a separate limited, per-user
scheduled task. The equivalent setup command is
`setup/setup_report_filing_watcher.ps1 -CheckScans`. The check watcher has its
own single-instance lock and never opens a per-file prompt.

The pilot queue is stored at
`%LOCALAPPDATA%/HigherEdAutomation/check-scanning/pilot-queue.sqlite3`.
It stores source filenames, change information, content fingerprints, status,
suggested company and serial, boxes, and filing receipts. Page images, full OCR
text, MICR contents and signatures are not stored in the queue. Original PDFs
remain in the scanner inbox. A renamed copy of previously filed content is
recognized by its fingerprint on the same workstation.

## Recognition and review

Each PDF is treated as one check and its supporting pages. OCR inspects every
page. It looks directly for the paired E-13B transit symbols and the spacing of
the nine intervening routing digits, even when OCR cannot read the symbols.
Recognized MICR delimiters with digits or a routing checksum beside another
numeric field also provide strong evidence. Check-face labels can corroborate a
long numeric band when OCR joins the fields. The band can occur anywhere on a
page. A weak band, pay-to-order text alone or an unreadable image needs review.
Ordinary invoice text alone is ignored. No confidence level files a PDF.

- **Check** and **Needs a look** appear in the queue. **Could not read** indicates
  an incomplete or unreadable PDF. Replace or resync the source to retry it.
- **Show all scans** also reveals unrelated, dismissed, and filed items. During
  the pilot, reopen a filed scan to test another redaction. When the desired
  filename exists, approval adds a number such as `(2)` to the new test copy.
  Dismissal leaves the source in place.
- Verify the issuer and printed check number. A suggested MICR box covers the
  line as a unit. A printed signature label can locate a proposed signing area.
  Missing or inaccurate suggestions require manual correction. Use the page
  controls and zoom, select a box type and drag to draw, drag a box to move it,
  or drag a corner to resize. Delete and undo are available before approval.
  **Skip for now** keeps the scan queued and discards unsaved edits.
- Inspect backup pages and the opaque **Redacted preview**. If a single scan
  contains separate checks or unrelated documents, separate the packet before
  filing. Multiple detected check pages are held for manual handling.
- The approval area shows the remaining steps. Open every page, add any missing
  MICR or signature boxes, and resolve filename errors. Then check the review
  confirmation to enable **Approve & Next**. Changes to the filename or boxes
  require a fresh confirmation.
- The next review shows the filename just saved. Once the review queue is
  empty and intake has caught up, **Queue complete** shows the session's count,
  source and destination folders, and original and redacted filenames. Closing
  the summary ends the review session. The optional sign-in watcher can keep
  checking for later scans.

## Pilot output

Approval saves to `Documents/Tests` under the signed-in user's home directory.
The app shows the full path before approval and creates the folder on first
save. For the synthetic issuer Example Company and serial 000482, Windows saves:

```text
%USERPROFILE%/Documents/Tests/Example Company - 000482.pdf
```

Approval checks the source fingerprint,
renders each displayed page onto new pixels, blacks out the selected areas, and
embeds only those resulting images in a fresh PDF. This deliberately removes
text layers, attachments and interactivity throughout the packet, including
backup pages. Page sizes and order are preserved. The staged copy is reopened
to verify its page count before publication. Existing destination files are
never overwritten. During the pilot, originals stay in the PaperCut inbox.

After pilot approval, the planned shared destination is the Controller's
`Accounting/Accounting (Shared)/CASHIER/CASHNet Copies/FYxx` folder. The
production queue will start with its own filing history so pilot copies do
not count as shared filings.

For workstation acceptance, use synthetic small checks, full-sheet stubs,
check-plus-backup packets, ordinary invoices, rotated or faint scans, and two
issuers with similar names. Verify the queue, editable marks, filed copy,
destination and time per packet on the actual printer and workstation.
