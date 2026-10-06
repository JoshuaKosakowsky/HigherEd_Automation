# Deliquent student accounts

Run `validate_hold_schema.sql` in Banner Insights first and confirm every field
is `FOUND`, then run `deliquent_student_accounts.sql`. Both queries are read-only.
The report returns `CWID`, `First Name`, `Last Name`, `Amt`, `Past Due Amt`,
`Preferred Email`, `Preferred Phone`, and `Hold`, with the largest net balance first.
The filename retains the requested spelling, `deliquent`.

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
