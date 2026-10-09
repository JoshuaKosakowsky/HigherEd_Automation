/* Staff-facing Insights/Metabase report: Banner activity by feed date.
   start_date/end_date: basic Date variables, both inclusive calendar dates.
   Widget labels: Start Feed Date (inclusive), End Feed Date (inclusive).
   detail_codes: required Field Filter mapped to TBRACCD_DETAIL_CODE;
   table/field alias t.tbraccd_detail_code.
   General-purpose extract for any selected detail codes and feed-date range.
   Preserve Description: sponsor-account rows may identify the student there.
*/
SELECT
    s.spriden_id AS "'ID'",
    TRIM(COALESCE(s.spriden_last_name, '') || ', ' ||
         COALESCE(s.spriden_first_name, '')) AS "'Name'",
    t.tbraccd_detail_code AS "'Detail Code'",
    t.tbraccd_desc AS "'Description'",
    t.tbraccd_amount AS "'Amount'",
    t.tbraccd_balance AS "'Balance'",
    t.tbraccd_term_code AS "'Term'",
    t.tbraccd_aidy_code AS "'Aid Year'",
    t.tbraccd_feed_doc_code AS "'Feed Document'",
    t.tbraccd_feed_date AS "'Feed Date'",
    d.tbbdetc_desc AS detail_code_description,
    t.tbraccd_user AS "Transaction User"
FROM taismgr.tbraccd t
LEFT JOIN saturn.spriden s
    ON s.spriden_pidm = t.tbraccd_pidm
   AND s.spriden_change_ind IS NULL
LEFT JOIN taismgr.tbbdetc d
    ON d.tbbdetc_detail_code = t.tbraccd_detail_code
WHERE t.tbraccd_feed_date >= CAST({{start_date}} AS date)
  AND t.tbraccd_feed_date < CAST({{end_date}} AS date) + INTERVAL '1 day'
  AND CAST({{start_date}} AS date) <= CAST({{end_date}} AS date)
  AND {{detail_codes}}
ORDER BY t.tbraccd_feed_date, t.tbraccd_feed_doc_code,
         t.tbraccd_pidm, t.tbraccd_tran_number;
