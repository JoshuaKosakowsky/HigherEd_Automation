# Student contact information lookup

`student_preferred_contacts.sql` replaces `OS_Checks.sql`. It returns one row
per qualifying student PIDM, with CWID, first/last name, Mines email and its type,
and phone (including area code/extension) and its type.
It does **not** query a check, payment, refund, or outstanding-check population.

## Population and contact rules

A student has any `SGBSTDN` record, including former students. `EXISTS` prevents
multiple student terms from duplicating the student. Only current `SPRIDEN`
identity rows qualify (`CHANGE_IND IS NULL`). Duplicate current identities
are ranked by CWID/name to select one consistently per PIDM; investigate such
source anomalies. Distinct PIDMs sharing a CWID are a source-data issue, not
silently merged by this report.

Accounts must have a `TAISMGR.TBBACCT` record with `TBBACCT_ACTIVITY_DATE`
from the start of the current month minus **eight years**, through today
(inclusive). For a run on October 16, 2026, that means October 1, 2018 through
October 16, 2026. Older, NULL-dated, future-only, and missing account records
are excluded. Duplicate account records cannot multiply student rows.

This replaces the old email-update cutoff with an account-record recency
filter: an unchanged email can still belong to a recently updated account.
An account update can be administrative; it does not prove current enrollment,
recent payment, an outstanding balance, or formal active status. Former students
can qualify if their account was updated recently. A qualifying active Mines
email is required; there is no enrollment/financial eligibility rule.

The query materializes the distinct recent-account population, then the student
population before ranking contacts. This narrows the contact work and avoids
rebuilding the student population for each contact join. Date comparisons leave
the account date column uncast so available indexes remain usable. Actual
runtime depends on Insights replication, indexes, and the number of qualifying
accounts; no live performance measurement has been made.

Students are excluded if either qualifying contact is missing. Email and phone
numbers must be nonblank, and their types must match the codes below. Email
preference and phone primary indicators do not affect selection.

- Email: nonblank, active (`A`) `GOREMAL` address with type `UNIV` (Mines).
  Latest activity wins (NULL last), then address/type to break ties. Personal
  email is not substituted when no qualifying Mines address exists.
- Phone: nonblank `SPRTELE` number of type `PR`, excluding inactive (`I`)
  records; NULL status is treated as active. If no usable `PR` exists, select
  `CELL`. Type priority comes first, then highest sequence number, followed
  by number, area, extension, and type for ties. Blank/inactive `PR` records
  do not block the `CELL` fallback. Other phone types are excluded.

Export columns are `CWID`, `First Name`, `Last Name`, `Mines Email`, `Email Type`,
`Phone Number`, and `Phone Type`. `Mines Email` and `Phone Number` replace the
former `Preferred Email` and `Preferred Phone` headers because the selection
no longer follows preference flags. The existing SQL filename is retained
for callers and saved-report references.

Each contact is ranked before joining, avoiding the email-by-phone fan-out
that repeated CWIDs in the old report. The output keeps only the selected
contact types rather than repeating status/preference/activity metadata.

## App export from PROD

1. Open **Connections**, select **PROD**, and connect using the existing sign-in.
2. Choose **Contact — Student contact information** and export to a new `.xlsx`.

The SQL and workbook contain only the seven identity/contact columns. There
is no `Report Row Count` column or report-specific row-count completeness check.
Use Insights export if API limits prevent returning the complete report.

The existing `contact_lookup` query ID is preserved. TEST remains available
with the same SQL; environment selection and export safeguards are unchanged.

## Staff Insights report

Create a native SQL question against the PROD Banner database, paste the
contents of `student_preferred_contacts.sql`, and save it as **Student contact
information** in the appropriate staff collection. The SQL is standalone and
requires no app placeholders or parameters. App and staff use the same file
to avoid divergent contact rules. Update any saved question using `OS_Checks`;
renaming a repository file does not update a published question automatically.

Optional staff filters can target CWID on the saved result. Configure
collection permissions through existing institutional access controls.

## Validation

Run `validate_contact_schema.sql` first and resolve every `MISSING` result.
Confirm the local meanings of `UNIV`, `PR`, `CELL`, `A`, `I`, and NULL phone status.
Compare selected contacts with Banner, including multiple UNIV/PR records and CELL fallback,
exclusion of incomplete contacts, and former students. Confirm account activity
against Banner, including records at the eight-year boundary. Investigate duplicate
current identity records or CWIDs assigned to distinct PIDMs. Insights replication may lag.

Synthetic SQLite tests execute the actual SQL with students, duplicate contact
records, ignored preference flags, PR/CELL priority, inactive/blank contacts,
missing contact types, and identity history.
They also cover old, missing, NULL-dated, duplicate, boundary, and future account
records using a fixed run date. Only PostgreSQL date expressions are adapted
for SQLite. They verify selection and export columns without production data
or credentials; they do not establish live PROD compatibility or performance. This report makes no Banner changes.
