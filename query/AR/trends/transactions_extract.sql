/* Annual trends: all activity by Feed Date, July through June.
   Disjoint monthly windows; PIDM/transaction keyset pages preserve duplicate
   amounts and descriptions. Count is evaluated before LIMIT and API caps.
   Identity join preserves accounts without a current SPRIDEN identity.
   Balance is the current replicated balance, not a historical FY-end snapshot.
*/
SELECT
    s.spriden_id AS "ID",
    t.tbraccd_detail_code AS "Detail Code",
    t.tbraccd_desc AS "Description",
    t.tbraccd_amount AS "Amount",
    t.tbraccd_balance AS "Balance",
    t.tbraccd_term_code AS "Term",
    t.tbraccd_pidm AS extract_pidm,
    t.tbraccd_tran_number AS extract_transaction,
    COUNT(*) OVER () AS extract_remaining_count
FROM taismgr.tbraccd t
LEFT JOIN saturn.spriden s
    ON s.spriden_pidm = t.tbraccd_pidm
   AND s.spriden_change_ind IS NULL
WHERE t.tbraccd_feed_date >= DATE '__START_DATE__'
  AND t.tbraccd_feed_date < DATE '__END_DATE__'
  AND __CURSOR_FILTER__
ORDER BY t.tbraccd_pidm, t.tbraccd_tran_number
LIMIT __PAGE_SIZE__;
