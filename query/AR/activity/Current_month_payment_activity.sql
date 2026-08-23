/* Current-month activity for the listed payment and card-fee detail codes. */
SELECT
    s.spriden_id             AS "CWID",
    s.spriden_first_name     AS "First Name",
    s.spriden_last_name      AS "Last Name",
    t.tbraccd_term_code      AS "Term",
     -- Update, change from detail code to category
    t.tbraccd_detail_code    AS "Detail Code",

    -- CFEE transaction fee, identified as to not pay down students balance.
    CASE
        WHEN t.tbraccd_detail_code = 'CFEE'
        THEN 'Credit Card Fee'
        ELSE 'Payment'
    END                      AS "Transaction Type",

    t.tbraccd_amount         AS "Amount",
    t.tbraccd_balance        AS "Balance",
    t.tbraccd_feed_date      AS "Feed Date",
    t.tbraccd_tran_number    AS "Transaction Number"

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
        'ACHK', 'CASH', 'CRVS', 'CRVC', 'CRMC',
        'CRED', 'CRDS', 'CRAM', 'CHCK', 'CFEE'
    )

    -- Transactions since the first day of the current month.
    AND t.tbraccd_feed_date >= date_trunc('month', CURRENT_DATE)

ORDER BY
    s.spriden_id,
    t.tbraccd_feed_date DESC,
    t.tbraccd_tran_number;
