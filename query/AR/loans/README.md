# Institutional-loan enrollment reports

`all_enrollment_load_categories_institutional_loans_summer.sql` is the combined
Summer report. It includes every UG/GR student in the loan population and adds
`Enrollment Load Category` so the three enrollment bands can be filtered in a
single Insights report.

`less_than_half_time_institutional_loans.sql` identifies undergraduate and
graduate students with selected institutional-loan activity who are enrolled
below the applicable half-time credit threshold.

`half_time_less_than_full_time_institutional_loans_summer.sql` returns the same
columns and applies the same loan, student, and contact rules, but selects the
Summer enrollment band from half time through less than full time.

`full_time_and_above_institutional_loans_summer.sql` returns the same columns
and applies the same rules for students meeting or exceeding the Summer
full-time threshold.

## Insights parameter

Configure `target_term` as a required text parameter containing a six-digit
Banner term code. For the original Summer report, use `202655`.

## Population and business rules

- The selected loan detail codes are `PERK`, `CFDN`, `CPAR`, `CCOM`, `CWLC`,
  and `L001`. This preserves the original report population. Other loan codes
  appearing in repository queries were not added without business validation.
- Loan activity and course registration are both restricted to `target_term`.
- Course hours count only registration statuses for which
  `STVRSTS_INCL_SECT_ENRL = 'Y'`.
- `Credit Hours` drives the half-time test. `Billable Hours` is shown separately
  because a dropped course may remain billable even though it no longer counts
  toward enrollment.
- Students with selected loan activity but no enrolled courses are included
  with zero credit hours.
- The less-than-half-time report selects UG students below 6 credits and GR
  students below 4.5 credits.
- The Summer half-time-to-less-than-full-time report selects UG students from
  6 through fewer than 12 credits and GR students from 4.5 through fewer than
  9 credits. Students at exactly 12 UG or 9 GR are excluded.
- The Summer full-time-and-above report selects UG students at 12 or more
  credits and GR students at 9 or more credits.
- The combined Summer report uses those same boundaries and assigns exactly one
  of these values: `Less Than Half Time`, `Half Time but Less Than Full Time`,
  or `Full Time and Above`. It otherwise preserves the same columns and rules.
- The student level and Student Type come from the latest `SGBSTDN` record
  effective on or before `target_term`.
- `Student Information Effective Term` identifies when the displayed Banner
  student level and Student Type became effective. It is not a balance or loan
  transaction term.
- `Returning Student Type Check` avoids an ambiguous `Y/N` flag. Type `X`
  displays `Yes - X (Returning Student)`; every other result starts with `No`
  and displays the actual Banner Student Type, such as `No - C (Continuing)`.
  A blank type displays `No - Student Type is blank`. This remains a Banner
  classification, not evidence of confirmed intent to enroll in a future term.
- Contact columns use one row per student so they do not multiply loan rows.
  The report selects the current `MA` (mailing) address, falling back to the
  current `PR` (permanent) address; active `UNIV` and `PER1` emails; and the
  active primary phone when present, otherwise the highest-sequence active
  phone. Address lines 1-3 are combined in `Street`.

## Where Returning Student comes from

The report does not use a separate "plans to return" checkbox. It uses Banner's
term-effective **Student Type** classification:

- Banner page: `SGASTDN` — General Student
- Location: enter the student ID and applicable term, select **Go**, then view
  the **Learner** tab and locate **Student Type**
- Source field: `SGBSTDN_STYP_CODE`
- Code-description table/page: `STVSTYP`
- Mines codes confirmed during report development: `X` = Returning Student and
  `C` = Continuing

The query selects the latest `SGBSTDN` record effective on or before the report
term. Therefore, the displayed Student Type is the classification applicable to
that term; it is not a current balance attribute or proof that the student has
recently confirmed an intention to enroll.

## Verification fields

- `Total Earned Credit Hours` comes from `SHRLGPA_HOURS_EARNED`. The query uses
  only `SHRLGPA_GPA_TYPE_IND = 'O'` (Overall) and sums the overall rows across
  the student's academic levels. Overall already incorporates the applicable
  institutional and transfer totals, so adding the `I` and `T` component rows
  would double-count earned credits.
- `Expected Graduation Date` comes from `SGBSTDN_EXP_GRAD_DATE` on the same
  term-effective `SGBSTDN` record used for Student Type and level. In Banner,
  it is visible in `SGASTDN` under **Academic and Graduation Status, Dual
  Degree**.

These columns are review cues, not automatic evidence that Student Type is
wrong. Degree-credit requirements vary, and Expected Graduation Date can be
blank or stale. Also, `SHRLGPA` is the student's current cumulative GPA summary,
not a historical snapshot as of `target_term`; a report run for an older term
may therefore show credits earned after that term.

## Amount convention

The query preserves the original report's `SUM(TBRACCD_AMOUNT)` convention and
shows `TBBDETC_TYPE_IND` for review. Before treating the amount as an accounting
signed balance, confirm that the six configured detail codes have the expected
charge/payment type and how reversals are represented locally.

`Detail Code Loan Activity` is the term total for that student's displayed
detail code. The report intentionally does not include a separate all-code
student total or a transaction-count column.

## First-run validation

1. Run `validate_loan_schema.sql` and resolve any missing columns.
2. Confirm locally configured contact types: `MA` mailing address, `PR`
   permanent address, `UNIV` school email, and `PER1` personal email.
3. Run the combined report with `target_term = 202655`; reconcile each category
   to its corresponding standalone report and the complete population to the
   original Summer reporting population.
4. Confirm a dropped or withdrawn course is excluded from enrolled hours.
5. Confirm a dropped but still-billable course appears in billable hours and
   not in enrollment-counting credit hours.
6. Confirm a loan recipient with no registration rows appears with zero hours.
7. Spot-check `X` Student Type rows against `SGASTDN` for the target term.
8. Reconcile `Total Earned Credit Hours` to the Overall totals by level in
   `SHAINST`, and confirm the expected graduation date in `SGASTDN`.
9. Spot-check the selected contact records against `SPAIDEN`/`GOAEMAL`.
10. Reconcile each detail-code amount to `TSAAREV` and confirm the displayed
   detail type before operational use.
