/* MANUAL WEBSITE EXPORT: download the complete result as XLSX or CSV.
Use identical run_date, target_term_override and cwid_filter in both exports.
Defaults: today's term, entire candidate population. Never commit a CWID.
Generated from the extract template and refund_scope.sql; regenerate when either changes. */
WITH batch_scope AS MATERIALIZED (
    /* Shared candidate selection for both exports. Render through extract.py.
   The two-year window selects accounts; it never truncates their history. */
WITH run_settings AS (
    SELECT
        CURRENT_DATE AS run_date,
        CAST(NULL AS varchar(6)) AS target_term_override,
        CAST(NULL AS varchar(30)) AS cwid_filter
),
scope_dates AS (
    SELECT *, CAST(run_date - INTERVAL '2 years' AS date) AS lookback_date
    FROM run_settings
),
params AS (
    SELECT
        run_date,
        CAST(COALESCE(target_term_override, CONCAT(
            CAST(EXTRACT(YEAR FROM run_date) AS integer),
            CASE
                WHEN run_date <= MAKE_DATE(CAST(EXTRACT(YEAR FROM run_date) AS integer), 5, 15) THEN '10'
                WHEN run_date <= MAKE_DATE(CAST(EXTRACT(YEAR FROM run_date) AS integer), 7, 15) THEN '55'
                ELSE '80'
            END
        )) AS varchar(6)) AS target_term,
        CAST(CONCAT(
            CAST(EXTRACT(YEAR FROM lookback_date) AS integer),
            CASE
                WHEN lookback_date <= MAKE_DATE(CAST(EXTRACT(YEAR FROM lookback_date) AS integer), 5, 15) THEN '10'
                WHEN lookback_date <= MAKE_DATE(CAST(EXTRACT(YEAR FROM lookback_date) AS integer), 7, 15) THEN '55'
                ELSE '80'
            END
        ) AS varchar(6)) AS lookback_term,
        cwid_filter
    FROM scope_dates
),
candidate_pidms AS MATERIALIZED (
    SELECT t.tbraccd_pidm AS pidm
    FROM taismgr.tbraccd t
    CROSS JOIN params p
    WHERE p.cwid_filter IS NULL
      AND t.tbraccd_term_code = p.target_term
      AND MOD(ABS(t.tbraccd_pidm), 1) = 0

    UNION

    /* Conservative HOMP candidate check; Python nets reversals and decides review. */
    SELECT t.tbraccd_pidm AS pidm
    FROM taismgr.tbraccd t
    INNER JOIN taismgr.tbbdetc d ON d.tbbdetc_detail_code = t.tbraccd_detail_code
    CROSS JOIN params p
    WHERE p.cwid_filter IS NULL
      AND t.tbraccd_detail_code = 'HOMP'
      AND UPPER(TRIM(d.tbbdetc_type_ind)) = 'C'
      AND t.tbraccd_amount > 0
      AND (t.tbraccd_term_code = p.target_term OR (
          t.tbraccd_effective_date >= p.run_date - INTERVAL '32 days'
          AND t.tbraccd_effective_date < p.run_date + INTERVAL '1 day'
      ))
      AND MOD(ABS(t.tbraccd_pidm), 1) = 0

    UNION

    SELECT t.tbraccd_pidm AS pidm
    FROM taismgr.tbraccd t
    INNER JOIN taismgr.tbbdetc d ON d.tbbdetc_detail_code = t.tbraccd_detail_code
    CROSS JOIN params p
    WHERE p.cwid_filter IS NULL
      AND t.tbraccd_term_code >= p.lookback_term
      AND t.tbraccd_term_code <= p.target_term
      AND t.tbraccd_balance < 0
      AND UPPER(TRIM(d.tbbdetc_type_ind)) = 'P'
      AND MOD(ABS(t.tbraccd_pidm), 1) = 0

    UNION

    SELECT i.spriden_pidm AS pidm
    FROM saturn.spriden i
    CROSS JOIN params p
    WHERE p.cwid_filter IS NOT NULL
      AND i.spriden_change_ind IS NULL
      AND i.spriden_id = TRIM(p.cwid_filter)
      AND MOD(ABS(i.spriden_pidm), 1) = 0
),
account_balances AS MATERIALIZED (
    /* Full history for selected accounts only. Positive balances are out of scope.
       Keep uncertain balances for Python's data-quality checks rather than
       silently inferring a credit from missing amounts or classifications. */
    SELECT
        c.pidm,
        SUM(CASE UPPER(TRIM(d.tbbdetc_type_ind))
            WHEN 'P' THEN -t.tbraccd_amount
            WHEN 'C' THEN t.tbraccd_amount
        END) AS full_account_balance,
        COUNT(*) FILTER (WHERE t.tbraccd_amount IS NULL
            OR d.tbbdetc_type_ind IS NULL
            OR UPPER(TRIM(d.tbbdetc_type_ind)) NOT IN ('C', 'P')) AS invalid_rows
    FROM candidate_pidms c
    INNER JOIN taismgr.tbraccd t ON t.tbraccd_pidm = c.pidm
    LEFT JOIN taismgr.tbbdetc d ON d.tbbdetc_detail_code = t.tbraccd_detail_code
    GROUP BY c.pidm
)
SELECT a.pidm, p.target_term
FROM account_balances a
CROSS JOIN params p
WHERE ROUND(a.full_account_balance, 2) <= 0 OR a.invalid_rows > 0

)
SELECT
    COUNT(*) OVER () AS extract_row_count,
    s.target_term AS extract_target_term,
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
FROM batch_scope s
INNER JOIN taismgr.tbraccd t
    ON t.tbraccd_pidm = s.pidm
LEFT JOIN taismgr.tbbdetc d
    ON d.tbbdetc_detail_code = t.tbraccd_detail_code
ORDER BY
    t.tbraccd_pidm,
    t.tbraccd_tran_number;
