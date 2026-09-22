/* Previous calendar month's TBRACCD transaction detail. */
SELECT
    s.spriden_id             AS "CWID",
    s.spriden_first_name     AS "First Name",
    s.spriden_last_name      AS "Last Name",
    t.tbraccd_term_code      AS "Term",
    t.tbraccd_detail_code    AS "Detail Code",
    d.tbbdetc_desc           AS "Detail Code Description",
    d.tbbdetc_dcat_code      AS "Category",
    t.tbraccd_amount         AS "Amount",
    t.tbraccd_balance        AS "Balance",
    d.tbbdetc_type_ind       AS "Charge or Payment",
    t.tbraccd_feed_date      AS "Feed Date",
    t.tbraccd_tran_number    AS "Transaction Number",
    d.tbbdetc_priority       AS "Priority"
FROM tbraccd t
JOIN spriden s
    ON t.tbraccd_pidm = s.spriden_pidm
   AND s.spriden_change_ind IS NULL
LEFT JOIN tbbdetc d
    ON t.tbraccd_detail_code = d.tbbdetc_detail_code
WHERE t.tbraccd_feed_date >= date_trunc('month', CURRENT_DATE) - INTERVAL '1 month'
  AND t.tbraccd_feed_date < date_trunc('month', CURRENT_DATE)
ORDER BY
    s.spriden_id,
    t.tbraccd_feed_date DESC,
    t.tbraccd_tran_number DESC;
