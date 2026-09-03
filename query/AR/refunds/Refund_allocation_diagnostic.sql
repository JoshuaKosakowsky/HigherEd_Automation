/*
Refund allocation diagnostic -- read only, one account, full account history.

Set params.cwid locally before running; NULL intentionally returns no rows.
Do not save or commit the populated identifier or production query results.
The output omits names, CWID, and PIDM so the relevant amounts/configuration can
be reviewed without those identifiers. It remains student financial data.

This query does NOT calculate a refund. It shows full-account source groups
alongside raw stored balances and the current metadata used by Refunds.sql.
AMOUNT and BALANCE retain Banner's raw signs; use TYPE_IND to distinguish C from P.
PRIORITY is the current TBBDETC setting, not a historical application snapshot.
Keep all terms: filtering to the current term could conceal why the full-account
balance differs from target-term stored balances. Zero-net groups remain
visible for reversal/cancellation review.

Uses the tables/columns checked by validate_refund_schema.sql.
*/
WITH params AS (
    SELECT CAST(NULL AS varchar(30)) AS cwid
),
selected_accounts AS (
    SELECT DISTINCT s.spriden_pidm AS pidm
    FROM saturn.spriden s
    CROSS JOIN params p
    WHERE s.spriden_change_ind IS NULL
      AND s.spriden_id = TRIM(p.cwid)
)
SELECT
    t.tbraccd_term_code AS term_code,
    t.tbraccd_aidy_code AS aid_year,
    t.tbraccd_detail_code AS detail_code,
    d.tbbdetc_desc AS detail_description,
    d.tbbdetc_type_ind AS type_ind,
    d.tbbdetc_priority AS priority_raw,
    d.tbbdetc_dcat_code AS category_code,
    d.tbbdetc_tiv_ind AS title_iv_ind,
    COUNT(*) AS transaction_count,
    MIN(t.tbraccd_tran_number) AS first_tran_number,
    MAX(t.tbraccd_tran_number) AS last_tran_number,
    STRING_AGG(
        CONCAT(
            'tran ', t.tbraccd_tran_number,
            ' / amount ', COALESCE(CAST(t.tbraccd_amount AS text), 'NULL'),
            ' / balance ', COALESCE(CAST(t.tbraccd_balance AS text), 'NULL'),
            ' / effective ', COALESCE(
                TO_CHAR(CAST(t.tbraccd_effective_date AS date), 'YYYY-MM-DD'),
                'NULL'
            )
        ),
        ' | ' ORDER BY t.tbraccd_tran_number
    ) AS transaction_detail,
    COUNT(*) FILTER (WHERE t.tbraccd_amount > 0) AS positive_amount_row_count,
    COUNT(*) FILTER (WHERE t.tbraccd_amount < 0) AS negative_amount_row_count,
    COUNT(*) FILTER (WHERE t.tbraccd_amount IS NULL) AS missing_amount_row_count,
    SUM(t.tbraccd_amount) AS net_amount_raw,
    SUM(t.tbraccd_balance) AS net_balance_raw,
    COUNT(*) FILTER (WHERE t.tbraccd_balance IS NULL) AS missing_balance_row_count
FROM selected_accounts a
INNER JOIN taismgr.tbraccd t ON t.tbraccd_pidm = a.pidm
LEFT JOIN taismgr.tbbdetc d
    ON d.tbbdetc_detail_code = t.tbraccd_detail_code
GROUP BY
    t.tbraccd_term_code,
    t.tbraccd_aidy_code,
    t.tbraccd_detail_code,
    d.tbbdetc_desc,
    d.tbbdetc_type_ind,
    d.tbbdetc_priority,
    d.tbbdetc_dcat_code,
    d.tbbdetc_tiv_ind
ORDER BY
    t.tbraccd_term_code DESC,
    d.tbbdetc_type_ind,
    d.tbbdetc_priority DESC,
    t.tbraccd_detail_code,
    t.tbraccd_aidy_code;
