/* Previous calendar month's activity for the existing payment and card-fee codes. */
SELECT
    s.spriden_id             AS "CWID",
    s.spriden_first_name     AS "First Name",
    s.spriden_last_name      AS "Last Name",
    t.tbraccd_term_code      AS "Term",
    t.tbraccd_detail_code    AS "Detail Code",
    CASE
        WHEN t.tbraccd_detail_code = 'CFEE'
        THEN 'Credit Card Fee'
        ELSE 'Payment'
    END                      AS "Transaction Type",
    t.tbraccd_amount         AS "Amount",
    t.tbraccd_balance        AS "Balance",
    t.tbraccd_feed_date      AS "Feed Date",
    t.tbraccd_tran_number    AS "Transaction Number"
FROM tbraccd t
JOIN spriden s
    ON s.spriden_pidm = t.tbraccd_pidm
   AND s.spriden_change_ind IS NULL
WHERE t.tbraccd_detail_code IN (
    'ACHK', 'CASH', 'CRVS', 'CRVC', 'CRMC',
    'CRED', 'CRDS', 'CRAM', 'CHCK', 'CFEE'
)
  AND t.tbraccd_feed_date >= date_trunc('month', CURRENT_DATE) - INTERVAL '1 month'
  AND t.tbraccd_feed_date < date_trunc('month', CURRENT_DATE)
ORDER BY
    s.spriden_id,
    t.tbraccd_feed_date DESC,
    t.tbraccd_tran_number;
