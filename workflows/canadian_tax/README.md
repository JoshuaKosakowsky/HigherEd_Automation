# TL11A source-data preparation

This command-line workflow prepares data for one student's Canadian tuition
certificate using existing department Insights authentication. TEST is the
default. PROD must be selected explicitly and used only with authorized access.
No PDF is filled, no Banner data is changed, and no final tuition-paid amount
is calculated in this step. The workflow is not yet in the GUI query picker.

First inspect metadata without querying a student:

```powershell
.\.venv\Scripts\python.exe -m workflows.canadian_tax.run_tl11a_data --schema-only
```

Review `schema.csv` for `MISSING` rows and
`payment_application_columns.csv` for available `TBRAPPL` fields. Resolve schema
differences before trying a student extract.

Then supply the requested CWID and year. `SYNTHETIC001` below is a placeholder:

```powershell
.\.venv\Scripts\python.exe -m workflows.canadian_tax.run_tl11a_data --cwid SYNTHETIC001 --tax-year 2025
```

On macOS, use `python3 -m workflows.canadian_tax.run_tl11a_data` with the same
arguments from the repository root and your configured Python environment.
The same dedicated Chrome/SSO flow and cached department session are reused.
For PROD, add `--environment PROD` explicitly. Do not record real CWIDs in
shared terminal transcripts or saved commands.

Outputs go to a new timestamped directory under ignored `data/canadian_tax/`.
Use `--output-dir` to select a new directory in another approved storage
location. Existing directories are never overwritten. A failed write removes
only the new partial package created by this run.

The package contains raw identity, transactions, enrollment, programs and
payment applications CSVs; prepared transactions with eligibility reasons;
prepared applications linked to their payment and charge transactions;
prepared enrollment with course-duration checks; a detail-code review grouped
by term/code; and the schema/payment-application inventories. Raw financial
amounts and signs are preserved. Prepared transactions add labels without
removing excluded fees. The code review summarizes **all account history**,
not just the requested year. `year_term_candidate` in the transaction files
identifies the requested year's broad candidate scope.

The configured fee policy excludes FEIT/CFEE and retains other charges. This
implements the report owner's direction. Payment applications preserve signed
amounts and direct-payment/reapplication flags. A `linked` application means
both transactions were found with expected payment/charge types; it is not
proof that the row should enter a final tuition-paid total. Missing links and
unexpected types are identified in `application_review_status`.

`enrollment_prepared.csv` includes `scheduled_duration_days` and
`course_duration_status`. The minimum is 21 consecutive days, counting start
and end dates inclusively. Short courses, dropped/non-counting registrations,
and missing/conflicting dates remain visible. Summer is included in the
duration check, consistent with the report owner's confirmation. Duration does
not independently prove full-time attendance.

Rerun the same CWID/year command after updating your work copy. The next
package will include the actual application records; the prior package
contains only their column inventory. Return the new package for reconciliation
of application signs and reapplication behavior before computing paid totals.

`manifest.json` records the application version, selected environment/year,
UTC extraction time, row counts, query hashes, fee-rule snapshot, course-duration
policy, outstanding
reviews, rate/year/direction, CRA and Bank of Canada source links, retrieval
time, and the fetched public rate response. `eligible_paid_usd` and
`eligible_paid_cad` remain null until payment allocation and eligibility are
established. Do not treat a net charge/code amount as tuition paid.

The selected annual rate is a conversion input for later reviewed paid USD
amounts. A missing rate does not prevent retaining the Banner data package;
the manifest explicitly reports it as `not_published` or `unavailable`.
Review payment years before using a tax-year rate for advance or late payments.

The original teaching workbook is unchanged. No student data or workbook from
Downloads is copied into tracked code or tests. Generated packages contain
student information and belong in approved institutional storage; the default
directory is excluded from Git, including JSON manifests.

See [query sources and business rules](../../query/AR/canadian_tax/README.md)
for the mapping, initial fee-rule questions and reconciliation steps.
