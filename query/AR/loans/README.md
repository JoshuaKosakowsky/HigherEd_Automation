# Institutional-loan graduate and leaver review

`institutional_loan_exit_review.sql` is the single source for the saved Insights
question and the application's **Recent graduate and leaver review** export.
Configure `target_term` as a required six-digit **text** parameter, ending in
`10` (Spring), `55` (Summer), or `80` (Fall). The application retains the internal
query ID `loan_all_enrollment`; the three band-specific picker entries have
been replaced by this consolidated report. The four original SQL files remain
unchanged in [archive/](archive/) for comparison until review and owner approval
are complete. They are historical references and are not used by the application.
Do not delete them before that approval. Repoint existing saved Insights questions
to the consolidated source after approval; repository changes do not update
questions already saved in Insights.

The owner classifies this consolidation and correction of existing reporting as
a patch release, **0.17.1** (following the merged 0.17.0 release).

The output remains one row per borrower and selected detail code. A student
with two loan codes has two rows, not two students. The original column names
and order are preserved; evidence and review columns are appended. The meaning
of `Detail Code Loan Activity` changes from the input-term total to **all
available history** for that borrower/code. It is not outstanding principal.

## Current business decisions

Owner decisions in the 2026-10-18 review established these rules. No matching
loan issue or PR was found in the repository's GitHub searches at review time;
there is no separate approval reference to cite. Preserve these decisions in
any subsequent implementation PR rather than inventing an approval history.

- Include `PERK`, `CFDN`, `CPAR`, `CCOM`, `CWLC`, `L001`, and the newly confirmed
  `LEWL`. Do not add `CLTL` from the unrelated activity draft.
- Any available loan activity qualifies, even if the loan was taken in 2022
  and never again. There is no loan-year cutoff or requirement for activity in
  the input term. Retain zero, fully reversed, and negative totals: a refund
  associated with a reversed loan may still require recovery. Do not use these
  amounts to infer an outstanding loan-company balance or settled liability.
- Select recent graduates **and** non-graduate leavers. Recent is a date on or
  after report date minus 365 days, through the report date, inclusive. Exactly
  365 days ago qualifies; 366 days ago and future dates do not. Dates are
  calendar dates, not transaction-update timestamps.
- Use current report date for the 365-day window. The input term selects
  enrollment; it does not move that rolling window. This is a current review
  of a selected term, not a reconstruction of an earlier reporting snapshot.
- Retain recent graduates/recorded withdrawals even when now enrolled again.
  The analyst needs their input-term enrollment to review continuing study.
- Summer absence never establishes a possible stop-out. Summer is optional.
- Classify enrollment strictly by credits, without reduced-registration or
  financial-aid eligibility overrides. All enrollment-counting credits are
  summed, including undergraduate courses taken by a graduate student.

## Qualification evidence

A borrower qualifies through any of the following, displayed together in
`Selection Reason` when multiple reasons apply:

1. **Recent Graduate**: `SHRDGMR_GRAD_DATE` is in the window and its degree
   status joins to `STVDEGS_AWARD_STATUS_IND = 'A'`. Do not assume a local code
   such as AW or DA means awarded, or accept a pending/sought record solely
   because a graduation date is populated. The newest qualifying award is
   selected, with sequence number breaking date ties. Multiple awards cannot
   multiply loan rows. `Graduated Level` is separate from input-term `Level`.
2. **Recorded Withdrawal**: the current `SFBETRM` term header has a status
   configured with `STVESTS_THIRD_PARTY_WD_IND = 'Y'`, in or before the input
   term. Use the latest matching `SFRWDRL_EFF_WDRL_DATE` where present, otherwise
   `SFBETRM_ESTS_DATE`; show the date source. Require that date in the window.
   A past withdrawal record alone cannot override a header now showing a
   non-withdrawal status. Documented Summer withdrawals still qualify.
3. **Possible Stop-Out - Review**: the input is a Fall/Spring term that has
   started, no course has an enrollment-counting status in that term, and
   the student's latest earlier enrolled term ended within the window. That
   prior term may be Summer if the student attended Summer. Its end date is
   explicitly labeled **Last Enrolled Term End - Proxy**, never a confirmed
   withdrawal date or last date of attendance. Missing dates, unknown target
   registration statuses, or a future input term cannot establish a stop-out.
   Zero-credit enrolled courses count as enrollment for this absence test.

These are review candidates, not confirmed instructions to begin repayment.
A possible stop-out can be late-registering, on leave, or attending elsewhere;
this query has no outside-institution enrollment feed. It does not calculate
loan-specific grace periods, repayment start dates, or servicing status.

## Enrollment bands and future Summer updates

`enrollment_thresholds` in the SQL contains separate Spring, Summer, and Fall
rows for UG and GR. All three currently use the same owner-selected boundaries:

| Level | Less Than Half Time | Half Time but Less Than Full Time | Full Time and Above |
| --- | --- | --- | --- |
| UG | credits < 6 | 6 <= credits < 12 | credits >= 12 |
| GR | credits < 4.5 | 4.5 <= credits < 9 | credits >= 9 |

Exactly 6 UG / 4.5 GR meets half time; exactly 12 UG / 9 GR meets full time.
The broad middle band includes three-quarter time. Once the owner confirms a
Summer policy, update only the two `55` rows, the documented policy, and boundary
tests. Do not derive different thresholds solely from a shorter term length.

Only `STVRSTS_INCL_SECT_ENRL = 'Y'` contributes credit hours. Dropped courses
may still contribute to separately reported billable hours. No registrations
means zero credits. Unknown statuses, missing/negative enrolled credits, or an
unconfigured student level produce **Needs Review** rather than a confident
credit category. Missing student/identity/detail metadata does not silently
remove an otherwise qualifying borrower; `Review Notes` flags it and Banner
PIDM allows internal follow-up when the displayed ID is missing.

## Other retained fields

- Level, Student Type, and Expected Graduation Date use the latest `SGBSTDN`
  record effective on/before the input term. Missing level is not inferred
  from an old degree, which could misclassify a borrower in a new program.
- Student Type is on **SGASTDN**, **Learner**, source `SGBSTDN_STYP_CODE`,
  descriptions from `STVSTYP`. Existing labels remain: `X` = Returning Student,
  `C` = Continuing. This does not establish intent to return.
- Expected Graduation Date is on SGASTDN, Academic and Graduation Status,
  Dual Degree. It remains a review cue; it never qualifies a graduate.
- Actual outcomes can be reviewed on **SHADEGR** / **SHADGMQ**; withdrawal
  records on **SFAWDRL**, and term enrollment status on **SFAREGS**. Mines
  access, warehouse availability, and populated fields need local validation.
- `Total Earned Credit Hours` sums `SHRLGPA` Overall (`O`) rows across levels,
  without adding the institutional/transfer component rows. It is current,
  not a historical snapshot or proof of degree completion.
- Contacts retain current MA then PR address, active UNIV/PER1 emails, and
  primary active phone then highest sequence. Address lines 1-3 form Street.
  Contact joins remain optional and ranked before joining, preventing fanout.
  Contacts are current at run time, not as of an earlier input term.
- Raw `SUM(TBRACCD_AMOUNT)` and `Detail Type` are preserved. Reconcile signs
  and reversals in TSAAREV before interpreting financial meaning.

## Synthetic acceptance examples

| Example | Expected result |
| --- | --- |
| 2022 LEWL only; awarded 30 days ago; no input-term courses | Included; Recent Graduate; zero credits |
| Loan +100 and reversal -100; awarded 30 days ago | Included with zero historical activity total |
| Award exactly 365 days ago / 366 days ago | First qualifies by graduation; second does not |
| Pending outcome with a recent expected/graduation date | Does not qualify by graduation |
| UG 6 / 12 credits; GR 4.5 / 9 credits | Half time / full time at the exact boundaries |
| Graduate with 4.6 credits | Middle band; no gap above the half-time boundary |
| Recent award; registered in a new graduate program | Retained; awarded and enrollment levels remain separate |
| Current withdrawal status; effective date 20 days ago | Included; date/source displayed |
| Old withdrawal row but term header now non-withdrawal | Does not qualify by withdrawal |
| No Fall courses; last enrolled term ended 100 days ago | Possible Stop-Out - Review after Fall begins |
| Same prior enrollment, no Summer courses | No inferred stop-out |
| Missing credits in an active course | Needs Review; not inferred absent |
| Two degrees and two loan codes | Two rows, not four |

Other reasons can independently retain a borrower who does not qualify through
one example's tested path. For example, an old graduate may still have a recent
withdrawal or qualify as a possible stop-out.

## First-run verification and delivery

1. Run `validate_loan_schema.sql`; resolve every MISSING column before running
   the report. The new degree/withdrawal sources have not yet been validated
   against the live Mines warehouse.
2. Run `validate_loan_statuses.sql`. Confirm local awarded indicators and
   third-party withdrawal indicators with the Registrar. Do not substitute
   assumed status codes or use financial-aid processing flags as proof of exit.
3. Confirm term start/end dates in STVTERM and registration inclusion settings.
4. Reconcile synthetic-style cases above to SHADEGR, SFAWDRL/SFAREGS, SGASTDN,
   and TSAAREV, including older loans, reversals and continued enrollment.
5. Confirm MA/PR, UNIV/PER1 and phone selection locally. Review missing contacts
   before sending information to the loan company.
6. Publish one saved Insights question in an approved staff collection and
   retire its old band-specific questions. The same source runs through the
   application's existing Connections exporter; no independent SQL copy is
   needed. `__loan_row_count` is an internal completeness column: hide it in
   Insights. The application checks it and removes it before saving Excel;
   capped/incomplete results fail without saving a workbook.

Staff procedures and the manual fallback belong in the office's approved Word
SOP. This technical README does not deliver or replace that SOP. No question
publication, student transmission, live verification, or SOP change is performed
by editing this repository.

## Source references

- [Mines Financial Aid credit requirements](https://finaid.mines.edu/credit-requirements/)
- [Mines Summer Financial Aid](https://finaid.mines.edu/summer/)
- [Banner SHRDGMR metadata](https://odsmetadata.wm.edu/ODST/SHRDGMR_source.html)
- [Banner STVDEGS awarded indicator metadata](https://banner-dev.wccnet.edu/InsightsMetadata/banner_metadata/STVDEGSsource.html)
- [Vendor Academic History workbook, awarded/pending indicators](https://fhdafiles.fhda.edu/downloads/eisDocs/STAcademicHistory81WB.pdf)
- [Banner SFRWDRL metadata](https://redirect.oakland.edu/uts/autodocs/ods/SFRWDRL_COMP_source.html)
- [Vendor Student User Guide, third-party withdrawal reporting](https://www.muw.edu/images/docs/office_finance_administration/its/banner_guides/student80500u.pdf)

Vendor/other-institution metadata supports the source design; it does not prove
that Mines exposes or maintains those fields identically. Validate locally.
