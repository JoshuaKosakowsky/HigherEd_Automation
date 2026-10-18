# Refund check contacts for AP matching

`refund_check_contacts.sql` is a read-only contact source for the monthly O/S
review. It is shared unchanged by a saved Insights question and the application's
administrator report exporter. `student_preferred_contacts.sql` is unchanged.

## Current rules

The owner confirmed in the October 18, 2026 project conversation that AP supplies
the outstanding-check population and the recipient suffix. Banner does not track
whether these checks are cashed. This report does not determine check status,
send messages, or match AP files automatically. No issue/PR decision reference
has been supplied for this new report.

- Select accounts with `TBRACCD_DETAIL_CODE` equal to `RFND` or `RFDP` and
  `TBRACCD_FEED_DATE` from `CURRENT_DATE - INTERVAL '200 days'` through today,
  inclusive. Exclude NULL dates and future dates. The date is the database's
  current date. Do not apply the older lookup's eight-year account-activity
  requirement or an enrollment requirement.
- Return one student-contact row per RFND account and one parent-contact row per
  distinct borrower suffix on each RFDP account. Multiple refunds do not multiply
  contact rows. First/Latest Feed Date describe the qualifying refund activity;
  they do not identify a particular check. No transaction numbers or amounts are
  returned. No sign, balance, reversal, void, or cleared-status exclusion is
  inferred: AP determines the actual outstanding population.
- RFND uses the current `SPRIDEN` identity and the existing contact lookup's
  active, nonblank `UNIV` email and usable `PR` phone, falling back to `CELL`.
  Ranking, inactive-phone handling, formatting, and preference-flag behavior
  match that lookup. Duplicate current identities are ranked consistently;
  investigate source anomalies rather than treating this as identity correction.
- RFDP obtains every distinct `RLRPAPP_BORROWER_ID_NO` for that student PIDM,
  across aid years and authorization values. AP identifies which borrower was
  paid, so the report does not infer that relationship from aid year or the
  PLUS-to-student flag. First/last name, phone and email come exclusively from
  `RLRPAPP_BORR_FIRST_NAME`, `BORR_LAST_NAME`, `BORR_PHONE_NO`, and `BORR_EMAIL`.
  Student contacts are never substituted for a missing parent contact.
- `Borrower CWID` concatenates Student CWID and the trimmed stored suffix without
  a separator or numeric conversion. `Borrower Suffix` is also returned.
  Leading zeros survive when present in the source; no padding is invented.
  A blank/missing suffix leaves Borrower CWID blank and flags review.
- For repeated application rows per student/suffix, select the latest activity
  date (NULL last), then latest aid year (NULL last), then name/email/phone for
  deterministic ties. Select all contact fields from that same source row.
  Different normalized name/phone/email combinations for a suffix trigger
  `Borrower contact records differ; verify selected record`, including when a
  difference is historical. Exact duplicates do not trigger that warning.
- Keep missing identities, missing borrower records and incomplete contacts.
  `Contact Review` flags missing CWID, suffix, recipient name, email or phone,
  and differing borrower profiles. `Contacts available` means fields exist;
  it does not validate deliverability or authorize outreach. Student contact
  types are UNIV/PR/CELL; parent contact source labels are RLRPAPP.

## Synthetic acceptance examples

| Input | Expected output |
| --- | --- |
| RFND at exactly 200 days ago, another RFND today | One student row with first/latest feed dates |
| Refund at 201 days ago, tomorrow, or NULL date | Excluded |
| RFDP for TEST-A; borrower suffixes 01, 02, 35 | Three parent rows; Borrower CWIDs TEST-A01, TEST-A02, TEST-A35 |
| TEST-A also has RFND | Separate student row; no parent contact substituted |
| Borrower 01 appears in two aid years | One 01 row, latest record selected; differing contacts flagged |
| Missing Mines email, usable CELL but inactive PR | Row retained, CELL selected, missing email flagged |
| RFDP without RLRPAPP records or with blank suffix | Row retained, blank Borrower CWID, missing fields flagged |

## Configuration and verification

Run `validate_refund_check_contacts_schema.sql` in the target Insights database
and resolve MISSING results, including field types. Confirm the borrower suffix
is replicated with its leading zeros and that RLRPAPP PIDM is the student PIDM.
Compare a limited authorized sample to RLAPAPP and AP, including multiple
borrowers, contact changes, missing contacts and the date boundary. Replication
may lag. Synthetic tests do not establish live schema compatibility or acceptance.

Create a native SQL question using the entire SQL file, with no parameters,
named **Refund check contacts for AP matching**, in the approved staff collection.
Publishing that saved question and setting its permissions are separate from
adding its source file to this repository.

In the app, an administrator selects **Connections**, the appropriate TEST/PROD
environment, and **Contact — Refund check contacts for AP matching**, then
exports to a new `.xlsx`. Existing login, environment and no-overwrite safeguards
apply. `Report Row Count` lets the app reject truncated results before saving;
the app removes that technical column from the workbook. It remains in raw
Insights results. Empty results retain the output headers. Use Insights export
if API limits prevent a complete app export.

Keep operational staff instructions and manual fallback in the office's approved
Word SOP; this README is technical documentation, not SOP delivery.
