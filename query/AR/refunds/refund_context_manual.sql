/*
MANUAL WEBSITE EXPORT 2 OF 2: REFUND ACCOUNT CONTEXT

Use exactly the same target_term_override and cwid_filter as the transaction
query, run this in Insights, and download the complete result as XLSX or CSV.
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
),
current_identity AS MATERIALIZED (
    SELECT
        i.spriden_pidm AS pidm,
        MAX(i.spriden_id) AS cwid,
        MAX(i.spriden_last_name) AS last_name,
        MAX(i.spriden_first_name) AS first_name
    FROM saturn.spriden i
    INNER JOIN refund_scope s ON s.pidm = i.spriden_pidm
    WHERE i.spriden_change_ind IS NULL
    GROUP BY i.spriden_pidm
),
person_controls AS MATERIALIZED (
    SELECT
        b.spbpers_pidm AS pidm,
        MAX(b.spbpers_dead_ind) AS deceased_ind,
        MAX(b.spbpers_dead_date) AS deceased_date,
        MAX(b.spbpers_confid_ind) AS confidential_ind
    FROM saturn.spbpers b
    INNER JOIN refund_scope s ON s.pidm = b.spbpers_pidm
    GROUP BY b.spbpers_pidm
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
    INNER JOIN refund_scope s ON s.pidm = a.tbbacct_pidm
    GROUP BY a.tbbacct_pidm
),
active_ed AS MATERIALIZED (
    SELECT
        h.sprhold_pidm AS pidm,
        COUNT(*) AS active_ed_row_count,
        MAX(h.sprhold_activity_date) AS ed_activity_date
    FROM saturn.sprhold h
    INNER JOIN refund_scope s ON s.pidm = h.sprhold_pidm
    WHERE UPPER(TRIM(h.sprhold_hldd_code)) = 'ED'
      AND CAST(h.sprhold_to_date AS date) = DATE '9999-12-31'
    GROUP BY h.sprhold_pidm
)
SELECT
    COUNT(*) OVER () AS extract_row_count,
    p.target_term AS extract_target_term,
    s.pidm,
    i.cwid,
    i.last_name,
    i.first_name,
    b.deceased_ind,
    b.deceased_date,
    b.confidential_ind,
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
FROM refund_scope s
CROSS JOIN params p
LEFT JOIN current_identity i ON i.pidm = s.pidm
LEFT JOIN person_controls b ON b.pidm = s.pidm
LEFT JOIN account_controls a ON a.pidm = s.pidm
LEFT JOIN active_ed e ON e.pidm = s.pidm
LEFT JOIN faismgr.rlrpapp r ON r.rlrpapp_pidm = s.pidm
ORDER BY
    s.pidm,
    r.rlrpapp_aidy_code,
    r.rlrpapp_activity_date;
