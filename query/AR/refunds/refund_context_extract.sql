/*
Refund allocation account/control extract

The result contains one row per account and PLUS authorization row. Account
controls are aggregated before the authorization join so duplicate control or
hold rows cannot multiply the financial transaction extract.
*/
WITH batch_scope AS MATERIALIZED (
    __REFUND_SCOPE_SQL__
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
