/* Read-only review of active registrations and remaining charge balances.
   Select Fall to check that year's Spring and Summer, or Spring to check the
   previous year's Fall. Source terms refer to charges, wherever the payment
   posted. The remaining charge balance already reflects applied payments.
*/
WITH input AS (
    SELECT TRIM(CAST({{registration_term}} AS text)) AS registration_term
),
params AS (
    SELECT registration_term, SUBSTR(registration_term, 5, 2) AS registration_suffix,
        CASE WHEN registration_term ~ '^[0-9]{4}(10|80)$'
            THEN CAST(SUBSTR(registration_term, 1, 4) AS integer) END AS registration_year
    FROM input
),
term_rules (registration_suffix, debt_suffix, year_offset) AS (
    VALUES ('80', '10', 0), ('80', '55', 0), ('10', '80', -1)
),
debt_terms AS (
    SELECT p.registration_term, m.debt_suffix,
        LPAD(CAST(p.registration_year + m.year_offset AS text), 4, '0') || m.debt_suffix AS debt_term
    FROM params p
    JOIN term_rules m ON m.registration_suffix = p.registration_suffix
    WHERE p.registration_year > 0
),
registered AS (
    SELECT r.sfrstcr_pidm AS pidm, COUNT(DISTINCT r.sfrstcr_crn) AS registered_sections
    FROM saturn.sfrstcr r
    JOIN (SELECT DISTINCT registration_term FROM debt_terms) d
        ON d.registration_term = r.sfrstcr_term_code
    WHERE EXISTS (
        SELECT 1 FROM saturn.stvrsts s
        WHERE s.stvrsts_code = r.sfrstcr_rsts_code
          AND UPPER(TRIM(s.stvrsts_incl_sect_enrl)) = 'Y'
    )
    GROUP BY r.sfrstcr_pidm
),
detail_types AS (
    SELECT tbbdetc_detail_code AS detail_code,
        CASE WHEN COUNT(*) = 1 THEN MAX(UPPER(TRIM(tbbdetc_type_ind))) END AS detail_type
    FROM taismgr.tbbdetc
    GROUP BY tbbdetc_detail_code
),
term_balances AS (
    SELECT r.pidm, dt.registration_term, dt.debt_suffix,
        CASE WHEN COUNT(t.tbraccd_pidm) FILTER (WHERE
                d.detail_type IS NULL OR d.detail_type NOT IN ('C', 'P')
                OR (d.detail_type = 'C' AND t.tbraccd_balance IS NULL)
            ) = 0 THEN GREATEST(0,
                ROUND(COALESCE(SUM(t.tbraccd_balance) FILTER (WHERE d.detail_type = 'C'), 0), 2)
            ) END AS balance_owed
    FROM registered r
    CROSS JOIN debt_terms dt
    LEFT JOIN taismgr.tbraccd t
        ON t.tbraccd_pidm = r.pidm AND t.tbraccd_term_code = dt.debt_term
    LEFT JOIN detail_types d ON d.detail_code = t.tbraccd_detail_code
    GROUP BY r.pidm, dt.registration_term, dt.debt_suffix
),
candidates AS (
    SELECT pidm, registration_term,
        MAX(balance_owed) FILTER (WHERE debt_suffix = '10') AS spring_balance,
        MAX(balance_owed) FILTER (WHERE debt_suffix = '55') AS summer_balance,
        MAX(balance_owed) FILTER (WHERE debt_suffix = '80') AS fall_balance,
        CASE WHEN COUNT(balance_owed) = COUNT(*) THEN SUM(balance_owed) END AS prior_balance_owed,
        COUNT(balance_owed) < COUNT(*) AS balance_needs_review
    FROM term_balances
    GROUP BY pidm, registration_term
    HAVING SUM(balance_owed) > 0 OR COUNT(balance_owed) < COUNT(*)
),
identities AS (
    SELECT s.spriden_pidm AS pidm, s.spriden_id, s.spriden_first_name, s.spriden_last_name,
        COUNT(*) OVER (PARTITION BY s.spriden_pidm) AS identity_count,
        ROW_NUMBER() OVER (PARTITION BY s.spriden_pidm ORDER BY
            NULLIF(TRIM(s.spriden_id), '') NULLS LAST, s.spriden_last_name, s.spriden_first_name
        ) AS identity_rank
    FROM saturn.spriden s
    JOIN candidates c ON c.pidm = s.spriden_pidm
    WHERE s.spriden_change_ind IS NULL
),
active_holds AS (
    SELECT c.pidm,
        STRING_AGG(DISTINCT UPPER(TRIM(h.sprhold_hldd_code)), ', '
            ORDER BY UPPER(TRIM(h.sprhold_hldd_code))) AS hold_codes
    FROM candidates c
    JOIN saturn.sprhold h ON h.sprhold_pidm = c.pidm
    WHERE NULLIF(TRIM(h.sprhold_hldd_code), '') IS NOT NULL
      AND (h.sprhold_from_date IS NULL OR CAST(h.sprhold_from_date AS date) <= CURRENT_DATE)
      AND CAST(h.sprhold_to_date AS date) > CURRENT_DATE
    GROUP BY c.pidm
),
unapplied_payments AS (
    SELECT c.pidm
    FROM candidates c
    WHERE EXISTS (
        SELECT 1
        FROM taismgr.tbraccd t
        JOIN detail_types d ON d.detail_code = t.tbraccd_detail_code
        WHERE t.tbraccd_pidm = c.pidm AND d.detail_type = 'P' AND t.tbraccd_balance < 0
    )
)
SELECT
    s.spriden_id AS "CWID",
    s.spriden_last_name AS "Last Name",
    s.spriden_first_name AS "First Name",
    c.registration_term AS "Registration Term",
    r.registered_sections AS "Registered Sections",
    c.spring_balance AS "Prior Spring Balance",
    c.summer_balance AS "Prior Summer Balance",
    c.fall_balance AS "Prior Fall Balance",
    c.prior_balance_owed AS "Prior Balance Owed",
    h.hold_codes AS "Active Holds",
    CASE WHEN u.pidm IS NOT NULL THEN 'Yes' ELSE 'No' END AS "Unapplied Payment Found",
    NULLIF(TRIM(
        CASE WHEN c.balance_needs_review THEN 'Incomplete prior-term balance. ' ELSE '' END
        || CASE WHEN u.pidm IS NOT NULL THEN 'Verify unapplied payments in Banner. ' ELSE '' END
        || CASE WHEN COALESCE(s.identity_count, 0) <> 1 OR NULLIF(TRIM(s.spriden_id), '') IS NULL
            THEN 'Missing or duplicate current identity. ' ELSE '' END
    ), '') AS "Review Notes",
    COUNT(*) OVER () AS "Report Row Count"
FROM candidates c
JOIN registered r ON r.pidm = c.pidm
LEFT JOIN identities s ON s.pidm = c.pidm AND s.identity_rank = 1
LEFT JOIN active_holds h ON h.pidm = c.pidm
LEFT JOIN unapplied_payments u ON u.pidm = c.pidm
ORDER BY c.prior_balance_owed DESC NULLS LAST, s.spriden_id NULLS LAST, c.pidm;
