/*
Refund allocation transaction extract

This is intentionally a flat, non-recursive query. The Python refund workflow
replaces the expensive SQL allocation engine and substitutes the validated
tokens below before execution. Do not run this template directly in Insights.
*/
WITH batch_scope AS MATERIALIZED (
    __REFUND_SCOPE_SQL__
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
