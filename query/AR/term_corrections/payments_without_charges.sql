/* Read-only term-correction candidates, not instructions to move payments.
   CSH follows the existing cash classification; P alone includes other credits.
   Any C row excludes the term, including zero charges and reversed charges.
   Missing classifications also exclude the term: absence cannot be established.
   Stored negative payment balances represent available credit, not original cash.
*/
WITH params AS (
    SELECT CAST({{payment_term}} AS varchar(6)) AS payment_term
)
SELECT
    s.spriden_id AS "CWID",
    s.spriden_first_name AS "First Name",
    s.spriden_last_name AS "Last Name",
    t.tbraccd_term_code AS "Payment Term",
    t.tbraccd_tran_number AS "Transaction Number",
    t.tbraccd_detail_code AS "Detail Code",
    d.tbbdetc_desc AS "Detail Code Description",
    t.tbraccd_desc AS "Transaction Description",
    t.tbraccd_amount AS "Payment Amount",
    t.tbraccd_balance AS "Payment Balance",
    -t.tbraccd_balance AS "Available Credit",
    t.tbraccd_feed_date AS "Feed Date",
    t.tbraccd_effective_date AS "Effective Date",
    COUNT(*) OVER () AS "Report Row Count"
FROM taismgr.tbraccd t
JOIN taismgr.tbbdetc d
    ON d.tbbdetc_detail_code = t.tbraccd_detail_code
JOIN saturn.spriden s
    ON s.spriden_pidm = t.tbraccd_pidm
   AND s.spriden_change_ind IS NULL
CROSS JOIN params p
WHERE t.tbraccd_term_code = p.payment_term
  AND UPPER(TRIM(d.tbbdetc_type_ind)) = 'P'
  AND UPPER(TRIM(d.tbbdetc_dcat_code)) = 'CSH'
  AND t.tbraccd_amount > 0
  AND t.tbraccd_balance < 0
  /* Student history qualifies first-time future students without multiplying rows. */
  AND EXISTS (
      SELECT 1 FROM saturn.sgbstdn student
      WHERE student.sgbstdn_pidm = t.tbraccd_pidm
  )
  AND NOT EXISTS (
      SELECT 1
      FROM taismgr.tbraccd term_activity
      LEFT JOIN taismgr.tbbdetc term_detail
          ON term_detail.tbbdetc_detail_code = term_activity.tbraccd_detail_code
      WHERE term_activity.tbraccd_pidm = t.tbraccd_pidm
        AND term_activity.tbraccd_term_code = t.tbraccd_term_code
        AND (
            term_detail.tbbdetc_type_ind IS NULL
            OR UPPER(TRIM(term_detail.tbbdetc_type_ind)) <> 'P'
        )
  )
ORDER BY s.spriden_id, t.tbraccd_tran_number;
