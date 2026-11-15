/* Shared CTEs for student check addresses. address_scope supplies pidm/run_date.
   Rank the newest added (highest sequence) current record within each type
   BEFORE testing domestic status; an older domestic PR must not replace a newer
   foreign PR. This is a mailing review, never a change of refund ownership.
   Decision: issue 36, comment 6898592530 and the owner's implementation replies. */
student_address_candidates AS (
    SELECT a.spraddr_pidm AS pidm,
        UPPER(TRIM(a.spraddr_atyp_code)) AS student_address_type,
        NULLIF(TRIM(a.spraddr_street_line1), '') AS student_address_line1,
        NULLIF(TRIM(a.spraddr_street_line2), '') AS student_address_line2,
        NULLIF(TRIM(a.spraddr_street_line3), '') AS student_address_line3,
        NULLIF(TRIM(a.spraddr_city), '') AS student_address_city,
        NULLIF(UPPER(TRIM(a.spraddr_stat_code)), '') AS student_address_state,
        NULLIF(TRIM(a.spraddr_zip), '') AS student_address_zip,
        NULLIF(UPPER(TRIM(a.spraddr_natn_code)), '') AS student_address_nation,
        CASE UPPER(TRIM(a.spraddr_atyp_code))
            WHEN 'PR' THEN 1 WHEN 'TX' THEN 2 WHEN 'MA' THEN 3
            WHEN 'PA' THEN 4 WHEN 'BI' THEN 5 END AS address_priority,
        ROW_NUMBER() OVER (
            PARTITION BY a.spraddr_pidm, UPPER(TRIM(a.spraddr_atyp_code))
            ORDER BY a.spraddr_seqno DESC NULLS LAST,
                a.spraddr_street_line1 NULLS LAST, a.spraddr_street_line2 NULLS LAST,
                a.spraddr_street_line3 NULLS LAST, a.spraddr_city NULLS LAST,
                a.spraddr_stat_code NULLS LAST, a.spraddr_zip NULLS LAST,
                a.spraddr_natn_code NULLS LAST
        ) AS type_rank
    FROM saturn.spraddr a
    INNER JOIN address_scope s ON s.pidm = a.spraddr_pidm
    WHERE UPPER(TRIM(a.spraddr_atyp_code)) IN ('PR', 'TX', 'MA', 'PA', 'BI')
      AND COALESCE(UPPER(TRIM(a.spraddr_status_ind)), 'A') <> 'I'
      AND (a.spraddr_from_date IS NULL OR CAST(a.spraddr_from_date AS date) <= s.run_date)
      AND (a.spraddr_to_date IS NULL OR CAST(a.spraddr_to_date AS date) >= s.run_date)
      AND COALESCE(NULLIF(TRIM(a.spraddr_street_line1), ''),
                   NULLIF(TRIM(a.spraddr_street_line2), ''),
                   NULLIF(TRIM(a.spraddr_street_line3), ''),
                   NULLIF(TRIM(a.spraddr_city), ''),
                   NULLIF(TRIM(a.spraddr_stat_code), ''),
                   NULLIF(TRIM(a.spraddr_zip), ''),
                   NULLIF(TRIM(a.spraddr_natn_code), '')) IS NOT NULL
),
student_address_classified AS (
    SELECT a.*,
        CASE WHEN student_address_nation = 'US' THEN 1
            WHEN student_address_nation IS NULL AND student_address_state IN (
                'AL', 'AK', 'AZ', 'AR', 'CA', 'CO', 'CT', 'DE', 'FL', 'GA',
                'HI', 'ID', 'IL', 'IN', 'IA', 'KS', 'KY', 'LA', 'ME', 'MD',
                'MA', 'MI', 'MN', 'MS', 'MO', 'MT', 'NE', 'NV', 'NH', 'NJ',
                'NM', 'NY', 'NC', 'ND', 'OH', 'OK', 'OR', 'PA', 'RI', 'SC',
                'SD', 'TN', 'TX', 'UT', 'VT', 'VA', 'WA', 'WV', 'WI', 'WY',
                'DC', 'AS', 'GU', 'MP', 'PR', 'VI', 'AA', 'AE', 'AP'
            ) THEN 1 ELSE 0 END AS domestic_ind
    FROM student_address_candidates a
    WHERE type_rank = 1
),
student_address_ranked AS (
    SELECT a.*, ROW_NUMBER() OVER (
        PARTITION BY pidm ORDER BY domestic_ind DESC, address_priority
    ) AS selected_rank
    FROM student_address_classified a
),
student_addresses AS MATERIALIZED (
    SELECT s.pidm,
        a.student_address_type, a.student_address_line1, a.student_address_line2,
        a.student_address_line3, a.student_address_city, a.student_address_state,
        a.student_address_zip, a.student_address_nation,
        CASE WHEN COALESCE(a.domestic_ind, 0) = 0 THEN 'Withhold check refund'
            WHEN a.address_priority > 1 THEN 'UPDATE WORKDAY'
        END AS student_address_review
    FROM address_scope s
    LEFT JOIN student_address_ranked a ON a.pidm = s.pidm AND a.selected_rank = 1
)
