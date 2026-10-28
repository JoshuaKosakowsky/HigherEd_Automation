# Student account holds and delinquency reports

## Collections demographic and academic profile

`collections_student_profile.sql` is the shared Insights/app report for all
historical CO hold date pairs, with hold status and academic context from
the term containing each CO start date. It includes demographics, term-effective
program/major/level, credit load, prior GPA/standing and reconstructed class.
From patch 0.25.2, Admissions (FGA) and FAFSA (FGF) have separate first-generation
indicators: each is Yes when its code is in the CO term's effective attribute
set and Unknown otherwise. Later outcomes are labeled. Patch 0.25.4 removes
redundant metadata/raw-code/review columns and displays the two CO term
boundary dates as YYYY-MM-DD. Run `validate_collections_profile_schema.sql` and
`inspect_collections_profile_codes.sql` before local acceptance. See
[field definitions, first-generation indicators and acceptance checks](collections_student_profile_README.md).
App 0.25.0 exposes it through the administrator-only Connections report picker.

From patch 0.25.3, `validate_collections_profile_indicators.sql` provides a
standalone aggregate-only Insights check: a total plus the four FGA/FGF
combinations, counts of indicator/effective-term mismatches, and counts of
missing context. It returns no student identifiers. See the report guide for
interpretation and refreshing the embedded report after source changes.

## W&F - Banner Recon (collections tracking)

`collections_tracking.sql` supports analyst reconciliation of accounts formally
sent to the collections agency, identified by a `CO` hold whose to date is
strictly after the database's `CURRENT_DATE`. Codes are trimmed and matched
without case sensitivity; comparisons ignore time of day. Holds ending today
or with NULL end dates do not qualify. There is no from-date cutoff: even a
future-start hold qualifies under the requested end-date rule.

The owner requested all qualifying accounts, including zero and credit balances,
with one row per student using the latest qualifying from date. NULL from dates
rank last; equal from dates use the latest to date. Exact duplicate holds yield
the same displayed values. The report uses current SPRIDEN identities
(`SPRIDEN_CHANGE_IND IS NULL`), assumed unique per PIDM. There is no enrollment
or SGBSTDN filter; the qualifying CO hold defines the account population.

Output (0.23.5): `CWID`, `Last Name`, `First Name`, `CO Hold`, `TO Hold`,
`CO From Date`, `CO To Date`, `Current Account Balance`, `WOFF`, `BDRC`,
`Total Balance`. Latest Feed Date is no longer selected. The balance uses the
delinquency report's all-term charges-minus-payments method with TBBDETC types
C/P, signed reversals and rounding to cents. Future terms are included. Unknown
detail types, missing amounts or no transactions leave the balance blank while
retaining the account; a blank is not a known zero. Transaction feed dates do
not restrict the population or balances.

From 0.23.4, [issue #15](https://github.com/JoshuaKosakowsky/HigherEd_Automation/issues/15)
combines W&F's Banner sources in this query. The owner clarified during
implementation: retain active CO accounts only, and sum signed posted Amount
for WOFF/BDRC. TO holds use the same end-date rule as CO and add an indicator
without adding rows. WOFF/BDRC include all dates and signed reversals, without
using remaining Balance. No matching code activity is zero when transactions
exist; unknown amounts stay NULL. Total Balance is Current Account Balance +
WOFF + BDRC; a NULL component leaves it NULL. No-transaction accounts stay blank.

Example: charges 500, WOFF payment Amounts 125 and -25, BDRC payment 50 give
Current Account Balance 350, WOFF 100, BDRC 50 and Total Balance 500. Duplicate
TO holds cannot multiply those totals. TO-only and WOFF-only accounts without
qualifying CO remain outside the population. This replaces the old hold-only
export schema; saved Insights questions must be updated before manual upload.

Run `validate_hold_schema.sql` first.
Paste the SQL into a native Insights question, or choose **Connections →
Holds — W&F - Banner Recon** in app 0.23.4 with administrator access. No
parameters are needed. The app reuses TEST/PROD connection controls, rejects
incomplete API results using `Report Row Count`, removes that internal count
from the workbook, and preserves existing files. Both CO date columns export
as real Excel calendar dates. Publishing a saved Insights question is separate.
App 0.19.1 preserves far-future hold dates such as 9999-12-31 as real Excel
dates; these exceed pandas' default timestamp range. Invalid dates still stop
the export without saving a workbook.

Synthetic acceptance examples (today = 2099-10-02):

- CO ending 2099-10-03 qualifies; ending 2099-10-02, even at 23:59, does not.
- Two qualifying CO holds starting January 1 and March 1 yield March 1's dates
  once, without multiplying the balance. A newer expired hold does not win.
- Charges 100, charge reversal -25, payment 20 and payment reversal -5 produce
  60, including across terms. Balances 0 and -50 remain in the output.
- A qualifying hold with no transaction rows remains with blank balances; an
  unknown detail type leaves balance blank for reconciliation.

Tests execute the actual SQL in SQLite with date syntax and the clock adapted,
and exercise the mocked app export. Before operational use, validate native
PostgreSQL execution and reconcile balances against TSAAREV and dates against
SOAHOLD, including duplicates, paid accounts and blanks. Confirm unique current
identities and detail-code definitions. Insights replication delay still applies.
The existing delinquency outreach report's any-CO exclusion is unchanged.

## RH delinquency review

`rh_delinquency.sql` returns every student whose account has
`TBBACCT_DELI_CODE = RH`, using the same source as the refund workflow.
Codes are trimmed and matched without case sensitivity. This is the account
delinquency field, separate from `SPRHOLD` hold records. No SPRHOLD record,
positive balance, transaction history, or current enrollment is required.
Former students qualify through any `SGBSTDN` record. Other holds, including
CO and PP, do not exclude students from this manual RH review.

Output has one row per current student identity: `CWID`, `First Name`,
`Last Name`, `Delinquency Code`, and `Account Activity Date`.
Only `SPRIDEN_CHANGE_IND IS NULL` identities are used. Multiple student-history
or RH control records do not multiply students; the latest activity among RH
control rows is displayed as a date without a time component. Excel exports
store it as a real date cell rather than text.
Missing activity dates remain blank and do not exclude students.

There is **no date cutoff**. The available `TBBACCT_ACTIVITY_DATE` records
account maintenance and does not establish when RH was assigned. Filtering it
as an RH start date could omit older holds after unrelated account changes.
Review the date as context only; confirm RH age and disposition in Banner.
The report does not remove RH or change Banner.

### Publish and run

1. Run `validate_hold_schema.sql` and resolve MISSING fields, including the
   three TBBACCT fields required by this report.
2. Paste `rh_delinquency.sql` into a native Banner Insights question named
   **RH delinquency review**. No variables or date/term inputs are needed.
3. Save in the staff AR collection and grant intended staff view/run access
   through existing Insights permissions, as for the wrong-term payment report.
4. Reconcile RH, non-RH, former-student, and missing-date examples against
   Banner before operational use. Allow for Insights replication delays.

Administrators can also choose **Connections → Holds — RH delinquency review**,
select TEST or PROD, and save a new `.xlsx` workbook. This reuses the existing
connection and export setup, rechecks administrator access before authentication,
and preserves existing files. No new workflow permissions are needed.

The SQL includes `Report Row Count`, counting the full result before API caps.
Compare this with exported rows when running in Insights. The app validates
the count and removes that internal column from Excel. Incomplete results
are rejected without saving; use an Insights export if the API caps the list.
An empty result means no qualifying students in the replicated data.

## Delinquent student accounts outreach

Run `validate_hold_schema.sql` in Banner Insights first and confirm every field
is `FOUND`, then run `deliquent_student_accounts.sql`. Both queries are read-only.
The report returns `CWID`, `First Name`, `Last Name`, `Amt`, `Past Due Amt`,
`Preferred Email`, `Preferred Phone`, and `Hold`, with the largest net balance first.
The filename retains the requested spelling, `deliquent`.

In the app, open **Connections**, select TEST or PROD, choose
**Holds — Delinquent student accounts**, and click **Run selected query and
save Excel**. No term input is required. Choose an approved workbook destination;
an existing workbook will not be overwritten. This uses the existing
administrator-only Insights export access.

This list supports outreach about upcoming late fees or collections. Accounts
with any `CO` hold record are excluded because they are already in collections
and should not receive these delinquency communications.
Accounts with PP holds are included for manual review. Transact errors affecting
payment arrangements cannot be determined from this Insights report, so a PP
hold alone does not establish whether a student should receive a message.

## Population and balance

- An account must have an `SGBSTDN` record. Former students are included;
  current enrollment is not required. Sponsor and other nonstudent accounts
  without student records are excluded.
- The current identity is the `SPRIDEN_CHANGE_IND IS NULL` row.
- `Amt` is `TBRACCD_AMOUNT` for charges (`TBBDETC_TYPE_IND = 'C'`) minus
  payments/credits (`'P'`), across **all terms**, including future terms.
  Negative amounts retain their sign so reversals offset the original posting.
- Only a net balance rounded to cents greater than zero qualifies. This does
  not select every unpaid charge or every positive term independently. A credit
  in another term offsets debt, and fully offset accounts are omitted.
- Missing amounts, unmatched detail codes, and types other than `C`/`P` exclude
  the entire account rather than producing an incomplete amount. This means
  the report is not exhaustive if such data exists; review those accounts
  separately before relying on it operationally.

## Past-due amount and contacts

`Past Due Amt` sums positive remaining `TBRACCD_BALANCE` values on charge
transactions whose `TBRACCD_DUE_DATE` is strictly before today. Charges due
today or in the future, fully paid charges, and payment rows are not included.
This uses remaining balances rather than original charge amounts to avoid
counting charges already paid. Date comparisons ignore time of day.

The value is NULL (blank) if any charge has a missing balance, or any positive
remaining charge has no due date. A known zero past-due amount displays zero.
The account still appears if it meets the original balance and hold rules;
there is no new requirement that `Past Due Amt > 0`.

This is a transaction-based past-due amount and depends on Banner payment
application. Unapplied payments or credits can leave overdue charge balances
larger than the net `Amt`; the query does not invent a credit allocation or cap
the value. Reconcile this with Banner before using it to determine eligibility.
The ODS aging reports use their own population/date filters, so their totals
need not match this student-only report without aligning those definitions.

`Preferred Email` selects a nonblank, active (`A`), preferred (`Y`) GOREMAL
address. University (`UNIV`) email takes priority among qualifying records,
then latest activity (NULL dates last), then address/type to resolve ties.
An active preferred address of another type is used if no preferred university
address qualifies. There is no activity-date cutoff.

`Preferred Phone` selects a nonblank primary (`Y`) SPRTELE number whose status
is not inactive (`I`), following the loan reports' treatment of NULL status as
active. Highest sequence number wins, with number/area/extension breaking ties.
Area code and extension are included when available. Non-primary numbers are
not substituted. Missing qualifying contacts display NULL without dropping the
student; ranking contacts before joining preserves one row per account.

Oldest due date is omitted because the existing aging reports cover aging.

## CO exclusion and PP review indicator

Any `SPRHOLD` record with hold code `CO` excludes the account, regardless of
start/end dates, including expired, future-dated, or NULL-dated records. This
implements the collections exclusion without inferring eligibility from CO
dates. Hold codes are trimmed and matched without case sensitivity.

A PP hold is active when its start date is today or earlier (or NULL) and its
end date is **strictly later than today**, using the database's `CURRENT_DATE`.
Dates are cast to `date`, ignoring time of day. `Hold` displays `PP` when at
least one active PP record exists; otherwise it is NULL (blank). Other hold
codes are not displayed. PP accounts remain in the output for manual review
against Transact before deciding whether outreach is appropriate. Multiple
holds cannot duplicate students because the PP indicator uses `EXISTS` and
the CO exclusion uses `NOT EXISTS`. An account with both PP and CO is excluded.

A hold ending today is not active under this requested rule. A future-start PP
hold is also not active, even when its end date is later. A NULL end date does
not satisfy `> CURRENT_DATE`; confirm whether local Banner practice treats NULL
as indefinite before relying on the PP indicator.

## Operational review and useful additions

Compare sample `Amt` values with TSAAREV and hold dates with SOAHOLD, including
cross-term credits, reversals, expired holds, future-start holds, and holds ending
today. Confirm that one current SPRIDEN row exists per PIDM and detail codes are
unique in TBBDETC. Insights refresh lag can make the list stale; recheck the live
balance and holds before taking action. A balance owed does not necessarily
mean it is due or eligible for a PP hold.

Validate sample past-due amounts, preferred contacts, and the local meanings of
contact indicators as well. Validate the institution's hold eligibility rules
before turning this review list into an action list. Despite the report name,
a positive net account balance alone does not establish delinquency.

Synthetic tests execute the report in SQLite with only date casts adapted to
SQLite's `date()` function and a fixed run date. They verify selection logic;
they do not replace live PostgreSQL schema and Banner reconciliation checks.
