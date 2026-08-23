/* Selected loan-detail-code activity for the configured historical window. */
SELECT
    s.spriden_id                AS "CWID",
    s.spriden_first_name        AS "First Name",
    s.spriden_last_name         AS "Last Name",
    t.tbraccd_term_code         AS "Term",
     -- Update, change from detail code to category
    t.tbraccd_detail_code       AS "Detail Code",
    SUM(t.tbraccd_amount)       AS "Amount",
    MIN(t.tbraccd_feed_date)    AS "Earliest Feed Date"

-- Transaction table
FROM tbraccd t

-- Student table
JOIN spriden s
    ON s.spriden_pidm = t.tbraccd_pidm

    -- Use only the student's current identity record.
    -- Prevents historical names/IDs from duplicating transactions.
    -- CWID matters most, not a name change
   AND s.spriden_change_ind IS NULL

WHERE
    -- Payment Codes and CC Fee.
    -- Update, change from detail code to category
    --
    t.tbraccd_detail_code IN (
        'PERK', 'CLTL', 'CPAR', 'CCOM', 'CFDN',
        '', 'CWLC', '', 'LEWL', 'L001'
    )

    -- Transactions since the first day of the current month.
    AND t.tbraccd_feed_date >= date_trunc('month', CURRENT_DATE) - INTERVAL '2 month' -- Change interval to capture last month in September to verify correectness
	AND t.tbraccd_feed_date <  date_trunc('month', CURRENT_DATE)

GROUP BY
    s.spriden_id,
    s.spriden_first_name,
    s.spriden_last_name,
	t.tbraccd_term_code,
	t.tbraccd_amount,
    t.tbraccd_detail_code

ORDER BY
    s.spriden_id,
    t.tbraccd_detail_code;
