# Collections demographic and academic profile

`collections_student_profile.sql` is the shared source for a native PostgreSQL
Insights question and **Connections → Holds — Collections demographic and
academic profile** in app **0.25.0**. It takes no parameters. The app's existing
administrator restriction, explicit TEST/PROD selection, complete-result check
and new-file Excel export apply. This is a new standalone report; the W&F
reconciliation SQL and workbook contract are unchanged.

Patch **0.25.2** replaces `First Generation` and `First Generation Source` with
`First Generation Admissions` and `First Generation FAFSA`. Update saved
Insights questions with the revised SQL to match the app's two separate indicators.

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
| First generation | Separate Admissions (`FGA`) and FAFSA (`FGF`) indicators. Each is `Yes` only when its code is in the CO term's effective attribute set; otherwise `Unknown`. Raw attribute codes/descriptions and their effective term remain visible. |
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

## First-generation indicators

The owner selected separate Admissions and FAFSA indicators after reviewing
the Mines code-discovery export. There is no combined first-generation flag or
source-precedence rule.

| Output | Code in CO term's effective attribute set | Otherwise |
| --- | --- | --- |
| `First Generation Admissions` | `FGA` → `Yes` | `Unknown` |
| `First Generation FAFSA` | `FGF` → `Yes` | `Unknown` |

The existing attribute selection uses all attributes at the greatest
`SGRSATT_TERM_CODE_EFF` on/before the containing CO term. It does not carry
removed attributes forward forever or use future effective terms. Codes are
trimmed and compared without case sensitivity. Missing dates, ambiguous terms,
no retained attribute rows or an absent code all leave the applicable indicator
`Unknown`. Missing program history does not suppress valid term attributes.

Both codes may be present, producing two `Yes` values. One source's `Yes` does
not establish the other source's status. Neither source returns `No`, because
absence does not prove the student is not first generation. `BLSS` is a
scholarship attribute and is not used for either indicator.

Synthetic examples: FGA only → Yes/Unknown; FGF only → Unknown/Yes;
both → Yes/Yes; neither, missing attributes or BLSS only → Unknown/Unknown.
The order here is Admissions/FAFSA. Counts of students ever carrying FGA and FGF
can overlap and do not establish the code's presence at CO start.

## Local validation

1. Run `validate_collections_profile_schema.sql` in the intended Insights
   database. Investigate every `MISSING` entry before running the main report.
   In particular confirm `SPBPERS_GNDR_CODE` is replicated and available.
2. `inspect_collections_profile_codes.sql` remains a discovery query for the
   attributes used by historical CO students and potential first-generation
   sources. Its distinct-student usage counts are not a snapshot at CO start
   and do not select or combine the report's two indicators.
3. Compare representative authorized records for FGA-only, FGF-only, both,
   neither, and changed effective sets. Confirm that the selected attribute
   term and indicators match Banner's term history. A later correction to a
   source record can still affect a rerun of historical data.

### Aggregate FGA/FGF validation

In patch **0.25.3**, paste the entire
`validate_collections_profile_indicators.sql` into a new native Insights question
and run it without parameters. It returns a **Total** row and the four normal
Admissions/FAFSA combinations, including zero-count combinations. No CWID,
name, PIDM, individual hold date, or student-level attribute list is returned.

The query evaluates an exact embedded copy of the shared report. It separately
reads `SGRSATT` to find the greatest effective attribute term on/before each
reported CO term and uses independent existence checks for FGA/FGF. It compares
those expected indicators and the expected attribute term to the report output.
The checks can detect a wrong source mapping, Yes/Unknown default, invalid
indicator value, or reported attribute effective term. This is a check of the
embedded report SQL; it does not inspect another saved question or a prior
spreadsheet export, and it does not independently validate the CO term's date
mapping or prove the underlying Banner attributes are complete/correct.

- `Admissions Mismatch Rows`, `FAFSA Mismatch Rows`, `Attribute Term Mismatch Rows`
  and `Mismatch Rows` should all be **0** for the unchanged report. A nonzero
  count sets `Validation Status = MISMATCH`. Unexpected values get an additional
  combination row labeled `[INVALID]`, `[BLANK]`, or `[NULL]`. The query never
  repeats unexpected source text, even if a wrong report projection places a
  student identifier in an indicator field.
- `Mismatch Rows` counts each affected report row once even if several checks
  fail. Do not add the three mismatch columns to obtain an affected-row total.
- `Rows Without CO Term` and `Rows With CO Term But No Attribute Set` expose
  missing context. Correct Unknown values are valid and do not create a
  mismatch. `OK` means these indicator/attribute-term checks agree, not that
  missing context has been resolved. A zero-count combination is `NO ROWS`.
- `CO Hold Rows` uses the report's hold-date-pair grain. `Distinct Students`
  counts students within each combination. Students with different historical
  holds can appear in more than one combination, so do not sum distinct-student
  counts across combinations. Discovery-query "ever had this code" counts use
  a different time basis and are not expected to equal these counts.

The validator remains outside the app's report picker, like other diagnostic
SQL files. Student-level lookups occur internally to evaluate the actual report;
only the final aggregate summary is exposed.

When the shared report changes, refresh the marked block rather than maintaining
another report implementation:

```powershell
.\.venv\Scripts\python.exe query/AR/holds/refresh_collections_profile_validation.py --write
```

Run the same command without `--write` to check synchronization. Regression
tests reject a stale embedded block and exercise deliberately corrupted report
flags/effective terms to verify that the summary actually detects mismatches.

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
- Birthdays and multiple races; separate FGA/FGF indicators with either, both,
  neither, duplicate/normalized codes and scholarship-only attributes; removed
  or future attributes and missing/ambiguous terms remain visible as Unknown.
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
