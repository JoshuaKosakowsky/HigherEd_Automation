# Late-fee definition evidence and population verification

Read-only PostgreSQL reports for the app's Insights connection and native Insights
questions. The student review adds identities, financial context, holds and shared
staff-waiver details to stored populations. The supporting diagnostics retrieve
configuration and compare two preserved results by exact population key. None
calculate or post new fees, execute returned Banner SQL, or replace eligibility rules.

Start with `validate_late_fee_schema.sql` in the Insights database being reviewed.
The read-only inventory queries can inspect PROD. Keep the proposed seven-step
versus three-step execution test in **Banner TEST**, using its corresponding
Insights database. PROD results cannot validate a SaaSTest run.

| File | Output and purpose |
| --- | --- |
| `validate_late_fee_schema.sql` | Required columns with FOUND/MISSING and any alternative schemas; needs only `information_schema.columns` |
| `late_fee_student_review.sql` | App report: CWID, names, Mines email, stored scope and dates, current selected-term/account balances, posted LPPF, holds and all-staff waiver ownership |
| `late_fee_selection_headers.sql` | Header descriptions, applications and creators using only GLBSLCT; does not retrieve eligibility rules |
| `late_fee_rules.sql` | Headers, SELECT/FROM clauses and ordered rules for every visible owner of the named selections, plus rules for the applications represented |
| `late_fee_compiled_sql.sql` | Optional compiled SQL chunks and parameter text from GLRCMPL, for checking automatically supplied joins/application rules |
| `late_fee_populations.sql` | Stored member keys, application, creator, run user, source activity dates and raw indicators; includes duplicate counts and missing-population markers |
| `late_fee_waiver_source_check.sql` | Each stored step 6 scope versus all current raw manual-waiver keys, with membership in the same scope's stored step 5; identifies source differences without treating them as approved changes |
| `compare_late_fee_populations.sql` | Summary plus every differing, duplicate or invalid key between two preserved populations |

## Student review from the app

In version **0.29.0**, administrators can use **Connections → Late fees — Student
detail and population verification**. Choose TEST or PROD, enter a six-digit
Banner term (Spring `10`, Summer `55`, Fall `80`), then choose **Run selected query
and save Excel** and a new output filename. This uses the existing Insights API
connection and native-SQL permissions; no saved question or manual SQL upload is
needed. TEST remains the default, and access is rechecked before execution.

The workbook contains all ten named populations, including each staff member's
manual waiver list. Each row is one application/selection/creator/run-user/raw-key
membership. Filter **Application**, **Selection ID**, **Creator ID** and **Run User
ID** to select the actual Banner output being compared. A FINAL list is obtained
by selecting `AR_LATEFEES_FINAL` within that scope. Stored activity dates identify
the available output's age; they are not a job-success record or replica timestamp.
Names and CWIDs make this export suitable for matching the work-laptop roster.
Keep raw keys and scope columns for exact membership comparison.

The report preserves missing/ambiguous identities, invalid keys and repeated
source rows with review flags. Identity joins do not remove stored members. The
latest active UNIV email is selected per PIDM. **Stored Selections For This Run
User** lists each selection with its creator; it does not certify that differently
owned or differently dated extracts are one successful run.

The selected term controls **current financial context**, not which historical
populations are included. Charges and payments use TBBDETC charge/payment types
with reversal signs preserved; net balances are charges minus payments. Account
balances include all terms, and another-term credits are flagged. Missing account
data or invalid amounts/classifications leave affected totals blank. A student
with visible transactions only in another term has zero selected-term activity.
Posted LPPF amounts and remaining LPPF balances cover the selected term, including
reversals. They are not an assessment calculation or proposed fee.

Hold history includes codes and dates. Active-hold context uses a start date on
or before today (NULL start is open), and an end date after today; an unknown end
is not labeled active. This does not replace the unavailable Banner hold rules.
Shared manual-waiver indicators and ownership include **all applications,
creators and staff run users**. A current waiver overlapping an older FINAL is
flagged for date review, not treated as evidence of an incorrect historical fee.

**Amounts repeat across populations and operator scopes. Do not sum the entire
workbook.** The app labels the environment, fetches capped API pages using ordered
row numbers, and checks counts and continuity before saving. It rejects detected
truncation, changed counts, invalid guards and more rows than one Excel sheet can
hold. Internal count/ordinal columns are removed from the delivered workbook.
Pages are separate database reads, so changes that retain the same count can
escape these checks; export while the relevant populations are stable. An empty
report is not proof that a Banner job ran successfully.

The raw query also supports native Insights with a required text parameter
`review_term`; the app renders it automatically. The existing preserved-result
comparison remains the exact two-run evidence report. Enrichment alone cannot
prove fresh **1 → 4 → 7** equivalence or independently reconstruct eligibility.

## Observed TEST and PROD metadata availability

The owner supplied a completed TEST/SaaSTest inventory and a separate PROD
inventory on 2026-11-15. Both contain the original 53 expected fields, with the same
availability: 14 FOUND and 39 MISSING.

The validator now also includes 21 **Student review** fields from SPRIDEN, GOREMAL,
TBRACCD, TBBDETC and SPRHOLD (74 total). The earlier inventories do not validate
those added fields. Their mappings follow existing app reports; the enriched
report still needs a first live run in each intended environment.

| Table | Expected fields found | Queries supported by this metadata |
| --- | --- | --- |
| GENERAL.GLBEXTR | 8 of 8 | Population export, comparison and waiver-source diagnostic |
| GENERAL.GLBSLCT | 6 of 6 | Selection-header export |
| GENERAL.GLRAPPL | 0 of 10 | Full rules extract unavailable |
| GENERAL.GLRSFRM | 0 of 8 | Full rules extract unavailable |
| GENERAL.GLRSLCT | 0 of 12 | Full rules extract unavailable |
| GENERAL.GLRCMPL | 0 of 9 | Compiled SQL extract unavailable |

No alternative schema was reported for the missing fields. This does not
distinguish replication omissions, access restrictions or differently named
fields. It also does not establish that any named population contains rows.

The completed TEST and PROD population and header exports were subsequently
reviewed, along with the PROD waiver-source diagnostic. The PROD diagnostic
reconciled to an independent calculation from the supplied population export.
`late_fee_populations.sql` and `late_fee_selection_headers.sql` need neither the
missing tables nor parameter edits. Review their actual applications, creators
and run users before configuring a comparison. The full `late_fee_rules.sql` and optional
`late_fee_compiled_sql.sql` cannot run against the reported schema as written.

## Running the queries

Resolve MISSING fields for the query being used before running it. Missing
GLRCMPL fields block only the optional compiled-SQL extract. Alternative schemas
require an explicit mapping check; the query does not silently switch sources.
FOUND means a column is visible in metadata, not that its data is populated or
current. Missing tables may be outside the replica or the user's permissions.

For a PROD inventory, run these as separate native SQL questions in PROD:

1. `validate_late_fee_schema.sql` to check that environment's visible fields.
2. `late_fee_populations.sql` and `late_fee_selection_headers.sql`, if GLBEXTR
   and GLBSLCT respectively have their required fields.
3. `late_fee_waiver_source_check.sql` if GLBEXTR has its required fields.
4. `late_fee_rules.sql` and `late_fee_compiled_sql.sql` only if their respective
   required fields are visible. The supplied PROD inventory has the same missing
   rule fields as TEST; check again after any access or replication change.

The inventory queries above need no staff parameter edits or Metabase template tags.
The rules and compiled-SQL inventories preserve each actual application/creator
instead of defaulting to a particular employee. Application rules are included
for applications represented in the named selections' headers or rule metadata.
Missing-definition markers do not assign an assumed owner. Record the selected
Insights database with each export; the SQL does not infer TEST versus PROD.

The population and header exports deliberately include all visible scopes for
the ten named selections. Keep those columns when filtering/exporting. In particular,
the displayed `_6` rule selects the manual waiver list without explicit
application, creator or run-user restrictions. The inventories preserve that
source scope and expose the contributing owners. Keys are internal population keys,
expected to be PIDMs, **not CWIDs**; no identity join can drop missing identities.
The raw system/selection indicators are retained without interpreting them as
eligibility filters.

`Report Row Count` is computed before the client/export row limit. Check it against
the exported data-row count and retain the complete results. Do not use a clipped
grid or truncated SQL cell as complete evidence. Store student-level exports in
an approved restricted location outside this repository. `Extracted At` is query
time; `Source Activity Date` is a row's Banner activity, **not replication time**.

## Existing configuration and proposed TEST comparison

Owner-supplied SaaSTest screenshots on 2026-11-15 show GLBDATAJ parameter sets:

| Set | Selection 1 | Operation / selection 2 | Result |
| --- | --- | --- | --- |
| LATEFEES1 | AR_TERM_BALANCE | MINUS AR_PP,CO,TO,WO_HOLDS | AR_LATEFEES_1 |
| LATEFEES2 | AR_LATEFEES_2 | Standalone extraction | AR_LATEFEES_2 |
| LATEFEES3 | AR_LATEFEES_3 | Standalone extraction | AR_LATEFEES_3 |
| LATEFEES4 | AR_LATEFEES_2 | MINUS AR_LATEFEES_3 | AR_LATEFEES_4 |
| LATEFEES5 | AR_LATEFEES_5 | Standalone extraction | AR_LATEFEES_5 |
| LATEFEES6 | AR_LATEFEES_6 | Standalone extraction | AR_LATEFEES_6 |
| LATEFEES7 | AR_LATEFEES_5 | MINUS AR_LATEFEES_6 | AR_LATEFEES_FINAL |

The commas in `AR_PP,CO,TO,WO_HOLDS` are part of one selection identifier.
`_2` reads saved `_1`, `_5` reads saved `_4`, `_3` selects
`ROBUSDF_VALUE_21 = 'Y'` for `&Aid_Year`, and `_6` reads
`AR_WAIVE_MANUAL_LATEFEES`. The application-level rules are also relevant.

The hypothesis is that submissions **1 → 4 → 7** reproduce the final membership
while retaining every definition, fresh upstream results and the manual waiver
source. Separate review, manual edits, reports or other consumers of standalone
outputs must be evaluated before changing an operational procedure.

The [Ellucian General guide, pages 74–76](https://www.hartford.edu/about/offices-divisions/finance-administration/information-technology-services/banner/files/General/Banner_General_User_Guide_9.3.9_8.10.1.pdf)
describes set operations evaluating definition rules without prior standalone
extractions. It also explains rule-free generated results and definitions that
read their stored members. That documentation motivates this test; it does not
verify the installed Java GLBDATAJ process. Table/column starting points were
checked against the [published Banner population-selection ERD](https://helpdesk.victoriacollege.edu/banner/ERDv7/General/Population_Selection/Population_Selection.pdf),
an older schema reference; the Insights inventory remains necessary.

## What constitutes evidence

For a controlled TEST comparison, preserve the original seven-step FINAL result
under a **distinct selection ID** in Banner TEST, keeping the same application,
creator and run user. Establish that the preserved result contains the exact
original membership before rerunning FINAL. These read-only queries do not
create that copy. If only a prior CSV survives, the SQL comparison cannot read
it directly; use a separately reviewed file comparison. A current FINAL cannot
reconstruct its overwritten predecessor.

Retain both runs' successful job logs/sequence numbers, exact dynamic inputs
(including term, aid year and user), source/definition snapshots and timings.
Confirm the baseline and candidate used the same relevant source data, including
manual waivers, and that the replica has caught up after each run. Reusing an old
extracted result or a still-unrefreshed FINAL can create a misleading match.
Population comparison requires no fee posting.

In `compare_late_fee_populations.sql`, fill `creator_id`, `run_user_id` and
`baseline_selection` in the top CTE, and check the application and candidate. The default
candidate is `AR_LATEFEES_FINAL`. Both selection IDs are compared under the same
application/creator/user. A different run user requires a separate comparison
design because it changes the `&User` input to the wrapper rules.
The creator here identifies the two stored results being compared, not who
maintains their underlying manual-waiver entries. Removing this result scope
would incorrectly combine different operators' populations.

| Comparison Status | Interpretation |
| --- | --- |
| INVALID_PARAMETERS | A scope value is absent, blank or padded; no source rows are compared |
| SAME_POPULATION | Both selectors refer to the same current population; cannot prove two runs |
| INCONCLUSIVE_EMPTY_SIDE | One or both sides have no visible rows; legitimate empty, wrong scope, missing execution and replication delay are not distinguishable here |
| INVALID_KEYS | NULL, blank or non-digit keys are present; inspect exception rows |
| DIFFERENT | At least one exact key occurs on only one side, regardless of total counts |
| DUPLICATE_KEYS_REVIEW | Membership matches but repeated keys require review |
| MATCH_REQUIRES_RUN_EVIDENCE | Nonempty unique keys match exactly; logs, inputs, source stability and replication still require confirmation |

The summary and exception rows also expose duplicate/invalid counts when another
status takes precedence. Keys are compared as stored: no numeric conversion,
whitespace trimming or leading-zero removal hides a difference. This establishes
membership equality only. It does not certify fee amounts, source eligibility,
indicator semantics, posting behavior, runtime improvement or policy correctness.

## Remaining eligibility work

### Shared manual-waiver lists

The owner confirmed on 2026-11-15 that Bursar staff each maintain their own
`AR_WAIVE_MANUAL_LATEFEES` list after obtaining authority to add a student.
The shared waiver source must include entries across staff creators and run
users; restricting it to `JPHOU` would omit other staff members' entries.
For example, if staff A lists `{101, 102}` and staff B lists `{102, 103}`, the
combined source contains `{101, 102, 103}`. Key 102 contributes once to membership,
while the diagnostic retains its two source rows for traceability.

This confirms staff inclusion, not an expiry rule or permission to add anyone.
The source audit continues to include all applications because the displayed
`_6` condition filters only the selection name. Application-level rules and
identity joins still need review before reproducing Banner eligibility in SQL.

### Manual-waiver source differences

`late_fee_waiver_source_check.sql` compares stored `AR_LATEFEES_6` with the
currently visible keys named `AR_WAIVE_MANUAL_LATEFEES` across all applications,
creators and run users. It discovers every visible application/definition-creator/
run-user scope containing stored `_5` or `_6` rows and reports each separately.
The shared source is compared to each scope; older operators' extracts are never
combined. Matching `_5` membership uses that exact scope, not a different
creator's or operator's results. No staff parameter edits are required.
`STORED_EXTRACT_ONLY` and `CURRENT_SOURCE_ONLY` identify keys present on only one
side. `BOTH` means raw key membership matches, not that the waiver is currently
valid. Repeated source rows across staff lists are counted but are not classified
as duplicate eligibility errors. Source application, creator and run-user counts
show how many distinct owners contributed each key. Invalid keys and absence of
both waiver populations are explicit; missing stored step 5 leaves its membership
indicator blank. With a manual source but no stored `_5`/`_6` scope, the report
uses `SOURCE_WITHOUT_STORED_SCOPE` and leaves result ownership blank. No visible
rows cannot distinguish an intentionally empty result from a missing run.

`In Stored Pre-final = Y` marks keys also in stored `_5`, where a waiver-source
difference could affect the final subtraction. This does not calculate a fresh
final result or authorize assessing a fee. The diagnostic intentionally does not
reproduce the unobserved application rules or automatic identity joins. A key
absent from the visible source does not establish deletion, expiry or an error;
different source times and replication visibility still require investigation.

For example, with synthetic stored `_6 = {101, 102}`, raw manual source
`{102, 103}` and stored `_5 = {101, 104}`, key 101 is stored-only and in the
pre-final population; 102 is on both sides; 103 is source-only. This is a source
comparison, not a replacement for the two-run equivalence test.

### Independent eligibility query

The supplied TEST and PROD metadata do not expose the fields needed for the full
rules or compiled-SQL extracts. Obtain the balance/hold definitions and AR_STU rules
from Banner, or resolve access/replication with the database owner, before
building the independent Insights eligibility query. Inspect generated SQL for
automatic joins when available. Header descriptions and saved membership do not
replace those definitions. The description
“balance > $66.59” alone does not establish which balance, terms, dates, signs,
holds or exclusions are actually used. The existing `term_balances_no_au.sql`
report is not a substitute for that missing policy evidence. Staff inclusion is
confirmed above; any waiver expiry and the actual fee-assessment inputs still
need confirmation. No such rules are
guessed or changed in this first version.

## Local verification

`python -m unittest discover -s tests/python -p 'test_late_fee_queries.py'`
executes synthetic fixtures against the actual SQL using SQLite. Only the schema
inventory's display aggregation is adapted from ordered STRING_AGG to
GROUP_CONCAT; BTRIM/TRANSLATE are registered equivalents. No institutional data,
credentials or live Banner/Insights connection is needed.

Acceptance cases include equal sets in different orders; equal counts with
different members; duplicates on both sides; empty/missing populations; self
comparison; scope isolation; invalid/raw keys; old/null activity dates; complete
rule order/parentheses; all visible manual-waiver scopes; and header/population
queries executing without the missing rule tables. Waiver-source cases cover
cross-application/creator/user source rows, separation of stored operator scopes,
unequal sets, missing populations and invalid keys. These tests verify
the report logic, not the institution's replication or GLBDATAJ behavior.

`test_late_fee_student_review.py` executes the actual student-review SQL with
synthetic identities, account transactions, holds and memberships. SQLite adapters
only change aggregate/date syntax and fix today's date. Cases cover reversals,
selected versus other terms, missing/ambiguous identities, duplicate source rows,
unknown financial inputs, all-staff waivers, independent operator scopes and
complete extraction under a smaller API cap. Pagination tests reject missing or
repeated rows, changed counts and invalid guards. `test_gui_insights.py` verifies
term input, administrator enforcement, TEST/PROD dispatch and Excel export.

Only the student review is a new app query-picker entry; the supporting SQL files
remain technical diagnostics. These files are not a staff SOP and do not publish
Insights questions or change production procedures.
