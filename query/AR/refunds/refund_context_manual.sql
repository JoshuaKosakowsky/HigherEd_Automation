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

    /* Conservative TPPY check; Python nets reversals and decides review. */
    SELECT t.tbraccd_pidm AS pidm
    FROM taismgr.tbraccd t
    INNER JOIN taismgr.tbbdetc d ON d.tbbdetc_detail_code = t.tbraccd_detail_code
    CROSS JOIN params p
    WHERE p.cwid_filter IS NULL
      AND t.tbraccd_detail_code = 'TPPY'
      AND UPPER(TRIM(d.tbbdetc_type_ind)) = 'P'
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

),
current_identity AS MATERIALIZED (
    SELECT
        i.spriden_pidm AS pidm,
        MAX(i.spriden_id) AS cwid,
        MAX(i.spriden_last_name) AS last_name,
        MAX(i.spriden_first_name) AS first_name
    FROM saturn.spriden i
    INNER JOIN batch_scope s ON s.pidm = i.spriden_pidm
    WHERE i.spriden_change_ind IS NULL
    GROUP BY i.spriden_pidm
),
person_controls AS MATERIALIZED (
    SELECT
        p.spbpers_pidm AS pidm,
        MAX(p.spbpers_dead_ind) AS deceased_ind,
        MAX(p.spbpers_dead_date) AS deceased_date,
        MAX(p.spbpers_confid_ind) AS confidential_ind
    FROM saturn.spbpers p
    INNER JOIN batch_scope s ON s.pidm = p.spbpers_pidm
    GROUP BY p.spbpers_pidm
),
account_controls AS MATERIALIZED (
    SELECT
        a.tbbacct_pidm AS pidm,
        COUNT(*) AS account_control_row_count,
        MAX(CASE
            WHEN UPPER(TRIM(COALESCE(a.tbbacct_deli_code, ''))) = 'RH'
                THEN 1 ELSE 0
        END) AS refund_hold_count,
        MAX(NULLIF(TRIM(a.tbbacct_deli_code), '')) AS raw_delinquency_code,
        MAX(NULLIF(TRIM(a.tbbacct_refund_ind), '')) AS raw_refund_account_ind,
        MAX(a.tbbacct_activity_date) AS account_control_activity_date
    FROM taismgr.tbbacct a
    INNER JOIN batch_scope s ON s.pidm = a.tbbacct_pidm
    GROUP BY a.tbbacct_pidm
),
active_ed AS MATERIALIZED (
    SELECT
        h.sprhold_pidm AS pidm,
        COUNT(*) AS active_ed_row_count,
        MAX(h.sprhold_activity_date) AS ed_activity_date
    FROM saturn.sprhold h
    INNER JOIN batch_scope s ON s.pidm = h.sprhold_pidm
    WHERE UPPER(TRIM(h.sprhold_hldd_code)) = 'ED'
      AND CAST(h.sprhold_to_date AS date) = DATE '9999-12-31'
    GROUP BY h.sprhold_pidm
)
SELECT
    COUNT(*) OVER () AS extract_row_count,
    s.target_term AS extract_target_term,
    s.pidm,
    i.cwid,
    i.last_name,
    i.first_name,
    p.deceased_ind,
    p.deceased_date,
    p.confidential_ind,
    COALESCE(a.account_control_row_count, 0) AS account_control_row_count,
    COALESCE(a.refund_hold_count, 0) AS refund_hold_count,
    a.raw_delinquency_code,
    a.raw_refund_account_ind,
    a.account_control_activity_date,
    COALESCE(e.active_ed_row_count, 0) AS active_ed_row_count,
    e.ed_activity_date,
    CASE WHEN r.rlrpapp_pidm IS NULL THEN 0 ELSE 1 END AS plus_auth_row_ind,
    r.rlrpapp_aidy_code AS plus_auth_aidy_code,
    r.rlrpapp_plus_to_student AS plus_to_student,
    r.rlrpapp_activity_date AS plus_auth_activity_date
FROM batch_scope s
LEFT JOIN current_identity i ON i.pidm = s.pidm
LEFT JOIN person_controls p ON p.pidm = s.pidm
LEFT JOIN account_controls a ON a.pidm = s.pidm
LEFT JOIN active_ed e ON e.pidm = s.pidm
LEFT JOIN faismgr.rlrpapp r ON r.rlrpapp_pidm = s.pidm
ORDER BY
    s.pidm,
    r.rlrpapp_aidy_code,
    r.rlrpapp_activity_date;
