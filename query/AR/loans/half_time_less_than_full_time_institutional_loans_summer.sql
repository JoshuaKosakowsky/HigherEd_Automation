/*
Half Time but Less Than Full Time with Institutional Loans — Summer
Colorado School of Mines | Banner Insights (PostgreSQL-flavored SQL)

PURPOSE
  Find students with selected institutional-loan activity in the requested
  term whose enrolled credit hours are at least half time but below the
  Mines Summer full-time threshold.

BUSINESS RULES
  * TARGET_TERM is a required Insights text parameter such as 202655.
  * Undergraduate students are included from 6 through fewer than 12 credits.
  * Graduate students are included from 4.5 through fewer than 9 credits.
  * These full-time ceilings are the Mines Summer thresholds.
  * Only registration statuses configured to count in section enrollment are
    included in credit hours.
  * Billable hours are reported separately and may remain after a student
    drops a course that no longer counts toward enrollment.
  * Students with selected loan activity and no enrolled credits are retained
    with zero credit hours.
  * Returning Student Type Check explicitly states whether the term-effective
    Banner Student Type is X and shows the actual type behind every No result.
  * Total Earned Credit Hours sums Banner's overall earned-hour totals across
    academic levels. Institutional and transfer GPA rows are not added again.
  * Expected Graduation Date comes from the same term-effective student record
    used for Student Type and level.
  * Loan amounts preserve the source query's raw TBRACCD amount convention.
    The detail type is exposed so the sign treatment can be validated.

OUTPUT GRAIN
  One row per student and selected institutional-loan detail code.
*/

WITH
params AS (
    SELECT CAST({{target_term}} AS varchar(6)) AS target_term
),

/* Confirm these institution-defined contact type codes before first use. */
contact_type_codes AS (
    SELECT
        'MA'::varchar(2) AS mailing_address_type,
        'PR'::varchar(2) AS permanent_address_type,
        'UNIV'::varchar(4) AS school_email_type,
        'PER1'::varchar(4) AS personal_email_type
),

institutional_loan_codes (detail_code) AS (
    VALUES
        ('PERK'),
        ('CFDN'),
        ('CPAR'),
        ('CCOM'),
        ('CWLC'),
        ('L001')
),

/*
Keep enrollment-counting credits separate from Banner billing hours. A dropped
course may retain billable hours without counting toward current enrollment.
*/
registration_hours AS (
    SELECT
        r.sfrstcr_pidm AS pidm,
        SUM(CASE
            WHEN UPPER(TRIM(COALESCE(
                registration_status.stvrsts_incl_sect_enrl,
                'N'
            ))) = 'Y'
                THEN COALESCE(r.sfrstcr_credit_hr, 0)
            ELSE 0
        END) AS credit_hours,
        SUM(COALESCE(r.sfrstcr_bill_hr, 0)) AS billable_hours
    FROM saturn.sfrstcr r
    LEFT JOIN saturn.stvrsts registration_status
        ON registration_status.stvrsts_code = r.sfrstcr_rsts_code
    CROSS JOIN params p
    WHERE r.sfrstcr_term_code = p.target_term
    GROUP BY
        r.sfrstcr_pidm
),

/* Scope loan activity to the same term used for the enrollment test. */
loan_activity AS (
    SELECT
        t.tbraccd_pidm AS pidm,
        t.tbraccd_detail_code AS detail_code,
        ROUND(SUM(COALESCE(t.tbraccd_amount, 0)), 2)
            AS detail_code_amount,
        MAX(t.tbraccd_activity_date) AS last_loan_activity_date
    FROM taismgr.tbraccd t
    INNER JOIN institutional_loan_codes configured_code
        ON configured_code.detail_code = t.tbraccd_detail_code
    CROSS JOIN params p
    WHERE t.tbraccd_term_code = p.target_term
    GROUP BY
        t.tbraccd_pidm,
        t.tbraccd_detail_code
),

loan_population AS (
    SELECT DISTINCT
        la.pidm
    FROM loan_activity la
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
    INNER JOIN loan_population population
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
    INNER JOIN loan_population population
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
    INNER JOIN loan_population population
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
    INNER JOIN loan_population population
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
    INNER JOIN loan_population population
        ON population.pidm = phone.sprtele_pidm
    WHERE COALESCE(UPPER(BTRIM(phone.sprtele_status_ind)), 'A') <> 'I'
      AND NULLIF(BTRIM(phone.sprtele_phone_number), '') IS NOT NULL
),

report_rows AS (
    SELECT
        p.target_term,
        identity.cwid,
        identity.last_name,
        identity.first_name,
        student.student_level,
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
    CROSS JOIN params p
    INNER JOIN current_identity identity
        ON identity.pidm = la.pidm
    INNER JOIN student_record_candidates student
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
    INNER JOIN taismgr.tbbdetc detail
        ON detail.tbbdetc_detail_code = la.detail_code
    WHERE
        (
            student.student_level = 'UG'
            AND COALESCE(hours.credit_hours, 0) >= 6
            AND COALESCE(hours.credit_hours, 0) < 12
        )
        OR
        (
            student.student_level = 'GR'
            AND COALESCE(hours.credit_hours, 0) >= 4.5
            AND COALESCE(hours.credit_hours, 0) < 9
        )
)

SELECT
    r.target_term AS "Term",
    r.cwid AS "ID",
    r.last_name AS "Last Name",
    r.first_name AS "First Name",
    r.detail_code AS "Detail Code",
    r.detail_code_description AS "Detail Code Description",
    r.detail_code_amount AS "Detail Code Loan Activity",
    r.last_loan_activity_date AS "Last Loan Activity Date",
    r.student_level AS "Level",
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
    r.phone_number AS "Phone Number"
FROM report_rows r
ORDER BY
    r.last_name,
    r.first_name,
    r.detail_code;
