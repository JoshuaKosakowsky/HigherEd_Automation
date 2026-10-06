/* One raw TBRAPPL record, without grouping, sign changes or date filtering.
   Preserve reapplications and direct-payment flags until their meaning is
   reconciled. Link transaction numbers locally to avoid multiplying rows. */
WITH __TL11A_SCOPE_SQL__
SELECT COUNT(*) OVER () AS extract_row_count,
       p.tax_year AS extract_tax_year, i.pidm,
       a.tbrappl_surrogate_id AS application_id,
       a.tbrappl_version AS application_version,
       a.tbrappl_pay_tran_number AS payment_tran_number,
       a.tbrappl_chg_tran_number AS charge_tran_number,
       a.tbrappl_amount AS application_amount_usd,
       a.tbrappl_direct_pay_ind AS direct_payment_ind,
       a.tbrappl_reappl_ind AS reapplication_ind,
       a.tbrappl_direct_pay_type AS direct_payment_type,
       a.tbrappl_activity_date AS application_activity_date,
       a.tbrappl_feed_date AS application_feed_date
FROM identity i
INNER JOIN taismgr.tbrappl a ON a.tbrappl_pidm = i.pidm
CROSS JOIN params p
ORDER BY a.tbrappl_surrogate_id;
