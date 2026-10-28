/*
Collections student profile | read-only Banner Insights / PostgreSQL.
All retained CO holds, including ended, future and undated holds. One row per
PIDM / calendar from-date / calendar to-date; exact duplicates are counted.
CO From Date is a hold-date proxy, not a verified agency placement date.
The academic context is the term CONTAINING that date. Gaps/overlaps remain
visible; an ambiguous term never supplies academic values.
Current demographic/registration records and later term outcomes are not
immutable snapshots. See collections_student_profile_README.md before analysis.
Run validate_collections_profile_schema.sql and inspect_collections_profile_codes.sql.
*/
WITH
params AS (
    SELECT CURRENT_DATE AS report_date
),
/* Populate ONLY after the owner verifies local SGRSATT codes and meaning.
   Replace the empty SELECT with VALUES ('verified_code', 'Yes' or 'No').
   No matching attribute means Unknown, never an inferred No. */
first_generation_codes (attribute_code, first_generation_status) AS (
    SELECT CAST(NULL AS varchar(8)), CAST(NULL AS varchar(3)) WHERE 1 = 0
),
hold_dates AS (
    SELECT h.sprhold_pidm AS pidm,
        CAST(h.sprhold_from_date AS date) AS from_date,
        CAST(h.sprhold_to_date AS date) AS to_date,
        COUNT(*) AS source_hold_rows
    FROM saturn.sprhold h
    WHERE UPPER(TRIM(h.sprhold_hldd_code)) = 'CO'
    GROUP BY h.sprhold_pidm, CAST(h.sprhold_from_date AS date),
        CAST(h.sprhold_to_date AS date)
),
holds AS (
    SELECT h.*, ROW_NUMBER() OVER (
        PARTITION BY pidm ORDER BY from_date NULLS LAST, to_date NULLS LAST
    ) AS co_hold_number,
        COUNT(*) OVER (PARTITION BY pidm) AS student_co_hold_count
    FROM hold_dates h
),
population AS (
    SELECT DISTINCT pidm FROM holds
),
identities AS (
    SELECT s.*, COUNT(*) OVER (PARTITION BY s.spriden_pidm) AS identity_count,
        ROW_NUMBER() OVER (PARTITION BY s.spriden_pidm
            ORDER BY s.spriden_id, s.spriden_last_name, s.spriden_first_name) AS identity_rank
    FROM saturn.spriden s
    INNER JOIN population p ON p.pidm = s.spriden_pidm
    WHERE s.spriden_change_ind IS NULL
),
terms AS (
    SELECT t.stvterm_code AS term_code, t.stvterm_desc AS term_description,
        CAST(t.stvterm_start_date AS date) AS start_date,
        CAST(t.stvterm_end_date AS date) AS end_date
    FROM saturn.stvterm t
    WHERE t.stvterm_start_date IS NOT NULL AND t.stvterm_end_date IS NOT NULL
      AND t.stvterm_end_date >= t.stvterm_start_date
),
term_matches AS (
    SELECT h.pidm, h.co_hold_number, COUNT(t.term_code) AS term_match_count,
        MIN(t.term_code) AS matched_term
    FROM holds h
    LEFT JOIN terms t ON h.from_date BETWEEN t.start_date AND t.end_date
    GROUP BY h.pidm, h.co_hold_number
),
hold_terms AS (
    SELECT h.*, m.term_match_count, t.term_code, t.term_description,
        t.start_date AS term_start_date, t.end_date AS term_end_date
    FROM holds h
    INNER JOIN term_matches m ON m.pidm = h.pidm AND m.co_hold_number = h.co_hold_number
    LEFT JOIN terms t ON t.term_code = m.matched_term AND m.term_match_count = 1
),
student_candidates AS (
    SELECT h.pidm, h.co_hold_number, s.*,
        ROW_NUMBER() OVER (PARTITION BY h.pidm, h.co_hold_number
            ORDER BY s.sgbstdn_term_code_eff DESC) AS student_rank
    FROM hold_terms h
    INNER JOIN saturn.sgbstdn s ON s.sgbstdn_pidm = h.pidm
        AND s.sgbstdn_term_code_eff <= h.term_code
),
student_context AS (
    SELECT * FROM student_candidates WHERE student_rank = 1
),
race_values AS (
    SELECT DISTINCT r.gorprac_pidm AS pidm, r.gorprac_race_cde AS race_code,
        COALESCE(NULLIF(TRIM(d.gorrace_desc), ''), r.gorprac_race_cde) AS race_description
    FROM general.gorprac r
    INNER JOIN population p ON p.pidm = r.gorprac_pidm
    LEFT JOIN general.gorrace d ON d.gorrace_race_cde = r.gorprac_race_cde
    WHERE NULLIF(TRIM(r.gorprac_race_cde), '') IS NOT NULL
),
races AS (
    SELECT pidm, STRING_AGG(race_code, '; ' ORDER BY race_code) AS race_codes,
        STRING_AGG(race_description, '; ' ORDER BY race_code) AS race_descriptions,
        COUNT(*) AS race_count
    FROM race_values GROUP BY pidm
),
attribute_terms AS (
    SELECT h.pidm, h.co_hold_number, MAX(a.sgrsatt_term_code_eff) AS attribute_term
    FROM hold_terms h
    LEFT JOIN saturn.sgrsatt a ON a.sgrsatt_pidm = h.pidm
        AND a.sgrsatt_term_code_eff <= h.term_code
    GROUP BY h.pidm, h.co_hold_number
),
attribute_values AS (
    SELECT DISTINCT t.pidm, t.co_hold_number, t.attribute_term,
        a.sgrsatt_atts_code AS attribute_code,
        COALESCE(NULLIF(TRIM(d.stvatts_desc), ''), a.sgrsatt_atts_code) AS attribute_description
    FROM attribute_terms t
    INNER JOIN saturn.sgrsatt a ON a.sgrsatt_pidm = t.pidm
        AND a.sgrsatt_term_code_eff = t.attribute_term
    LEFT JOIN saturn.stvatts d ON d.stvatts_code = a.sgrsatt_atts_code
),
attributes AS (
    SELECT a.pidm, a.co_hold_number, MAX(a.attribute_term) AS attribute_term,
        STRING_AGG(a.attribute_code, '; ' ORDER BY a.attribute_code) AS attribute_codes,
        STRING_AGG(a.attribute_description, '; ' ORDER BY a.attribute_code) AS attribute_descriptions,
        CASE WHEN COUNT(DISTINCT f.first_generation_status) = 1
             THEN MIN(f.first_generation_status) ELSE 'Unknown' END AS first_generation,
        COUNT(DISTINCT f.first_generation_status) AS first_generation_matches
    FROM attribute_values a
    LEFT JOIN first_generation_codes f ON f.attribute_code = a.attribute_code
    GROUP BY a.pidm, a.co_hold_number
),
registration AS (
    SELECT r.sfrstcr_pidm AS pidm, r.sfrstcr_term_code AS term_code,
        SUM(CASE WHEN UPPER(TRIM(s.stvrsts_incl_sect_enrl)) = 'Y'
                 THEN r.sfrstcr_credit_hr ELSE 0 END) AS registered_credits,
        SUM(CASE WHEN UPPER(TRIM(s.stvrsts_incl_sect_enrl)) = 'Y'
                 THEN 1 ELSE 0 END) AS counting_courses,
        SUM(CASE WHEN s.stvrsts_code IS NULL
            OR COALESCE(UPPER(TRIM(s.stvrsts_incl_sect_enrl)), '') NOT IN ('Y', 'N')
            OR (UPPER(TRIM(s.stvrsts_incl_sect_enrl)) = 'Y'
                AND (r.sfrstcr_credit_hr IS NULL OR r.sfrstcr_credit_hr < 0))
            THEN 1 ELSE 0 END) AS review_rows
    FROM saturn.sfrstcr r
    INNER JOIN population p ON p.pidm = r.sfrstcr_pidm
    LEFT JOIN saturn.stvrsts s ON s.stvrsts_code = r.sfrstcr_rsts_code
    GROUP BY r.sfrstcr_pidm, r.sfrstcr_term_code
),
/* Aggregate quality points / GPA hours, never averages of term GPAs.
   Level is fixed to the CO-term program, so UG/GR credits cannot mix.
   Academic history without a term-end date makes the reconstruction unknown. */
prior_history AS (
    SELECT h.pidm, h.co_hold_number,
        MAX(CASE WHEN t.end_date < h.from_date THEN t.term_code END) AS through_term,
        SUM(CASE WHEN g.shrtgpa_gpa_type_ind = 'I' THEN g.shrtgpa_quality_points ELSE 0 END) AS quality_points,
        SUM(CASE WHEN g.shrtgpa_gpa_type_ind = 'I' THEN g.shrtgpa_gpa_hours ELSE 0 END) AS gpa_hours,
        SUM(g.shrtgpa_hours_earned) AS earned_credits,
        SUM(CASE WHEN t.term_code IS NULL OR (g.shrtgpa_gpa_type_ind = 'I'
            AND (g.shrtgpa_quality_points IS NULL OR g.shrtgpa_quality_points < 0
              OR g.shrtgpa_gpa_hours IS NULL OR g.shrtgpa_gpa_hours < 0))
            THEN 1 ELSE 0 END) AS gpa_review_rows,
        SUM(CASE WHEN t.term_code IS NULL OR g.shrtgpa_hours_earned IS NULL
            OR g.shrtgpa_hours_earned < 0 THEN 1 ELSE 0 END) AS credit_review_rows
    FROM hold_terms h
    INNER JOIN student_context s ON s.pidm = h.pidm AND s.co_hold_number = h.co_hold_number
    INNER JOIN saturn.shrtgpa g ON g.shrtgpa_pidm = h.pidm
        AND g.shrtgpa_levl_code = s.sgbstdn_levl_code
        AND g.shrtgpa_gpa_type_ind IN ('I', 'T')
    LEFT JOIN terms t ON t.term_code = g.shrtgpa_term_code
    WHERE t.end_date < h.from_date OR t.term_code IS NULL
    GROUP BY h.pidm, h.co_hold_number
),
prior_standing_candidates AS (
    SELECT h.pidm, h.co_hold_number, a.shrttrm_term_code AS standing_term,
        a.shrttrm_astd_code_end_of_term AS standing_code,
        ROW_NUMBER() OVER (PARTITION BY h.pidm, h.co_hold_number
            ORDER BY t.end_date DESC, t.term_code DESC) AS standing_rank
    FROM hold_terms h
    INNER JOIN saturn.shrttrm a ON a.shrttrm_pidm = h.pidm
    INNER JOIN terms t ON t.term_code = a.shrttrm_term_code AND t.end_date < h.from_date
    WHERE h.term_match_count = 1
)
SELECT
    p.report_date AS "Report Date",
    h.pidm AS "Banner PIDM",
    i.spriden_id AS "CWID",
    i.spriden_last_name AS "Last Name",
    i.spriden_first_name AS "First Name",
    CASE WHEN i.identity_count = 1 THEN 'OK' ELSE 'Review current identity' END AS "Identity Review",
    h.co_hold_number AS "CO Hold Number",
    h.student_co_hold_count AS "Student CO Hold Count",
    h.source_hold_rows AS "Source Hold Rows",
    h.from_date AS "CO From Date",
    h.to_date AS "CO To Date",
    CASE WHEN h.from_date IS NULL OR h.to_date IS NULL OR h.to_date < h.from_date THEN 'Unknown'
         WHEN h.from_date <= p.report_date AND h.to_date > p.report_date THEN 'Yes'
         ELSE 'No' END AS "Active CO Hold",
    CASE WHEN h.from_date IS NULL OR h.to_date IS NULL OR h.to_date < h.from_date THEN 'Review dates'
         WHEN h.from_date > p.report_date THEN 'Scheduled'
         WHEN h.to_date <= p.report_date THEN 'Ended' ELSE 'Active' END AS "CO Hold Status",
    CASE WHEN b.spbpers_birth_date IS NOT NULL AND h.from_date >= CAST(b.spbpers_birth_date AS date)
         THEN CAST(EXTRACT(YEAR FROM AGE(h.from_date, CAST(b.spbpers_birth_date AS date))) AS integer)
    END AS "Age at CO Start",
    b.spbpers_sex AS "Current Recorded Sex Code",
    CASE UPPER(TRIM(b.spbpers_sex)) WHEN 'M' THEN 'Male' WHEN 'F' THEN 'Female'
         WHEN 'N' THEN 'Not reported' ELSE b.spbpers_sex END AS "Current Recorded Sex",
    b.spbpers_gndr_code AS "Current Gender Identity Code",
    b.spbpers_ethn_cde AS "Current Ethnicity Code",
    r.race_codes AS "Current Race Codes",
    r.race_descriptions AS "Current Races",
    COALESCE(r.race_count, 0) AS "Current Race Count",
    h.term_code AS "CO Term",
    h.term_description AS "CO Term Description",
    h.term_start_date AS "CO Term Start Date",
    h.term_end_date AS "CO Term End Date",
    h.term_match_count AS "Containing Term Count",
    CASE WHEN h.from_date IS NULL THEN 'Missing CO start date'
         WHEN h.term_match_count = 0 THEN 'No containing term'
         WHEN h.term_match_count > 1 THEN 'Overlapping terms - review'
         WHEN s.pidm IS NULL THEN 'No program effective by CO term' ELSE 'OK' END AS "Academic Context Review",
    s.sgbstdn_term_code_eff AS "Program Effective Term",
    s.sgbstdn_levl_code AS "CO Term Student Level Code",
    l.stvlevl_desc AS "CO Term Student Level",
    s.sgbstdn_styp_code AS "CO Term Student Type Code",
    s.sgbstdn_stst_code AS "CO Term Student Status Code",
    s.sgbstdn_degc_code_1 AS "CO Term Primary Degree Code",
    s.sgbstdn_majr_code_1 AS "CO Term Primary Major Code",
    m.stvmajr_desc AS "CO Term Primary Major",
    s.sgbstdn_majr_code_2 AS "CO Term Secondary Curriculum Major Code",
    m2.stvmajr_desc AS "CO Term Secondary Curriculum Major",
    COALESCE(a.first_generation, 'Unknown') AS "First Generation",
    CASE WHEN NOT EXISTS (SELECT 1 FROM first_generation_codes) THEN 'Local mapping pending'
         WHEN a.first_generation_matches > 1 THEN 'Conflicting mapped attributes'
         WHEN COALESCE(a.first_generation_matches, 0) = 0 THEN 'No verified attribute match'
         ELSE 'Verified attribute mapping' END AS "First Generation Source",
    a.attribute_term AS "Attribute Effective Term",
    a.attribute_codes AS "CO Term Attribute Codes",
    a.attribute_descriptions AS "CO Term Attributes",
    CASE WHEN h.term_code IS NOT NULL AND COALESCE(e.review_rows, 0) = 0
         THEN COALESCE(e.registered_credits, 0) END AS "CO Term Registered Credits",
    CASE WHEN h.term_code IS NOT NULL THEN COALESCE(e.counting_courses, 0) END AS "CO Term Counting Courses",
    CASE WHEN h.term_code IS NULL THEN 'No unambiguous CO term'
         WHEN e.pidm IS NULL THEN 'No retained registration rows'
         WHEN e.review_rows > 0 THEN 'Unknown status or credits - review'
         ELSE 'Current registration record; not a dated snapshot' END AS "Registration Review",
    ph.through_term AS "Prior Academic History Through Term",
    CASE WHEN ph.gpa_review_rows = 0 AND ph.gpa_hours > 0
         THEN ROUND(1.0 * ph.quality_points / ph.gpa_hours, 3) END AS "Reconstructed Institution GPA Before CO",
    CASE WHEN ph.credit_review_rows = 0 THEN ph.earned_credits END AS "Reconstructed Earned Credits Before CO",
    CASE WHEN s.sgbstdn_levl_code = 'GR' THEN 'Graduate'
         WHEN s.sgbstdn_levl_code <> 'UG' OR ph.credit_review_rows IS NULL OR ph.credit_review_rows > 0 THEN 'Unknown'
         WHEN ph.earned_credits < 30 THEN 'Freshman'
         WHEN ph.earned_credits < 60 THEN 'Sophomore'
         WHEN ph.earned_credits < 90 THEN 'Junior' ELSE 'Senior' END AS "Reconstructed Class at CO Start",
    CASE WHEN ph.pidm IS NULL THEN 'No prior level-specific term GPA history'
         WHEN ph.gpa_review_rows > 0 OR ph.credit_review_rows > 0 THEN 'Missing or invalid history - review'
         ELSE 'Term-history reconstruction; verify repeat and transfer treatment' END AS "Prior History Review",
    ps.standing_term AS "Prior Academic Standing Term",
    ps.standing_code AS "Prior Academic Standing Code",
    ast.stvastd_desc AS "Prior Academic Standing",
    tg.shrtgpa_gpa AS "CO Term Institution GPA - Later Outcome",
    cs.shrttrm_astd_code_end_of_term AS "CO Term End Standing Code - Later Outcome",
    ast2.stvastd_desc AS "CO Term End Standing - Later Outcome",
    'Current source records; not an immutable point-in-time snapshot' AS "Historical Data Limitation",
    COUNT(*) OVER () AS "Report Row Count"
FROM hold_terms h
CROSS JOIN params p
LEFT JOIN identities i ON i.spriden_pidm = h.pidm AND i.identity_rank = 1
LEFT JOIN saturn.spbpers b ON b.spbpers_pidm = h.pidm
LEFT JOIN races r ON r.pidm = h.pidm
LEFT JOIN student_context s ON s.pidm = h.pidm AND s.co_hold_number = h.co_hold_number
LEFT JOIN saturn.stvlevl l ON l.stvlevl_code = s.sgbstdn_levl_code
LEFT JOIN saturn.stvmajr m ON m.stvmajr_code = s.sgbstdn_majr_code_1
LEFT JOIN saturn.stvmajr m2 ON m2.stvmajr_code = s.sgbstdn_majr_code_2
LEFT JOIN attributes a ON a.pidm = h.pidm AND a.co_hold_number = h.co_hold_number
LEFT JOIN registration e ON e.pidm = h.pidm AND e.term_code = h.term_code
LEFT JOIN prior_history ph ON ph.pidm = h.pidm AND ph.co_hold_number = h.co_hold_number
LEFT JOIN prior_standing_candidates ps ON ps.pidm = h.pidm
    AND ps.co_hold_number = h.co_hold_number AND ps.standing_rank = 1
LEFT JOIN saturn.stvastd ast ON ast.stvastd_code = ps.standing_code
LEFT JOIN saturn.shrtgpa tg ON tg.shrtgpa_pidm = h.pidm AND tg.shrtgpa_term_code = h.term_code
    AND tg.shrtgpa_levl_code = s.sgbstdn_levl_code AND tg.shrtgpa_gpa_type_ind = 'I'
LEFT JOIN saturn.shrttrm cs ON cs.shrttrm_pidm = h.pidm AND cs.shrttrm_term_code = h.term_code
LEFT JOIN saturn.stvastd ast2 ON ast2.stvastd_code = cs.shrttrm_astd_code_end_of_term
ORDER BY i.spriden_id NULLS LAST, h.pidm, h.co_hold_number;
