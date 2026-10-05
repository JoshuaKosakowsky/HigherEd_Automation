/* Full account history preserves advance/late payments and cross-term context.
   Do not filter effective/activity dates to the tax year or sum payments as tuition. */
WITH __TL11A_SCOPE_SQL__
SELECT COUNT(*) OVER () AS extract_row_count,
       p.tax_year AS extract_tax_year, i.pidm,
       t.tbraccd_tran_number AS tran_number,
       TRIM(t.tbraccd_term_code) AS term_code,
       terms.stvterm_desc AS term_description,
       CASE WHEN y.term_code IS NULL THEN 'N' ELSE 'Y' END AS year_term_candidate,
       UPPER(TRIM(t.tbraccd_detail_code)) AS detail_code,
       d.tbbdetc_desc AS description,
       UPPER(TRIM(d.tbbdetc_type_ind)) AS type_ind,
       UPPER(TRIM(d.tbbdetc_dcat_code)) AS category_code,
       t.tbraccd_amount AS amount_usd,
       t.tbraccd_balance AS stored_balance_usd,
       t.tbraccd_effective_date AS effective_date,
       t.tbraccd_activity_date AS activity_date,
       t.tbraccd_entry_date AS entry_date,
       t.tbraccd_feed_date AS feed_date
FROM identity i
INNER JOIN taismgr.tbraccd t ON t.tbraccd_pidm = i.pidm
CROSS JOIN params p
LEFT JOIN taismgr.tbbdetc d ON d.tbbdetc_detail_code = t.tbraccd_detail_code
LEFT JOIN saturn.stvterm terms ON terms.stvterm_code = t.tbraccd_term_code
LEFT JOIN year_terms y ON y.term_code = t.tbraccd_term_code
ORDER BY t.tbraccd_tran_number;
