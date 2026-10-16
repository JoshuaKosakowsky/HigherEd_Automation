# Student contact information lookup

`student_preferred_contacts.sql` replaces `OS_Checks.sql`. It returns one row
per qualifying student PIDM, with CWID, first/last name, preferred email and its type,
and preferred phone (including area code/extension) and its type.
It does **not** query a check, payment, refund, or outstanding-check population.

## Population and contact rules

A student has any `SGBSTDN` record, including former students. `EXISTS` prevents
multiple student terms from duplicating the student. Only current `SPRIDEN`
identity rows qualify (`CHANGE_IND IS NULL`). Duplicate current identities
are ranked by CWID/name to select one consistently per PIDM; investigate such
source anomalies. Distinct PIDMs sharing a CWID are a source-data issue, not
silently merged by this report.

The old query required preferred active `UNIV` email changed within two years
of the current month (the old README incorrectly said six years). That cutoff
and the university-only population restriction are removed. There is no
current-enrollment, balance, outstanding-check, or date restriction.
Students are excluded if their selected preferred email, email type, primary
phone, or phone type is NULL, empty, or whitespace-only. No nonpreferred
contacts are substituted. Type checks apply after ranking; an incomplete
selected contact does not cause an older contact to be substituted.

Contact selection follows the existing delinquency outreach report:

- Email: nonblank, active (`A`), preferred (`Y`) `GOREMAL` address. University
  (`UNIV`) wins among qualifying addresses, then latest activity (NULL last),
  then address/type to break ties. A preferred personal address can therefore
  be selected if no qualifying preferred university address exists.
- Phone: nonblank primary (`Y`) `SPRTELE` number, excluding inactive (`I`)
  records; NULL status is treated as active. Highest sequence number wins,
  followed by number, area, extension, and phone type for ties.

Each contact is ranked before joining, avoiding the email-by-phone fan-out
that repeated CWIDs in the old report. The output keeps only the selected
contact types rather than repeating status/preference/activity metadata.

## App export from PROD

1. Open **Connections**, select **PROD**, and connect using the existing sign-in.
2. Choose **Contact — Student preferred contacts** and export to a new `.xlsx`.
The SQL and workbook contain only the seven identity/contact columns. There
is no `Report Row Count` column or report-specific row-count completeness check.
Use Insights export if API limits prevent returning the complete report.

The existing `contact_lookup` query ID is preserved. TEST remains available
with the same SQL; environment selection and export safeguards are unchanged.

## Staff Insights report

Create a native SQL question against the PROD Banner database, paste the
contents of `student_preferred_contacts.sql`, and save it as **Student preferred
contacts** in the appropriate staff collection. The SQL is standalone and
requires no app placeholders or parameters. App and staff use the same file
to avoid divergent contact rules. Update any saved question using `OS_Checks`;
renaming a repository file does not update a published question automatically.

Optional staff filters can target CWID on the saved result. Configure
collection permissions through existing institutional access controls.

## Validation

Run `validate_contact_schema.sql` first and resolve every `MISSING` result.
Confirm the local meanings of `UNIV`, `A`, `Y`, `I`, and NULL phone status.
Compare selected contacts with Banner, including duplicate preference flags,
exclusion of incomplete contacts, and former students. Investigate duplicate current identity
records or CWIDs assigned to distinct PIDMs. Insights replication may lag.

Synthetic SQLite tests execute the actual SQL with students, duplicate contact
flags, inactive/blank contacts, missing contact types, and identity history.
They verify contact selection, exclusion rules, and app export columns without production records or credentials; they do not establish
live PROD schema compatibility. This report makes no Banner changes.
