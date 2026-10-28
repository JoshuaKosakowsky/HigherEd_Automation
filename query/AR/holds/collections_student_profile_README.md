# Collections demographic and academic profile

`collections_student_profile.sql` is the shared source for a native PostgreSQL
Insights question and **Connections → Holds — Collections demographic and
academic profile** in app **0.25.0**. It takes no parameters. The app's existing
administrator restriction, explicit TEST/PROD selection, complete-result check
and new-file Excel export apply. This is a new standalone report; the W&F
reconciliation SQL and workbook contract are unchanged.

## Population and row meaning

The owner selected **all historical CO holds with an active flag** and the
**term containing the CO start date**. No balance, current enrollment, student
status or program-history requirement removes a CO account. Missing current
identity, demographics and academic history remain visible.

One row represents a PIDM and distinct calendar-date pair (`CO From Date`,
`CO To Date`). Duplicate date pairs collapse with `Source Hold Rows` showing
their source count. Distinct dates remain separate, even for the same person.
`Student CO Hold Count` counts these date pairs, not verified agency placements.
`CO Hold Number` is a chronological display sequence, not a persistent event ID;
use PIDM and the two dates to reconcile an export. Count distinct PIDMs for a
student headcount; summing rows gives the number of retained hold date pairs.
SPRHOLD cannot recover records that were deleted or prior versions overwritten.

`Active CO Hold = Yes` requires from date on/before report date and to date
strictly after report date. A hold ending today is ended; a future start is
scheduled. Missing dates or an end before its start yield `Unknown` and review.
This start-and-end definition belongs to this historical report; the W&F
report retains its existing end-date-only population rule.

`CO From Date` is a proxy for entering collections. It does not establish the
agency's actual referral/placement date. No agency-date or debt-amount inference
is made. The report uses the database's `CURRENT_DATE` for its report date.

## Fields and timing

| Field group | Source and interpretation |
| --- | --- |
| Identity | Current unchanged `SPRIDEN`; missing/multiple identities are flagged. PIDM retains unmatched accounts. |
| Age at CO start | Whole years from `SPBPERS_BIRTH_DATE` to the hold start date, accounting for birthday. Missing/impossible dates stay blank. Full birth date is not exported. |
| Sex and gender | Separate current `SPBPERS_SEX` and `SPBPERS_GNDR_CODE`; the latter is the institution's raw gender identity code, not inferred from sex. Verify local code meanings in GTVGNDR. |
| Race and ethnicity | Current `GENERAL.GORPRAC`/`GORRACE` retain every distinct reported race in ordered lists. `SPBPERS_ETHN_CDE` is retained separately as a raw ethnicity code. No race or ethnicity is inferred from names. |
| Containing term | Inclusive `STVTERM_START_DATE` through `STVTERM_END_DATE`, ignoring time of day. A gap or overlap supplies no term and no program/registration/later term outcomes. No nearest-term fallback. |
| Level, status, degree, major | Latest `SGBSTDN_TERM_CODE_EFF` on/before the containing term. Codes and descriptions expose UG/GR and declared primary/secondary-curriculum majors. `_MAJR_CODE_2` is the secondary curriculum's major, not a second major within the primary curriculum. |
| First generation | Verified local student-attribute mapping only; initially `Unknown` with `Local mapping pending`. Raw effective attribute codes/descriptions are included to support verification. |
| Credit load | `SFRSTCR_CREDIT_HR` summed only for statuses whose `STVRSTS_INCL_SECT_ENRL = Y`. Zero-credit counting courses remain counted. Unknown statuses or missing/negative counting credits make the credit total blank. No retained registration rows produce zero credits with an explicit review message. |
| Prior GPA | Reconstructed institutional quality points divided by institutional GPA hours over terms ending strictly before CO began, at the CO-term student level. Zero GPA hours produce blank GPA. Transfer quality points never enter the institution GPA. |
| Prior earned credits | Sum of institutional and transfer `SHRTGPA_HOURS_EARNED` at that same level, for terms ending before CO. Missing term dates or missing/negative earned credits make the reconstruction unknown. No history is not assumed zero. |
| Class at CO start | UG: below 30 earned credits Freshman, 30–<60 Sophomore, 60–<90 Junior, 90+ Senior. GR is Graduate; other/unknown levels or missing credits are Unknown. This is a reconstruction, not Banner's official class-calculation function. |
| Prior academic standing | Latest completed term's `SHRTTRM_ASTD_CODE_END_OF_TERM` and `STVASTD` description. Its term is shown; a missing standing code stays blank. SHRTTRM standing is keyed by student/term, not student level. |
| Later outcomes | The containing term's institutional GPA and end-of-term academic standing have explicit `Later Outcome` labels. These may have been established after the CO start date. |

Current race, ethnicity, sex, gender and registration rows are **current records**,
including when joined to an older CO term. Term-effective program and attribute
rows may also have been corrected later. Prior GPA/credits are reconstructed
from current term-history records; repeats, forgiveness, transfer posting dates,
pre-Banner totals and later corrections may prevent an exact historical GPA or
classification. A transfer row with no dated term, including a `000000` term,
requires review. No Oracle Banner functions are called in PostgreSQL Insights.

The report labels these limits and retains source terms and review columns.
It is descriptive collections research, not a point-in-time ML training set.
In particular, later outcomes and current demographic values must not be
silently treated as information known before collections. A future prediction
dataset also needs eligible students who did not enter collections and a defined
observation date/outcome window; this CO-only report does not supply those.

## First-generation verification

1. Run `validate_collections_profile_schema.sql` in the intended Insights
   database. Investigate every `MISSING` entry before running the main report.
   In particular confirm `SPBPERS_GNDR_CODE` is replicated and available.
2. Run `inspect_collections_profile_codes.sql`. It lists attributes used by CO
   students and description/code candidates for first generation, with distinct
   student usage counts and no student-level output. A description match is
   evidence to investigate, not a confirmed definition. Mines' actual source
   could instead be an admissions/aid/custom field; absence of candidates does
   not prove no first-generation students.
3. Verify candidate meaning and positive/negative/unknown semantics with the
   local data owner and representative authorized Banner records. Confirm
   SGRSATT history uses effective attribute sets: this report takes all attributes
   at the greatest effective term on/before the containing CO term, rather than
   retaining a removed attribute forever.
4. Once verified, replace the empty SELECT in `first_generation_codes` with
   `VALUES ('verified_code', 'Yes')`, adding a verified `No` code only if one
   exists. Apply the same reviewed source file to Insights and the application.
   No matching code remains `Unknown`; contradictory mapped statuses remain
   `Unknown` with `Conflicting mapped attributes`.

The delivered mapping is intentionally empty because no Mines first-generation
source/code has yet been confirmed. No institution's example FGEN code is
preloaded as a Mines business rule.

## Loading and acceptance checks

Paste the **entire** main SQL into a native Insights question with no template
variables. Save/publish that question through the normal owner process. The app
runs the repository SQL directly; it does not require a saved question ID.
The SQL's internal `Report Row Count` allows the existing app service to reject
truncated results and is removed from the app workbook. It counts hold date
pairs. CO dates preserve calendar dates through year 9999 in Excel. Other
date fields may arrive as ISO date text depending on the Insights API.

Before operational use, compare distinct CO students/date pairs to SOAHOLD;
compare program/major/level to SGASTDN, registration to SFAREGS, standing to
SHAINST and GPA/transfer/classification to the appropriate transcript/history.
Verify local UG/GR codes, ethnicity/gender dictionaries, term boundaries,
SPBPERS uniqueness, reference-table keys and the SHRTGPA PIDM/term/level/type
key. The report assumes these standard table keys; an unexpected duplicate
history/reference row can multiply output and requires correction at source.
No live Mines schema, extraction performance or records were validated by
the synthetic tests.

Synthetic acceptance examples in `test_collections_student_profile.py` cover:

- Ended, ending-today, active, scheduled, undated and reversed-date holds;
  duplicate holds, repeated placements and missing identity retention.
- Exact containing-term start/end boundaries, date gaps and overlaps; future
  program/attribute changes do not replace the CO-term context.
- Birthdays, multiple races, unknown first generation and conflicting mappings.
- Weighted GPA (100 quality points / 30 hours = 3.333), distinct UG/GR history,
  transfer earned credits, null/zero/undated history and all class thresholds.
- Dropped and zero-credit courses, unknown registration statuses and credits;
  separate later GPA/standing outcomes.
- Administrator access, complete/empty/capped results, shared SQL path,
  far-future CO dates and protection of existing export files.

## Source references

- [Mines Registrar classification rules](https://registrar.mines.edu/student-classification/)
  support the 30/60/90 earned-credit thresholds. Historical application and
  transfer/repeat handling still require local confirmation.
- [Mines first-generation support page](https://mep.mines.edu/current-students/first-generation-students/)
  explains that definitions can vary; it does not identify the Banner field.
- [Ellucian Banner metadata: SHRTGPA](https://ods.uvu.edu/metadata/SHRTGPA_ODS_source.html)
  documents term/level GPA hours, quality points and earned-credit fields.
- [Ellucian Banner metadata: SHRTTRM](https://ods.uvu.edu/metadata/SHRTTRM_ODS_source.html)
  documents end-of-term academic standing.
- [Ellucian Banner metadata: gender fields](https://ods.uvu.edu/metadata/CONSTITUENT_ODS_target.html)
  distinguishes recorded sex from gender designation. Local replication and
  dictionaries must be verified rather than inferred from another institution.
