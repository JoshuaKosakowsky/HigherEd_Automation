# Canadian TL11A review

In the GUI, sign in as an Administrator and open **Canadian TL11A Review**.
Enter the student's CWID, calendar tax year, and output location. Each run creates
a new timestamped subfolder, so the same location can be reused for future students.
TEST is the default; select PROD explicitly when authorized to read production
records. Complete the existing Chrome/Insights sign-in if prompted. The GUI
restricts this workflow to Administrators, including when staff policies
explicitly grant its workflow ID. The runner verifies administrator access too.

Each run saves `tl11a_review.xlsx`, raw/prepared CSVs and `manifest.json` together.
Open Summary for proposed paid USD/CAD amounts, Sessions for readable Banner
term labels, dates, credits and program codes, and Checks for unresolved items.
Confirm full-time attendance and a qualifying degree/course in the editable
confirmation columns on Sessions before certifying any form. These cells are
reviewer notes; they do not recalculate or certify the saved financial amounts.
No PDF is filled and no Banner data is changed. Cancellation is checked between
reads and before publication; saving the complete package is a protected step.

## Terminal use on Windows

From the repository root with its configured environment, first inspect schema
metadata without querying a student:

```powershell
.\.venv\Scripts\python.exe -m workflows.canadian_tax.run_tl11a_data --schema-only
```

Review `schema.csv` for `MISSING` fields and `payment_application_columns.csv`.
Then run a student review; `SYNTHETIC001` is a placeholder:

```powershell
.\.venv\Scripts\python.exe -m workflows.canadian_tax.run_tl11a_data --cwid SYNTHETIC001 --tax-year 2025
```

For PROD add `--environment PROD`. On macOS use `python3 -m` with the same module
and arguments. Do not put real CWIDs in shared transcripts or saved examples.
The CLI reuses department Insights authentication and defaults to TEST. GUI
administrator policy applies to the GUI runner; CLI access is controlled by the
existing authorized workstation and Insights credentials.

To rebuild a review from a previously downloaded complete source ZIP, without
connecting to Insights or refreshing its captured exchange rate:

```powershell
.\.venv\Scripts\python.exe -m workflows.canadian_tax.run_tl11a_data --source-package "C:\approved-storage\student-source.zip" --output-dir "C:\approved-storage\new-review"
```

The account/year and environment come from the package. Completeness, account,
schema, registration and transaction keys are validated. Old prepared CSVs are
ignored and rebuilt from raw files. The current configured fee policy is used
and its snapshot recorded in the new manifest. Source application version and
original extraction/rate timestamps remain in the audit record.

## Calculation and review rules

- Exclude FEIT/CFEE only; retain other charge codes under the report owner's
  operational policy. This is not an independent CRA determination of each fee.
- Count positive payment-to-positive-charge allocations to retained charges
  for the requested year's sessions. Scholarships stay in the payment funding.
  Unused payments and unpaid charges are not counted as tuition paid.
- Reapplication `Y` records are omitted only after validating equal
  opposite-direction pairs. Negative charge credits and payment reversals
  reconcile separately; they do not become additional tuition paid.
- Reconcile **every full-history transaction**: amount minus stored balance
  must equal incoming minus outgoing applications for charges, or outgoing
  minus incoming for payments. Missing links, unsupported signs/flags, unmatched
  reapplications or mismatched balances withhold USD/CAD. An older-history
  discrepancy also requires review rather than assuming the current year is safe.
- Courses must be enrolled and last at least 21 inclusive scheduled days.
  Summer is included. Missing/conflicting dates, short/mixed course eligibility,
  cross-year sessions or missing/tied programs withhold totals rather than
  guessing tuition proration. Full-time attendance and degree qualification
  still require administrator confirmation; credit hours alone are not proof.
- Use the Bank of Canada's published `FXAUSDCAD` **annual average**, in CAD per
  USD, verified against the captured annual observation. Multiply the final USD
  total and round CAD to cents, half up. The workbook records the method, source
  URL, CRA guidance URL, rate year and retrieval time.
- Payment effective dates in another year or missing/invalid dates keep USD
  allocations visible but withhold CAD pending appropriate payment-year rate
  review. Payment activity/feed dates are not substituted as payment dates.
  Missing/unpublished/unreachable exchange rates also withhold CAD without a
  fallback. The annual-average method follows CRA guidance for fees paid
  throughout the calendar year.

Financial results are a saved review snapshot, not a live Excel financial
model. Re-run the workflow after correcting source records or configuration.
Sequential Insights reads reflect warehouse data and are not guaranteed to
represent one atomic/live Banner snapshot.

## Audit and storage

The default output is under ignored `data/canadian_tax/`. `--output-dir` selects
a new approved location. Existing directories/workbooks are never overwritten.
A failed write removes only this run's partial directory. Source CSVs preserve
signs, flags, full history and excluded fees. The manifest includes environment,
year, row counts, query hashes for live reads, application version, policy,
amount status, outstanding reviews and the public exchange-rate response.

Generated packages contain student information. Keep them in approved
institutional storage and use redacted or synthetic examples when reporting
GitHub issues. No student data from Downloads is put into tracked code or tests.

See [query sources and business rules](../../query/AR/canadian_tax/README.md)
for Banner mappings and official sources.
