/*
MANUAL WEBSITE EXPORT 1 OF 2: REFUND TRANSACTIONS

Run this flat query in Insights and download the complete result as XLSX or CSV.
It performs no refund allocation. Python does that work locally.

Leave target_term_override NULL for the term containing CURRENT_DATE. Set it to
a six-digit Banner term only for an intentional historical/work-ahead run.
Leave cwid_filter NULL for the population, or set it temporarily for one-account
validation. Never commit a populated CWID.
*/
WITH
run_settings AS (
    SELECT
        CURRENT_DATE AS run_date,
        CAST(NULL AS varchar(6)) AS target_term_override,
        CAST(NULL AS varchar(30)) AS cwid_filter
),
params AS (
    SELECT
        CAST(COALESCE(
            target_term_override,
            CONCAT(
                CAST(EXTRACT(YEAR FROM run_date) AS integer),
                CASE
                    WHEN run_date <= MAKE_DATE(
                        CAST(EXTRACT(YEAR FROM run_date) AS integer), 5, 15
                    ) THEN '10'
                    WHEN run_date <= MAKE_DATE(
                        CAST(EXTRACT(YEAR FROM run_date) AS integer), 7, 15
                    ) THEN '55'
                    ELSE '80'
                END
            )
        ) AS varchar(6)) AS target_term,
        cwid_filter
    FROM run_settings
),
refund_scope AS MATERIALIZED (
    SELECT t.tbraccd_pidm AS pidm
    FROM taismgr.tbraccd t
    CROSS JOIN params p
    WHERE p.cwid_filter IS NULL
      AND t.tbraccd_term_code = p.target_term
    GROUP BY t.tbraccd_pidm

    UNION ALL

    SELECT DISTINCT i.spriden_pidm AS pidm
    FROM saturn.spriden i
    CROSS JOIN params p
    WHERE p.cwid_filter IS NOT NULL
      AND i.spriden_change_ind IS NULL
      AND i.spriden_id = TRIM(p.cwid_filter)
)
SELECT
    COUNT(*) OVER () AS extract_row_count,
    p.target_term AS extract_target_term,
    t.tbraccd_pidm AS pidm,
    TRIM(t.tbraccd_term_code) AS term_code,
    t.tbraccd_aidy_code AS aidy_code,
    t.tbraccd_tran_number AS tran_number,
    UPPER(TRIM(t.tbraccd_detail_code)) AS detail_code,
    t.tbraccd_amount AS amount,
    t.tbraccd_balance AS stored_balance,
    t.tbraccd_effective_date AS effective_date,
    t.tbraccd_activity_date AS activity_date,
    COALESCE(d.tbbdetc_desc, '[Description unavailable]') AS detail_desc,
    UPPER(TRIM(d.tbbdetc_type_ind)) AS type_ind,
    TRIM(CAST(d.tbbdetc_priority AS text)) AS priority,
    UPPER(TRIM(COALESCE(d.tbbdetc_dcat_code, ''))) AS category_code,
    UPPER(TRIM(COALESCE(d.tbbdetc_tiv_ind, ''))) AS title_iv_ind
FROM refund_scope s
INNER JOIN taismgr.tbraccd t ON t.tbraccd_pidm = s.pidm
LEFT JOIN taismgr.tbbdetc d
    ON d.tbbdetc_detail_code = t.tbraccd_detail_code
CROSS JOIN params p
ORDER BY
    t.tbraccd_pidm,
    t.tbraccd_tran_number;
