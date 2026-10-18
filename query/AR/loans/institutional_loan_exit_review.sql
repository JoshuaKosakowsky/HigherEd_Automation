/*
Institutional-loan graduate and leaver review | Banner Insights

One row per borrower/detail code. The input term selects enrollment only.
All available loan history is retained, including net-zero and negative totals.
Recent means an event/proxy date from CURRENT_DATE - 365 days through today.
Summer absence never establishes a stop-out. This is an analyst review report,
not an outstanding-principal calculation or an instruction to begin repayment.
Run validate_loan_schema.sql and the local status inventory before first use.
*/
WITH
params AS (
    SELECT CAST({{target_term}} AS varchar(6)) AS target_term,
        CURRENT_DATE AS report_date,
        CURRENT_DATE - INTERVAL '365 days' AS window_start
),
/* Separate Summer rows permit a later policy change without changing CASEs. */
enrollment_thresholds (term_suffix, student_level, half_time, full_time) AS (
    VALUES
        ('10', 'UG', 6.0, 12.0),
        ('80', 'UG', 6.0, 12.0),
        ('55', 'UG', 6.0, 12.0),
        ('10', 'GR', 4.5, 9.0),
        ('80', 'GR', 4.5, 9.0),
        ('55', 'GR', 4.5, 9.0)
),
contact_type_codes AS (
    SELECT 'MA'::varchar(2) AS mailing_address_type,
        'PR'::varchar(2) AS permanent_address_type,
        'UNIV'::varchar(4) AS school_email_type,
        'PER1'::varchar(4) AS personal_email_type
),
institutional_loan_codes (detail_code) AS (
    VALUES ('PERK'), ('CFDN'), ('CPAR'), ('CCOM'), ('CWLC'), ('L001'), ('LEWL')
),
loan_activity AS (
    SELECT t.tbraccd_pidm AS pidm, t.tbraccd_detail_code AS detail_code,
        ROUND(SUM(COALESCE(t.tbraccd_amount, 0)), 2) AS detail_code_amount,
        MAX(t.tbraccd_activity_date) AS last_loan_activity_date
    FROM taismgr.tbraccd t
    INNER JOIN institutional_loan_codes code
        ON code.detail_code = t.tbraccd_detail_code
    GROUP BY t.tbraccd_pidm, t.tbraccd_detail_code
),
loan_population AS (
    SELECT DISTINCT pidm FROM loan_activity
),
/* Count actual enrollment rows separately from credits, including zero-credit
   courses. Unknown statuses/credit values must not imply a confirmed absence. */
registration_by_term AS (
    SELECT r.sfrstcr_pidm AS pidm, r.sfrstcr_term_code AS term_code,
        SUM(CASE WHEN UPPER(TRIM(status.stvrsts_incl_sect_enrl)) = 'Y'
            THEN COALESCE(r.sfrstcr_credit_hr, 0) ELSE 0 END) AS credit_hours,
        SUM(COALESCE(r.sfrstcr_bill_hr, 0)) AS billable_hours,
        SUM(CASE WHEN UPPER(TRIM(status.stvrsts_incl_sect_enrl)) = 'Y'
            THEN 1 ELSE 0 END) AS enrolled_course_count,
        SUM(CASE WHEN status.stvrsts_code IS NULL
            OR COALESCE(UPPER(TRIM(status.stvrsts_incl_sect_enrl)), '') NOT IN ('Y', 'N')
            OR (UPPER(TRIM(status.stvrsts_incl_sect_enrl)) = 'Y'
                AND (r.sfrstcr_credit_hr IS NULL OR r.sfrstcr_credit_hr < 0))
            THEN 1 ELSE 0 END) AS enrollment_review_count
    FROM saturn.sfrstcr r
    INNER JOIN loan_population population ON population.pidm = r.sfrstcr_pidm
    LEFT JOIN saturn.stvrsts status ON status.stvrsts_code = r.sfrstcr_rsts_code
    GROUP BY r.sfrstcr_pidm, r.sfrstcr_term_code
),
registration_hours AS (
    SELECT hours.* FROM registration_by_term hours
    CROSS JOIN params p WHERE hours.term_code = p.target_term
),
/* Use the configured awarded indicator, not an assumed local status code.
   Only the most recent qualifying outcome is joined, avoiding degree fanout. */
graduation_candidates AS (
    SELECT g.shrdgmr_pidm AS pidm, g.shrdgmr_grad_date AS graduation_date,
        g.shrdgmr_degc_code AS degree_code, g.shrdgmr_levl_code AS graduated_level,
        g.shrdgmr_degs_code AS degree_status,
        ROW_NUMBER() OVER (PARTITION BY g.shrdgmr_pidm
            ORDER BY g.shrdgmr_grad_date DESC, g.shrdgmr_seq_no DESC) AS graduation_rank
    FROM saturn.shrdgmr g
    INNER JOIN loan_population population ON population.pidm = g.shrdgmr_pidm
    INNER JOIN saturn.stvdegs status ON status.stvdegs_code = g.shrdgmr_degs_code
    CROSS JOIN params p
    WHERE UPPER(TRIM(status.stvdegs_award_status_ind)) = 'A'
      AND CAST(g.shrdgmr_grad_date AS date) >= p.window_start
      AND CAST(g.shrdgmr_grad_date AS date) <= p.report_date
),
/* A stale withdrawal record cannot override a term header that is no longer
   configured for third-party withdrawal reporting. */
withdrawal_records AS (
    SELECT w.*,
        ROW_NUMBER() OVER (PARTITION BY w.sfrwdrl_pidm, w.sfrwdrl_term_code
            ORDER BY w.sfrwdrl_seq_no DESC) AS withdrawal_record_rank
    FROM saturn.sfrwdrl w
    INNER JOIN loan_population population ON population.pidm = w.sfrwdrl_pidm
),
withdrawal_candidates AS (
    SELECT e.sfbetrm_pidm AS pidm, e.sfbetrm_term_code AS withdrawal_term,
        COALESCE(w.sfrwdrl_eff_wdrl_date, e.sfbetrm_ests_date) AS withdrawal_date,
        CASE WHEN w.sfrwdrl_eff_wdrl_date IS NOT NULL THEN 'SFAWDRL effective date'
            ELSE 'SFAREGS enrollment status date' END AS withdrawal_date_source,
        ROW_NUMBER() OVER (PARTITION BY e.sfbetrm_pidm
            ORDER BY COALESCE(w.sfrwdrl_eff_wdrl_date, e.sfbetrm_ests_date) DESC,
                e.sfbetrm_term_code DESC) AS withdrawal_rank
    FROM saturn.sfbetrm e
    INNER JOIN loan_population population ON population.pidm = e.sfbetrm_pidm
    INNER JOIN saturn.stvests status ON status.stvests_code = e.sfbetrm_ests_code
    LEFT JOIN withdrawal_records w ON w.sfrwdrl_pidm = e.sfbetrm_pidm
        AND w.sfrwdrl_term_code = e.sfbetrm_term_code
        AND w.sfrwdrl_ests_code = e.sfbetrm_ests_code
        AND w.withdrawal_record_rank = 1
    CROSS JOIN params p
    WHERE UPPER(TRIM(status.stvests_third_party_wd_ind)) = 'Y'
      AND CAST(COALESCE(w.sfrwdrl_eff_wdrl_date, e.sfbetrm_ests_date) AS date) >= p.window_start
      AND CAST(COALESCE(w.sfrwdrl_eff_wdrl_date, e.sfbetrm_ests_date) AS date) <= p.report_date
      AND e.sfbetrm_term_code <= p.target_term
),
/* Last enrolled term end is a proxy, never a claimed last-attendance date.
   Include Summer attendance as evidence, but never infer a Summer absence. */
last_enrollment_candidates AS (
    SELECT hours.pidm, hours.term_code AS last_enrolled_term,
        term.stvterm_end_date AS last_enrolled_term_end,
        ROW_NUMBER() OVER (PARTITION BY hours.pidm
            ORDER BY hours.term_code DESC) AS enrollment_rank
    FROM registration_by_term hours
    LEFT JOIN saturn.stvterm term ON term.stvterm_code = hours.term_code
    CROSS JOIN params p
    WHERE hours.enrolled_course_count > 0 AND hours.term_code < p.target_term
),
cohort AS (
    SELECT population.pidm, grad.graduation_date, grad.degree_code,
        grad.graduated_level, grad.degree_status,
        withdrawal.withdrawal_date, withdrawal.withdrawal_term,
        withdrawal.withdrawal_date_source,
        prior.last_enrolled_term, prior.last_enrolled_term_end,
        CASE WHEN SUBSTR(p.target_term, 5, 2) IN ('10', '80')
            AND CAST(target.stvterm_start_date AS date) <= p.report_date
            AND COALESCE(hours.enrolled_course_count, 0) = 0
            AND COALESCE(hours.enrollment_review_count, 0) = 0
            AND CAST(prior.last_enrolled_term_end AS date) >= p.window_start
            AND CAST(prior.last_enrolled_term_end AS date) <= p.report_date
            THEN 1 ELSE 0 END AS possible_stop_out
    FROM loan_population population
    CROSS JOIN params p
    LEFT JOIN graduation_candidates grad ON grad.pidm = population.pidm
        AND grad.graduation_rank = 1
    LEFT JOIN withdrawal_candidates withdrawal ON withdrawal.pidm = population.pidm
        AND withdrawal.withdrawal_rank = 1
    LEFT JOIN last_enrollment_candidates prior ON prior.pidm = population.pidm
        AND prior.enrollment_rank = 1
    LEFT JOIN registration_hours hours ON hours.pidm = population.pidm
    LEFT JOIN saturn.stvterm target ON target.stvterm_code = p.target_term
),
review_population AS (
    SELECT * FROM cohort
    WHERE graduation_date IS NOT NULL OR withdrawal_date IS NOT NULL
        OR possible_stop_out = 1
),
/*
SHRLGPA type O is the overall earned total for a student level. Sum those rows
across levels to show all earned credits without also adding the component
Institutional (I) and Transfer (T) rows.
*/
accumulated_earned_credits AS (
    SELECT
        g.shrlgpa_pidm AS pidm,
        SUM(COALESCE(g.shrlgpa_hours_earned, 0)) AS total_earned_credit_hours
    FROM saturn.shrlgpa g
    INNER JOIN review_population population
        ON population.pidm = g.shrlgpa_pidm
    WHERE g.shrlgpa_gpa_type_ind = 'O'
    GROUP BY
        g.shrlgpa_pidm
),

/*
Student Type is maintained in Banner on SGASTDN (General Student), Learner tab.
Its source field is SGBSTDN_STYP_CODE; STVSTYP supplies the code descriptions.
At Mines, X = Returning Student and C = Continuing. This is a term-effective
student classification, not a separate checkbox confirming intent to return.
*/
student_record_candidates AS (
    SELECT
        s.sgbstdn_pidm AS pidm,
        s.sgbstdn_term_code_eff AS effective_term,
        s.sgbstdn_levl_code AS student_level,
        s.sgbstdn_styp_code AS student_type_code,
        s.sgbstdn_exp_grad_date AS expected_graduation_date,
        ROW_NUMBER() OVER (
            PARTITION BY s.sgbstdn_pidm
            ORDER BY s.sgbstdn_term_code_eff DESC
        ) AS record_rank
    FROM saturn.sgbstdn s
    INNER JOIN review_population population
        ON population.pidm = s.sgbstdn_pidm
    CROSS JOIN params p
    WHERE s.sgbstdn_term_code_eff <= p.target_term
),

current_identity AS (
    SELECT
        i.spriden_pidm AS pidm,
        i.spriden_id AS cwid,
        i.spriden_last_name AS last_name,
        i.spriden_first_name AS first_name
    FROM saturn.spriden i
    WHERE i.spriden_change_ind IS NULL
),

/* Prefer a current mailing address, with current permanent address as fallback. */
address_candidates AS (
    SELECT
        a.spraddr_pidm AS pidm,
        CONCAT_WS(
            ', ',
            NULLIF(BTRIM(a.spraddr_street_line1), ''),
            NULLIF(BTRIM(a.spraddr_street_line2), ''),
            NULLIF(BTRIM(a.spraddr_street_line3), '')
        ) AS street,
        a.spraddr_city AS city,
        a.spraddr_stat_code AS state,
        a.spraddr_zip AS zip,
        ROW_NUMBER() OVER (
            PARTITION BY a.spraddr_pidm
            ORDER BY
                CASE
                    WHEN a.spraddr_atyp_code = types.mailing_address_type THEN 1
                    ELSE 2
                END,
                a.spraddr_from_date DESC NULLS LAST,
                a.spraddr_seqno DESC
        ) AS address_rank
    FROM saturn.spraddr a
    INNER JOIN review_population population
        ON population.pidm = a.spraddr_pidm
    CROSS JOIN contact_type_codes types
    WHERE a.spraddr_atyp_code IN (
            types.mailing_address_type,
            types.permanent_address_type
        )
      AND COALESCE(UPPER(BTRIM(a.spraddr_status_ind)), 'A') <> 'I'
      AND (a.spraddr_from_date IS NULL OR a.spraddr_from_date <= CURRENT_DATE)
      AND (a.spraddr_to_date IS NULL OR a.spraddr_to_date >= CURRENT_DATE)
),

email_candidates AS (
    SELECT
        e.goremal_pidm AS pidm,
        e.goremal_emal_code AS email_type,
        e.goremal_email_address AS email_address,
        ROW_NUMBER() OVER (
            PARTITION BY e.goremal_pidm, e.goremal_emal_code
            ORDER BY
                CASE WHEN e.goremal_preferred_ind = 'Y' THEN 1 ELSE 2 END,
                e.goremal_activity_date DESC,
                e.goremal_email_address
        ) AS email_rank
    FROM general.goremal e
    INNER JOIN review_population population
        ON population.pidm = e.goremal_pidm
    CROSS JOIN contact_type_codes types
    WHERE e.goremal_emal_code IN (
            types.school_email_type,
            types.personal_email_type
        )
      AND e.goremal_status_ind = 'A'
),

contact_emails AS (
    SELECT
        email.pidm,
        MAX(email.email_address) FILTER (
            WHERE email.email_type = types.school_email_type
              AND email.email_rank = 1
        ) AS school_email,
        MAX(email.email_address) FILTER (
            WHERE email.email_type = types.personal_email_type
              AND email.email_rank = 1
        ) AS personal_email
    FROM email_candidates email
    CROSS JOIN contact_type_codes types
    GROUP BY
        email.pidm
),

phone_candidates AS (
    SELECT
        phone.sprtele_pidm AS pidm,
        CONCAT(
            CASE
                WHEN NULLIF(BTRIM(phone.sprtele_phone_area), '') IS NOT NULL
                    THEN '(' || BTRIM(phone.sprtele_phone_area) || ') '
                ELSE ''
            END,
            BTRIM(phone.sprtele_phone_number),
            CASE
                WHEN NULLIF(BTRIM(phone.sprtele_phone_ext), '') IS NOT NULL
                    THEN ' x' || BTRIM(phone.sprtele_phone_ext)
                ELSE ''
            END
        ) AS phone_number,
        ROW_NUMBER() OVER (
            PARTITION BY phone.sprtele_pidm
            ORDER BY
                CASE WHEN phone.sprtele_primary_ind = 'Y' THEN 1 ELSE 2 END,
                phone.sprtele_seqno DESC
        ) AS phone_rank
    FROM saturn.sprtele phone
    INNER JOIN review_population population
        ON population.pidm = phone.sprtele_pidm
    WHERE COALESCE(UPPER(BTRIM(phone.sprtele_status_ind)), 'A') <> 'I'
      AND NULLIF(BTRIM(phone.sprtele_phone_number), '') IS NOT NULL
),

report_rows AS (
    SELECT
        p.target_term,
        p.report_date,
        cohort.pidm,
        cohort.graduation_date, cohort.degree_code, cohort.graduated_level,
        cohort.degree_status, cohort.withdrawal_date, cohort.withdrawal_term,
        cohort.withdrawal_date_source, cohort.last_enrolled_term,
        cohort.last_enrolled_term_end, cohort.possible_stop_out,
        thresholds.half_time, thresholds.full_time,
        CONCAT_WS('; ',
            CASE WHEN cohort.graduation_date IS NOT NULL THEN 'Recent Graduate' END,
            CASE WHEN cohort.withdrawal_date IS NOT NULL THEN 'Recorded Withdrawal' END,
            CASE WHEN cohort.possible_stop_out = 1 THEN 'Possible Stop-Out - Review' END
        ) AS selection_reason,
        CONCAT_WS('; ',
            CASE WHEN identity.cwid IS NULL THEN 'Missing current identity' END,
            CASE WHEN student.pidm IS NULL THEN 'Missing term-effective student record' END,
            CASE WHEN thresholds.student_level IS NULL THEN 'Unconfigured student level' END,
            CASE WHEN COALESCE(hours.enrollment_review_count, 0) > 0
                THEN 'Check registration statuses or credit hours' END,
            CASE WHEN detail.tbbdetc_detail_code IS NULL THEN 'Missing detail-code metadata' END
        ) AS review_notes,
        identity.cwid,
        identity.last_name,
        identity.first_name,
        student.student_level,
        CASE
            WHEN thresholds.student_level IS NULL
              OR COALESCE(hours.enrollment_review_count, 0) > 0
                THEN 'Needs Review'
            WHEN COALESCE(hours.credit_hours, 0) < thresholds.half_time
                THEN 'Less Than Half Time'
            WHEN COALESCE(hours.credit_hours, 0) < thresholds.full_time
                THEN 'Half Time but Less Than Full Time'
            ELSE 'Full Time and Above'
        END AS enrollment_load_category,
        COALESCE(hours.credit_hours, 0) AS credit_hours,
        COALESCE(hours.billable_hours, 0) AS billable_hours,
        student.effective_term AS student_record_effective_term,
        student.student_type_code,
        student_type.stvstyp_desc AS student_type_description,
        CASE
            WHEN student.student_type_code = 'X'
                THEN 'Yes - X (Returning Student)'
            WHEN student.student_type_code IS NULL
                THEN 'No - Student Type is blank'
            ELSE CONCAT(
                'No - ',
                student.student_type_code,
                ' (',
                COALESCE(
                    student_type.stvstyp_desc,
                    'Description unavailable'
                ),
                ')'
            )
        END AS returning_student_type_check,
        COALESCE(earned.total_earned_credit_hours, 0)
            AS total_earned_credit_hours,
        student.expected_graduation_date,
        la.detail_code,
        detail.tbbdetc_desc AS detail_code_description,
        detail.tbbdetc_type_ind AS detail_type,
        la.detail_code_amount,
        la.last_loan_activity_date,
        address.street,
        address.city,
        address.state,
        address.zip,
        email.school_email,
        email.personal_email,
        phone.phone_number
    FROM loan_activity la
    INNER JOIN review_population cohort ON cohort.pidm = la.pidm
    CROSS JOIN params p
    LEFT JOIN current_identity identity
        ON identity.pidm = la.pidm
    LEFT JOIN student_record_candidates student
        ON student.pidm = la.pidm
       AND student.record_rank = 1
    LEFT JOIN registration_hours hours
        ON hours.pidm = la.pidm
    LEFT JOIN accumulated_earned_credits earned
        ON earned.pidm = la.pidm
    LEFT JOIN address_candidates address
        ON address.pidm = la.pidm
       AND address.address_rank = 1
    LEFT JOIN contact_emails email
        ON email.pidm = la.pidm
    LEFT JOIN phone_candidates phone
        ON phone.pidm = la.pidm
       AND phone.phone_rank = 1
    LEFT JOIN saturn.stvstyp student_type
        ON student_type.stvstyp_code = student.student_type_code
    LEFT JOIN taismgr.tbbdetc detail
        ON detail.tbbdetc_detail_code = la.detail_code
    LEFT JOIN enrollment_thresholds thresholds
        ON thresholds.term_suffix = SUBSTR(p.target_term, 5, 2)
       AND thresholds.student_level = student.student_level
)

SELECT
    COUNT(*) OVER () AS __loan_row_count,
    r.target_term AS "Term",
    r.cwid AS "ID",
    r.last_name AS "Last Name",
    r.first_name AS "First Name",
    r.detail_code AS "Detail Code",
    r.detail_code_description AS "Detail Code Description",
    r.detail_code_amount AS "Detail Code Loan Activity",
    r.last_loan_activity_date AS "Last Loan Activity Date",
    r.student_level AS "Level",
    r.enrollment_load_category AS "Enrollment Load Category",
    r.credit_hours AS "Credit Hours",
    r.billable_hours AS "Billable Hours",
    r.student_record_effective_term AS "Student Information Effective Term",
    r.student_type_code AS "Student Type Code",
    r.student_type_description AS "Student Type Description",
    r.returning_student_type_check AS "Returning Student Type Check",
    r.total_earned_credit_hours AS "Total Earned Credit Hours",
    r.expected_graduation_date AS "Expected Graduation Date",
    r.detail_type AS "Detail Type",
    r.street AS "Street",
    r.city AS "City",
    r.state AS "State",
    r.zip AS "Zip",
    r.school_email AS "School Email",
    r.personal_email AS "Personal Email",
    r.phone_number AS "Phone Number",
    r.report_date AS "Report Date",
    r.selection_reason AS "Selection Reason",
    r.graduation_date AS "Graduation Date",
    r.degree_code AS "Awarded Degree Code",
    r.graduated_level AS "Graduated Level",
    r.degree_status AS "Degree Status Code",
    r.withdrawal_date AS "Withdrawal Date",
    r.withdrawal_term AS "Withdrawal Term",
    r.withdrawal_date_source AS "Withdrawal Date Source",
    r.last_enrolled_term AS "Last Enrolled Term",
    r.last_enrolled_term_end AS "Last Enrolled Term End - Proxy",
    r.half_time AS "Half-Time Credit Threshold",
    r.full_time AS "Full-Time Credit Threshold",
    r.review_notes AS "Review Notes",
    r.pidm AS "Banner PIDM"
FROM report_rows r
ORDER BY
    r.last_name,
    r.first_name,
    r.detail_code,
    r.pidm;
