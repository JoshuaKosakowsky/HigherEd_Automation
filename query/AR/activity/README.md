# Accounts Receivable activity reports

These reports read Banner account transactions from `TBRACCD` and current
identity information from `SPRIDEN`.

## Reports

### `tgiaccd_transactions.sql`: staff-selectable Banner extract

Publish this SQL as a saved native question named **Banner Activity by Date &
Detail Code** in Insights. Staff select dates and any detail codes, run the saved
question, and download XLSX or CSV without editing SQL. The same template is
also available in the application's administrator Connections report picker.

It returns transaction-level detail using separate **Start Feed Date (inclusive)**
and **End Feed Date (inclusive)** inputs. Both selected days are included in full,
including transactions with timestamps late on the end date. Any period, quarter,
year, or multi-year range can be supplied as actual dates; the query does not
infer the institution's fiscal calendar. An end before the start returns no rows.
Blank dates must be entered before running. Transactions without a feed date
are outside this report's population. The single date-range widget was not
supported in the owner's Insights installation, so this report uses basic Date
parameters instead.

The first ten column labels match the corresponding TGIACCD export labels,
including their surrounding quote marks. This is a general-purpose transaction extract, not
a complete copy of every TGIACCD display column. `Feed Indicator` is omitted
because `TBRACCD_FEED_IND` is not available in the owner's Insights database.
`Description` is the transaction
description from `TBRACCD_DESC`, which can contain a student reference on sponsor
accounts. `detail_code_description` is separate metadata from `TBBDETC`. `ID`
may identify a sponsor account; do not assume every ID is a student CWID.
The final column, `Transaction User`, exposes `TBRACCD_USER`, the user recorded
on the transaction. It may identify an automated process rather than a person.
Amounts and stored balances retain their original signs. This report does not
calculate a ledger balance or independently establish which codes post to 1305.

#### Publish and configure filters

1. Run `validate_activity_schema.sql` in the intended Banner database. Resolve
   every `MISSING` result before publishing.
   If a referenced column is absent, run `inspect_tgiaccd_schema.sql` to list
   the actual replicated column names and types. The supplied column inventory
   confirms **`TBRACCD_FEED_DOC_CODE`** for Feed Document, rather than
   `TBRACCD_FEED_DOC`. The report and required-column inventory use the confirmed
   name. Do not drop the reference field or substitute Feed Date: reconciliation
   requires the actual feed-document identifier.
2. Create a native SQL question in that database and paste
   `tgiaccd_transactions.sql`.
3. Configure the variables as follows:

   | Variable | Type | Configuration |
   | --- | --- | --- |
   | `start_date` | Basic **Date** | Display name **Start Feed Date (inclusive)**; one date; manual entry `YYYY-MM-DD` |
   | `end_date` | Basic **Date** | Display name **End Feed Date (inclusive)**; one date; manual entry `YYYY-MM-DD` |
   | `detail_codes` | **Field Filter** | Map to `TAISMGR.TBRACCD.TBRACCD_DETAIL_CODE`; table/field alias **`t.tbraccd_detail_code`**; equality / “is” operator; allow multiple values; dropdown list |

4. Set the detail-code default selection to **TPDT**, **TDLE**, and **Z0LE**.
   Enable **Always require a value** for this filter so clearing it does not
   turn the report into all-code activity. The default is saved-question
   configuration, not a SQL hard-coded restriction. Staff can replace the
   selection with other codes. If the dropdown is unavailable, have the
   administrator configure the mapped field's filtering metadata as a list of
   values and sync it. Verify all three default codes exist; the development
   sample only contained TPDT and Z0LE.
5. Start/end parameters are referenced unconditionally, so the report requires
   dates. If enabling **Always require a value** for the dates, the UI requires
   defaults too: choose an explicit initial review period and remind users to
   replace it for each run. Do not assume saved dates advance automatically.
   Set the saved question description to: **“Pull Banner account transactions
   for any selected detail codes within a feed-date range. Both start and end
   dates are inclusive, including the entire end date. Use the results for
   transaction review, reporting, and reconciliation.”**
   When updating the single-range version, remove its `feed_date_range` variable
   and any dashboard mapping to it, configure the two basic Date variables above,
   and save the question again.
6. Save the question into the staff's authorized collection. Configure the
   intended group's collection visibility, database access, and download
   permissions under your institution's Insights policy. Validate by signing in
   as a staff user without SQL-authoring privileges: open the question, change
   both dates and multiple codes, run it, and download the result. No app access
   rules are changed by adding this SQL.

These settings follow Metabase's [field-filter configuration](https://www.metabase.com/docs/latest/questions/native-editor/field-filters),
[SQL parameter settings](https://www.metabase.com/docs/latest/questions/native-editor/sql-parameters),
and [required-widget behavior](https://www.metabase.com/docs/latest/questions/native-editor/filter-widgets).
An Insights installation may use different labels or an older Metabase version;
check its parameter sidebar and preview the generated SQL. In particular,
`start_date` and `end_date` must be basic Date variables. `detail_codes` must be
a field filter, not a comma-separated text parameter. Configure its table/field
alias exactly as listed; Insights generates the complete detail-code predicate.

#### Automated app extraction (0.11.0)

In the administrator **Connections** page, explicitly select TEST or PROD and
choose **Activity — Banner Activity by Date & Detail Code**. Start/end calendars
default to the first of the current month and today. Replace those dates with
the actual period, quarter, year, or multi-year boundaries; fiscal boundaries
are not inferred. Both dates include the entire selected day. The comma-separated
code input starts blank with no default selections and accepts any four-letter/digit
code. At least one code is required before running. Input is normalized to uppercase and
duplicate selections are removed. Invalid input is rejected before sign-in.

Choose **Run selected query and save Excel** and a new filename. Existing
JWT/SSO sign-in exchanges the JWT for an Insights API session; a valid cached
session is reused. No JWT is pasted into the report inputs. This executes the
repository SQL through the authenticated native-query API, independently of
the saved question. The admin account must have native SQL access to the selected
database. The saved question remains the route for staff without Run Query access.
No application role permissions are broadened.

`shared/insights/banner_activity.py` validates inputs and provides
`extract_banner_activity(executor, parameters, sql_template=...)` for later
workflows. The executor only needs `run_sql(sql) -> pandas.DataFrame`; GUI,
authentication, and Excel writing stay outside the extraction logic. A future
database adapter can implement that contract; no direct database connection is
implemented in this update. The template is reused rather than maintaining a
second copy of its joins, columns, or date/code rules.

The app adds a private `COUNT(*) OVER ()` field to each API query and removes it
before export. If the API returns fewer rows than the count, extraction retries
non-overlapping smaller date windows. If a single day is still capped, the run
fails without writing a partial workbook; select fewer codes for that day.
Timeouts or permission failures also fail the run rather than produce a partial
file. Splitting is not a database snapshot: avoid changing the source while
extracting and validate authoritative totals. Legitimate duplicate transactions
are retained. Count checking detects truncation, not duplicate source joins or
incorrect reconciliation populations.

The output preserves the same 12 columns, raw signed amounts, and final
Transaction User column. Feed dates are real Excel date/time cells. It is a
plain worksheet without Excel Tables. Existing output files are not overwritten.
This provides Banner input for the upcoming 1305 workflow; it does not retrieve
Workday data or perform the reconciliation.

#### Validate and use the download

- Test a single day, including its late-night transactions, and verify that
  the next day's transactions are excluded. The query uses an exclusive upper
  bound at the start of the next day so the user-selected end date is inclusive.
  Reconcile a matching date/code
  selection to an authoritative TGIACCD export, comparing rows and signed amounts.
- Check a quarter or year by entering its actual start/end dates. Match Workday
  Accounting Date scope deliberately; feed timing differences remain review items.
- Download the **complete result**, rather than copying the preview. The report
  intentionally omits `extract_row_count`; it has no embedded truncation guard.
  Verify downloaded row counts and signed totals against an authoritative export
  for the same dates/codes. If export limits are reached, split into smaller,
  non-overlapping date ranges. Confirm whether an empty result is expected.
- Verify one current SPRIDEN record per selected PIDM and one TBBDETC record per
  code before relying on totals. Multiple metadata matches can duplicate rows;
  no row-count guard or deduplication is applied. The left joins retain
  transactions lacking identity/detail-code metadata, with missing output fields
  exposed for review. This slim export omits account PIDM and transaction number;
  it does not provide a stable source transaction key for automated deduplication.
- Keep raw `Amount`, reversals, transaction descriptions, and reference fields.
  Do not sign-adjust based on charge/payment type without validating the 1305 rule.
- This extract has no hard-coded student, term, account prefix, or ledger filter.
  It includes sponsor activity when its detail code and feed date qualify.
  Save downloads outside version-controlled source files.

### `Current_month_activity.sql`

Returns every transaction whose feed date is on or after the first day of the
current month. `TBBDETC` supplies the description, category, charge/payment
indicator, and priority. The displayed `Balance` is the transaction-level
`TBRACCD_BALANCE`, not a calculated full-account balance.

### `Last_month_activity.sql`

Returns the same transaction detail for the previous calendar month, using a
feed-date range from the first of last month through the start of this month.

### `Current_month_payment_activity.sql`

Returns current-month activity for a maintained list of payment detail codes
plus `CFEE`. `CFEE` is labeled as a credit-card fee rather than a payment.

### `Last_month_payment_activity.sql`

Uses the same payment detail-code list and `CFEE` classification for the
previous calendar month's feed dates.

The query currently uses a hard-coded detail-code list. Before broadening it to
category-based selection, confirm the intended Banner detail-code category and
the special treatment of `CFEE`.

### `Current_month_loan_activity.sql`

Returns selected loan detail codes from a historical feed-date window beginning
two months before the current month and ending at the start of the current
month. Despite the filename, it does not currently return current-month rows.

This query also contains placeholder empty detail codes and groups by the raw
amount before applying `SUM`. Those behaviors are preserved pending business
validation; do not interpret its output as a fully consolidated loan total.

## Run order and validation

1. Run `validate_activity_schema.sql` and resolve every `MISSING` result.
2. Reconcile a small date range to TSAAREV or an authoritative TBRACCD extract.
3. Confirm the payment and loan detail-code lists with the report owner.
4. Confirm whether `FEED_DATE`, rather than entry, effective, or activity date,
   is the intended operational date for each report.
5. Check that current `SPRIDEN` filtering returns one identity row per PIDM.
