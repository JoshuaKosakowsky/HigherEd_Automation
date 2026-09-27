/* TBRACCD transactions fed in the selected calendar month for TBB recon. */
SELECT
    s.spriden_id AS "'ID'",
    TRIM(COALESCE(s.spriden_last_name, '') || ', ' || COALESCE(s.spriden_first_name, '')) AS "'Name'",
    d.tbbdetc_desc AS tbbdetc_desc,
    t.*,
    COUNT(*) OVER () AS extract_row_count
FROM tbraccd t
JOIN spriden s
    ON s.spriden_pidm = t.tbraccd_pidm
   AND s.spriden_change_ind IS NULL
LEFT JOIN tbbdetc d
    ON d.tbbdetc_detail_code = t.tbraccd_detail_code
WHERE t.tbraccd_detail_code IN ('FRST', 'BOOK')
  AND t.tbraccd_feed_date >= DATE '__START_DATE__'
  AND t.tbraccd_feed_date < DATE '__END_DATE__'
  AND __BATCH_FILTER__
ORDER BY s.spriden_id, t.tbraccd_feed_date, t.tbraccd_tran_number;
