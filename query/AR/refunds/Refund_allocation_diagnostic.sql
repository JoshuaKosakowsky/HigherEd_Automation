/*
Refund allocation diagnostic -- read only, one account, full account history.

Set params.cwid locally before running; NULL intentionally returns no rows.
Do not save or commit the populated identifier or production query results.
The output omits names, CWID, and PIDM so the relevant amounts/configuration can
be reviewed without those identifiers. It remains student financial data.

This query does NOT calculate a refund or infer payment application. It shows
full-account source groups alongside raw stored balances; Refunds.sql allocates
only the target-term groups, while other terms here provide context. AMOUNT and
BALANCE retain Banner's raw signs; use TYPE_IND to distinguish C from P.
PRIORITY is the current TBBDETC setting, not a historical application snapshot.
Keep all terms: filtering to the current term could conceal why the full-account
allocation differs from a current-term calculation. Zero-net groups remain
visible for reversal/cancellation review.

Uses the tables/columns checked by validate_refund_schema.sql.
*/
WITH params AS (
    SELECT CAST(NULL AS varchar(30)) AS cwid
)
SELECT
    t.tbraccd_term_code AS term_code,
    t.tbraccd_aidy_code AS aid_year,
    t.tbraccd_detail_code AS detail_code,
    d.tbbdetc_desc AS detail_description,
    d.tbbdetc_type_ind AS type_ind,
    d.tbbdetc_priority AS priority_raw,
    COUNT(*) AS transaction_count,
    COUNT(*) FILTER (WHERE t.tbraccd_amount > 0) AS positive_amount_row_count,
    COUNT(*) FILTER (WHERE t.tbraccd_amount < 0) AS negative_amount_row_count,
    COUNT(*) FILTER (WHERE t.tbraccd_amount IS NULL) AS missing_amount_row_count,
    SUM(t.tbraccd_amount) AS net_amount_raw,
    SUM(t.tbraccd_balance) AS net_balance_raw,
    COUNT(*) FILTER (WHERE t.tbraccd_balance IS NULL) AS missing_balance_row_count
FROM taismgr.tbraccd t
LEFT JOIN taismgr.tbbdetc d
    ON d.tbbdetc_detail_code = t.tbraccd_detail_code
WHERE EXISTS (
    SELECT 1
    FROM saturn.spriden s
    CROSS JOIN params p
    WHERE s.spriden_pidm = t.tbraccd_pidm
      AND s.spriden_change_ind IS NULL
      AND s.spriden_id = TRIM(p.cwid)
)
GROUP BY
    t.tbraccd_term_code,
    t.tbraccd_aidy_code,
    t.tbraccd_detail_code,
    d.tbbdetc_desc,
    d.tbbdetc_type_ind,
    d.tbbdetc_priority
ORDER BY
    t.tbraccd_term_code DESC,
    d.tbbdetc_type_ind,
    d.tbbdetc_priority DESC,
    t.tbraccd_detail_code,
    t.tbraccd_aidy_code;
