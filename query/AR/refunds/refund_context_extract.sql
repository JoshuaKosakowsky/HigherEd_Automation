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
sponsor_terms AS MATERIALIZED (
    SELECT s.pidm, s.current_term AS term_code FROM batch_scope s
    UNION
    SELECT t.tbraccd_pidm, t.tbraccd_term_code
    FROM batch_scope s
    INNER JOIN taismgr.tbraccd t ON t.tbraccd_pidm = s.pidm
    WHERE t.tbraccd_detail_code IN ('TPPY', 'Z0LE', 'C529')
),
sponsor_attachments AS MATERIALIZED (
    -- Keep attachment history for manual review; do not guess deletion/auth rules.
    SELECT DISTINCT cs.tbbcstu_stu_pidm AS pidm,
        cs.tbbcstu_contract_pidm AS sponsor_pidm,
        NULLIF(TRIM(CONCAT_WS(' ', i.spriden_last_name, i.spriden_first_name)), '') AS sponsor_name,
        NULLIF(TRIM(i.spriden_id), '') AS sponsor_id,
        NULLIF(TRIM(CAST(cs.tbbcstu_contract_number AS text)), '') AS contract_number
    FROM sponsor_terms s
    INNER JOIN taismgr.tbbcstu cs
        ON cs.tbbcstu_stu_pidm = s.pidm
       AND cs.tbbcstu_term_code = s.term_code
    LEFT JOIN saturn.spriden i
        ON i.spriden_pidm = cs.tbbcstu_contract_pidm
       AND i.spriden_change_ind IS NULL
),
sponsor_context AS MATERIALIZED (
    -- Aggregate before joining PLUS authorizations: never multiply financial rows.
    SELECT pidm,
        STRING_AGG(COALESCE(sponsor_name, '[Name unavailable]'), ' | '
            ORDER BY sponsor_id NULLS LAST, sponsor_pidm, contract_number NULLS LAST) AS sponsor_names,
        STRING_AGG(COALESCE(sponsor_id, '[ID unavailable]'), ' | '
            ORDER BY sponsor_id NULLS LAST, sponsor_pidm, contract_number NULLS LAST) AS sponsor_ids,
        STRING_AGG(COALESCE(contract_number, '[Number unavailable]'), ' | '
            ORDER BY sponsor_id NULLS LAST, sponsor_pidm, contract_number NULLS LAST) AS contract_numbers
    FROM sponsor_attachments
    GROUP BY pidm
),
active_ed AS MATERIALIZED (
    SELECT
        h.sprhold_pidm AS pidm,
        COUNT(*) AS active_ed_row_count,
        MAX(h.sprhold_activity_date) AS ed_activity_date
    FROM saturn.sprhold h
    INNER JOIN batch_scope s ON s.pidm = h.sprhold_pidm
    WHERE UPPER(TRIM(h.sprhold_hldd_code)) = 'ED'
      -- Banner and cashnet use different far-future ED end dates.
      AND CAST(h.sprhold_to_date AS date) >= DATE '2099-12-31'
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
    sc.sponsor_names,
    sc.sponsor_ids,
    sc.contract_numbers,
    CASE WHEN r.rlrpapp_pidm IS NULL THEN 0 ELSE 1 END AS plus_auth_row_ind,
    r.rlrpapp_aidy_code AS plus_auth_aidy_code,
    r.rlrpapp_plus_to_student AS plus_to_student,
    r.rlrpapp_activity_date AS plus_auth_activity_date
FROM batch_scope s
LEFT JOIN current_identity i ON i.pidm = s.pidm
LEFT JOIN person_controls p ON p.pidm = s.pidm
LEFT JOIN account_controls a ON a.pidm = s.pidm
LEFT JOIN active_ed e ON e.pidm = s.pidm
LEFT JOIN sponsor_context sc ON sc.pidm = s.pidm
LEFT JOIN faismgr.rlrpapp r ON r.rlrpapp_pidm = s.pidm
ORDER BY
    s.pidm,
    r.rlrpapp_aidy_code,
    r.rlrpapp_activity_date;
